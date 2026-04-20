"""Gemini manual function-calling loop (_run_with_tools) and output fixer (_run_fixer).

Uses manual function-calling (not AFC) so we can inject multimodal parts — specifically,
desktop_screenshot() returns a ScreenshotResult with raw PNG bytes, which the loop sends
back to the model as an inline image alongside the function response text.
"""

from __future__ import annotations

import concurrent.futures as _cf
import contextvars as _cv
import inspect
import logging
import threading
from typing import List, Tuple

from .config import OUTPUT_DIR
from .desktop_live_snapshot import build_user_message_with_live_screen
from .desktop_skill import DESKTOP_TOOLS_OK_FAIL
from .llm_client import (
    GEMINI_MODEL,
    _perplexity_from_content,
    _track_tokens,
    get_client,
    token_summary,
)
from .prompts_loaded import _SYSTEM_AGENT, _worker_system
from .roles import ROLES
from .tool_registry import _TOOL_CALLABLES, _dev_tools_for_attempt, ScreenshotResult

logger = logging.getLogger("company")


def _build_initial_contents(prompt: str, role_key: str):
    """Return a list of Content objects for the first user turn."""
    from google.genai import types as _gtypes

    initial_msg = build_user_message_with_live_screen(prompt, role_key)
    if isinstance(initial_msg, list):
        # [text_str, image_Part]
        parts = [_gtypes.Part.from_text(text=initial_msg[0])] + [
            p if isinstance(p, _gtypes.Part) else _gtypes.Part.from_text(text=str(p))
            for p in initial_msg[1:]
        ]
        logger.info(f"  first turn includes live desktop PNG ({len(parts)} parts)")
    else:
        parts = [_gtypes.Part.from_text(text=initial_msg)]
    return [_gtypes.Content(role="user", parts=parts)]


def _run_with_tools(
    prompt: str,
    role_key: str,
    label: str,
    retry_count: int = 0,
) -> Tuple[str, List[str], float]:
    """
    Run a prompt through Gemini with a manual function-calling loop.
    Unlike AFC, we execute tools ourselves and build the function response Content,
    which lets us attach ScreenshotResult PNG bytes as inline image parts so the model
    sees the actual screen rather than a text description.
    Returns (final_text, tool_result_strings, perplexity_estimate).
    """
    from google.genai import types as _gtypes

    _AGENT_TIMEOUT = 240
    _MAX_AGENT_RETRIES = 3
    _MAX_TOOL_CALLS = 10_000  # effectively unlimited

    _tool_invocations: List[str] = []
    _tool_inv_lock = threading.Lock()

    def _run_loop() -> Tuple[str, List[str]]:
        import typing as _typing_mod

        names = _dev_tools_for_attempt(role_key, retry_count)
        # Dict keyed by tool name for O(1) lookup during the function-call loop
        raw_fns = {n: _TOOL_CALLABLES[n] for n in names if n in _TOOL_CALLABLES}
        system = _worker_system(role_key) + "\n\n" + _SYSTEM_AGENT
        _consec_list_files = [0]

        def _make_counted(fn):
            def _wrapper(*args, **kwargs):
                arg_repr = str(kwargs or args)[:200]
                is_list = fn.__name__ == "list_files"
                with _tool_inv_lock:
                    if is_list:
                        _consec_list_files[0] += 1
                        run_n = _consec_list_files[0]
                    else:
                        _consec_list_files[0] = 0
                        run_n = 0
                if is_list:
                    logger.warning(f"  [{label}] list_files called (consecutive #{run_n})")
                try:
                    result = fn(*args, **kwargs)
                    _tn = fn.__name__
                    # For desktop tools, tag ok/fail based on the text portion of the result
                    result_text = result.text if isinstance(result, ScreenshotResult) else result
                    if _tn in DESKTOP_TOOLS_OK_FAIL:
                        _dok = (
                            isinstance(result_text, str)
                            and not str(result_text).lstrip().upper().startswith("ERROR")
                        )
                        entry = f"[TOOL: {_tn}|{'ok' if _dok else 'fail'}] {arg_repr}"
                    else:
                        entry = f"[TOOL: {_tn}] {arg_repr}"
                    with _tool_inv_lock:
                        _tool_invocations.append(entry)
                    if is_list:
                        logger.info(f"  [{label}] list_files result →\n{result_text}")
                    elif isinstance(result, ScreenshotResult):
                        logger.info(f"  [{label}] tool {fn.__name__}: PNG {len(result.png_bytes or b'')} bytes")
                    else:
                        logger.info(f"  [{label}] tool {fn.__name__}: {arg_repr[:80]}")
                    return result
                except Exception as _tool_err:
                    entry = f"[TOOL ERROR: {fn.__name__}] {arg_repr} -> {_tool_err}"
                    with _tool_inv_lock:
                        _tool_invocations.append(entry)
                    logger.error(f"  [{label}] tool {fn.__name__} RAISED: {_tool_err}")
                    raise

            _wrapper.__name__ = fn.__name__
            _wrapper.__qualname__ = fn.__qualname__
            _wrapper.__doc__ = fn.__doc__
            _wrapper.__module__ = fn.__module__

            try:
                raw_sig = inspect.signature(fn, follow_wrapped=False)
                try:
                    hints = _typing_mod.get_type_hints(fn)
                except Exception:
                    hints = {}
                new_params = []
                for pname, param in raw_sig.parameters.items():
                    if pname in hints:
                        param = param.replace(annotation=hints[pname])
                    new_params.append(param)
                ret_ann = hints.get("return", inspect.Parameter.empty)
                _wrapper.__signature__ = raw_sig.replace(
                    parameters=new_params, return_annotation=ret_ann
                )
            except Exception as _sig_err:
                logger.warning(f"[_make_counted] could not build signature for {fn.__name__}: {_sig_err}")

            return _wrapper

        counted_fns = {name: _make_counted(fn) for name, fn in raw_fns.items()}

        # Config: pass tool callables for function declarations (SDK converts them),
        # but NO automatic_function_calling — we drive the loop ourselves.
        cfg = _gtypes.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=8096,
            tools=list(counted_fns.values()) if counted_fns else [],
            automatic_function_calling=_gtypes.AutomaticFunctionCallingConfig(disable=True),
        )

        contents = _build_initial_contents(prompt, role_key)
        tool_call_count = 0
        final_text = ""

        for _turn in range(_MAX_TOOL_CALLS + 2):
            r = get_client().models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
                config=cfg,
            )
            _track_tokens(r)

            # Append model turn to history
            if r.candidates:
                contents.append(r.candidates[0].content)

            # Collect any function calls from this response
            fn_calls = []
            if r.candidates:
                for part in (r.candidates[0].content.parts or []):
                    if hasattr(part, "function_call") and part.function_call:
                        fn_calls.append(part.function_call)

            if not fn_calls:
                # No more function calls — this is the final model turn
                final_text = (getattr(r, "text", "") or "").strip()
                break

            # Execute all function calls and build the user response turn
            response_parts: List[_gtypes.Part] = []
            for fc in fn_calls:
                tool_call_count += 1
                fn = counted_fns.get(fc.name)
                if fn is None:
                    response_parts.append(_gtypes.Part.from_function_response(
                        name=fc.name,
                        response={"error": f"unknown tool: {fc.name}"},
                    ))
                    continue
                try:
                    result = fn(**dict(fc.args or {}))
                    if isinstance(result, ScreenshotResult):
                        # Send metadata text as function response + PNG as inline image
                        response_parts.append(_gtypes.Part.from_function_response(
                            name=fc.name,
                            response={"result": result.text},
                        ))
                        if result.png_bytes:
                            response_parts.append(
                                _gtypes.Part.from_bytes(data=result.png_bytes, mime_type="image/png")
                            )
                    else:
                        response_parts.append(_gtypes.Part.from_function_response(
                            name=fc.name,
                            response={"result": str(result) if result is not None else ""},
                        ))
                except Exception as exc:
                    response_parts.append(_gtypes.Part.from_function_response(
                        name=fc.name,
                        response={"error": str(exc)},
                    ))

            contents.append(_gtypes.Content(role="user", parts=response_parts))

        with _tool_inv_lock:
            collected = list(_tool_invocations)
        logger.info(f"[{label}] agent finished — {len(collected)} tool invocations, {tool_call_count} tool calls")
        return final_text, collected

    last_err = ""
    text = ""
    tool_results: List[str] = []
    logger.info(f"[{label}] -- Gemini manual function-calling loop (role={role_key}, prompt={len(prompt)}c)")

    for _attempt in range(1, _MAX_AGENT_RETRIES + 1):
        _ctx = _cv.copy_context()
        _ex = _cf.ThreadPoolExecutor(max_workers=1)
        try:
            _fut = _ex.submit(_ctx.run, _run_loop)
            try:
                text, tool_results = _fut.result(timeout=_AGENT_TIMEOUT)
                break
            except _cf.TimeoutError:
                last_err = f"agent timed out after {_AGENT_TIMEOUT}s"
                logger.warning(f"[{label}] {last_err} (attempt {_attempt}/{_MAX_AGENT_RETRIES})")
                _fut.cancel()
            except Exception as e:
                last_err = str(e)
                logger.warning(f"[{label}] agent error: {e} (attempt {_attempt}/{_MAX_AGENT_RETRIES})")
                if "429" in last_err or "RESOURCE_EXHAUSTED" in last_err:
                    _backoff = 5 * (2 ** (_attempt - 1))
                    logger.info(f"[{label}] rate-limited — waiting {_backoff}s before retry")
                    import time as _time
                    _time.sleep(_backoff)
        finally:
            _ex.shutdown(wait=False)
    else:
        logger.error(f"[{label}] all {_MAX_AGENT_RETRIES} attempts failed -- {last_err}")
        return f"[ERROR: {last_err}]\nSTANCE: PRAGMATIC", [], 10.0

    # Fallback: if agent produced no meaningful summary, synthesise from tool outputs
    used_fallback = False
    if len(text) < 150 and tool_results:
        tool_summary = "\n".join(tool_results[:6])
        fallback_prompt = (
            f"You just used these tools:\n{tool_summary}\n\n"
            "Write a detailed technical summary of what was built, key decisions, "
            "and integration notes. End with: STANCE: [MINIMAL|ROBUST|SCALABLE|PRAGMATIC]"
        )
        import software_company as _sc

        text = _sc.llm_call(
            fallback_prompt, label=f"{label}_summary", get_logprobs=False, system=_SYSTEM_AGENT
        )
        used_fallback = True
        logger.info(f"[{label}] fallback summary triggered ({len(text)}c)")

    logger.info(
        f"[{label}] ({len(text)}c | tools={len(tool_results)}) "
        f"[total: {token_summary()}]: {text[:80]}{'...' if len(text) > 80 else ''}"
    )

    perplexity = (
        max(1.5, 10.0 - min(len(text) / 500, 1.0) * 7.0)
        if used_fallback
        else _perplexity_from_content(text)
    )
    logger.info(f"[{label}] perplexity={perplexity:.2f}  final_text={len(text)}c")

    # Save agent trace to markdown
    try:
        import datetime as _dt
        logs_dir = OUTPUT_DIR / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        md_path = logs_dir / f"{label}.md"
        lines = [
            f"# Agent Trace: `{label}`\n",
            f"**Role:** {role_key}  \n**Time:** {_dt.datetime.now().strftime('%H:%M:%S')}\n\n",
        ]
        for tr in tool_results:
            lines.append(f"**Tool:** {tr[:400]}\n\n")
        if text.strip():
            lines.append(f"---\n## Summary\n{text.strip()}\n")
        md_path.write_text("".join(lines), encoding="utf-8")
    except Exception:
        pass

    return text, tool_results, perplexity


def _run_fixer(role_key: str, task: str, failed_output: str, F_score: float) -> str:
    """
    Fixer agent: reads a failed/uncertain output and makes surgical corrections.
    Returns a patched output. Used instead of full retry on anomaly.
    Per research: raises success 43->89.5 vs. restart, cuts recovery time 50%.
    """
    role = ROLES[role_key]
    fix_prompt = (
        f"You are a senior {role['title']} reviewing a colleague's uncertain work.\n\n"
        f"ORIGINAL TASK:\n{task[:400]}\n\n"
        f"UNCERTAIN OUTPUT (uncertainty score={F_score:.3f}):\n{failed_output[:1200]}\n\n"
        f"This output scored high on uncertainty. Diagnose exactly what is wrong:\n"
        f"1. Identify the specific parts that are vague, incomplete, or contradictory.\n"
        f"2. Rewrite only those parts with decisive, concrete replacements.\n"
        f"3. Keep everything that is already correct — do not rewrite for the sake of it.\n\n"
        f"Output the complete corrected version. Be decisive and specific.\n"
        f"End with: STANCE: [MINIMAL|ROBUST|SCALABLE|PRAGMATIC]"
    )
    import software_company as _sc

    fixed = _sc.llm_call(
        fix_prompt, label=f"{role_key}_fixer", get_logprobs=False, system=_worker_system(role_key)
    )
    if not fixed.strip():
        logger.warning(f"[{role_key}] fixer returned empty -- keeping original output")
        return failed_output
    logger.info(f"[{role_key}] fixer applied -- output patched ({len(fixed)}c)")
    return fixed
