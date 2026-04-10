"""Gemini AFC loop (_run_with_tools) and output fixer (_run_fixer)."""

from __future__ import annotations

import concurrent.futures as _cf
import contextvars as _cv
import inspect
import logging
import threading
from typing import List, Tuple

from .config import OUTPUT_DIR
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
from .tool_registry import _TOOL_CALLABLES, _dev_tools_for_attempt

logger = logging.getLogger("company")

def _run_with_tools(
    prompt: str,
    role_key: str,
    label: str,
    retry_count: int = 0,
) -> Tuple[str, List[str], float]:
    """
    Run a prompt through Gemini's native automatic function-calling chat session.
    System instruction is pinned once in chat config and never re-injected.
    Conversation history is maintained as structured Content objects by the SDK —
    no string concatenation, no JSON parsing, no regex.
    Returns (final_text, tool_result_strings, perplexity_estimate).
    """
    from google.genai import types as _gtypes
    import concurrent.futures as _cf

    _AGENT_TIMEOUT = 240
    _MAX_AGENT_RETRIES = 3
    _MAX_TOOL_CALLS = 24 if role_key.startswith("dev_") else 100

    # Thread-safe invocation log shared between the wrapper closures and _run_loop.
    _tool_invocations: List[str] = []
    _tool_inv_lock = threading.Lock()

    def _run_loop() -> Tuple[str, List[str]]:
        names    = _dev_tools_for_attempt(role_key, retry_count)
        tool_fns = [_TOOL_CALLABLES[n] for n in names if n in _TOOL_CALLABLES]
        system   = _worker_system(role_key) + "\n\n" + _SYSTEM_AGENT

        # Wrap each tool callable so we can count and log actual invocations.
        # AFC resolves tool calls internally — the final response has no
        # function_call parts, so response-inspection always reports 0.
        _consec_list_files = [0]   # mutable so inner closure can mutate it

        def _make_counted(fn):
            import typing as _typing_mod

            def _wrapper(*args, **kwargs):
                arg_repr = str(kwargs or args)[:200]
                # Registered tools have names like "list_files", "write_code_file" (no _tool_ prefix)
                is_list = fn.__name__ == "list_files"
                with _tool_inv_lock:
                    if is_list:
                        _consec_list_files[0] += 1
                        run_n = _consec_list_files[0]
                    else:
                        _consec_list_files[0] = 0
                        run_n = 0
                if is_list:
                    logger.warning(
                        f"  [{label}] list_files called (consecutive #{run_n})"
                    )
                try:
                    result = fn(*args, **kwargs)
                    _tn = fn.__name__
                    # Desktop tools can return ERROR: strings without raising — the manager fix loop
                    # must not count failed/no-op calls as verified GUI interaction.
                    if _tn in DESKTOP_TOOLS_OK_FAIL:
                        _dok = (
                            isinstance(result, str)
                            and not result.lstrip().upper().startswith("ERROR")
                        )
                        entry = f"[TOOL: {_tn}|{'ok' if _dok else 'fail'}] {arg_repr}"
                    else:
                        entry = f"[TOOL: {_tn}] {arg_repr}"
                    with _tool_inv_lock:
                        _tool_invocations.append(entry)
                    if is_list:
                        logger.info(
                            f"  [{label}] list_files result →\n{result}"
                        )
                    else:
                        logger.info(f"  [{label}] tool {fn.__name__}: {arg_repr[:80]}")
                    return result
                except Exception as _tool_err:
                    entry = f"[TOOL ERROR: {fn.__name__}] {arg_repr} → {_tool_err}"
                    with _tool_inv_lock:
                        _tool_invocations.append(entry)
                    logger.error(f"  [{label}] tool {fn.__name__} RAISED: {_tool_err}")
                    raise

            # Copy identity attributes manually.
            # IMPORTANT: do NOT use functools.wraps() or set __wrapped__ = fn.
            # `from __future__ import annotations` (PEP 563) makes all
            # annotations in this module strings.  In Python 3.14 inspect.signature()
            # no longer evaluates those strings, so they stay as e.g. `'str'`.
            # The Gemini AFC code calls isinstance(value, param.annotation) which
            # then fails with "isinstance() arg 2 must be a type" because 'str'
            # is a string, not a type.  Setting __wrapped__ would cause
            # inspect.signature() to follow it and hit the same problem.
            # Instead we build an explicit __signature__ with fully-evaluated
            # type objects sourced from typing.get_type_hints().
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

        counted_fns = [_make_counted(fn) for fn in tool_fns]

        cfg_kwargs: dict = dict(
            system_instruction=system,
            max_output_tokens=8096,
        )
        if counted_fns:
            cfg_kwargs["tools"] = counted_fns
            cfg_kwargs["automatic_function_calling"] = _gtypes.AutomaticFunctionCallingConfig(
                maximum_remote_calls=_MAX_TOOL_CALLS + 1,
            )

        chat = get_client().chats.create(
            model=GEMINI_MODEL,
            config=_gtypes.GenerateContentConfig(**cfg_kwargs),
        )

        r = chat.send_message(prompt)
        _track_tokens(r)

        final_text = (getattr(r, "text", "") or "").strip()

        with _tool_inv_lock:
            collected = list(_tool_invocations)

        logger.info(f"[{label}] agent finished — {len(collected)} tool invocations")
        return final_text, collected

    last_err = ""
    text = ""
    tool_results: List[str] = []
    logger.info(f"[{label}] ── Gemini native function-calling loop (role={role_key}, prompt={len(prompt)}c)")

    for _attempt in range(1, _MAX_AGENT_RETRIES + 1):
        # Fresh context copy per attempt — a Context can only be entered once at a time.
        # After a timeout the abandoned thread still holds the old context, so reusing
        # the same copy would raise "context is already entered".
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
                # Exponential backoff for rate-limit (429) errors
                if "429" in last_err or "RESOURCE_EXHAUSTED" in last_err:
                    _backoff = 5 * (2 ** (_attempt - 1))   # 5s, 10s, 20s …
                    logger.info(f"[{label}] rate-limited — waiting {_backoff}s before retry")
                    import time as _time
                    _time.sleep(_backoff)
        finally:
            _ex.shutdown(wait=False)
    else:
        logger.error(f"[{label}] all {_MAX_AGENT_RETRIES} attempts failed — {last_err}")
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

    # ── Save agent trace to markdown ──────────────────────────────────────
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
        pass  # never let logging break the agent

    return text, tool_results, perplexity
def _run_fixer(role_key: str, task: str, failed_output: str, F_score: float) -> str:
    """
    Fixer agent: reads a failed/uncertain output and makes surgical corrections.
    Returns a patched output. Used instead of full retry on anomaly.
    Per research: raises success 43→89.5 vs. restart, cuts recovery time 50%.
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
        logger.warning(f"[{role_key}] fixer returned empty — keeping original output")
        return failed_output
    logger.info(f"[{role_key}] fixer applied — output patched ({len(fixed)}c)")
    return fixed
