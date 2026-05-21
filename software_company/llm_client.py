"""Gemini client singleton, token accounting, and ``llm_call``."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional, Tuple, Union

from google import genai

from .config import GEMINI_MODEL
from .prompts_loaded import _SYSTEM_WORKER

logger = logging.getLogger("company")

__all__ = [
    "get_client",
    "generate_content_with_resilience",
    "llm_call",
    "token_summary",
    "_track_tokens",
    "_tokens_in",
    "_tokens_out",
    "_call_count",
    "_perplexity_from_content",
    "_CONFIDENCE_MAP",
    "_write_episode",
]

# Episode log — one JSON line per LLM call, written to logs/episodes.jsonl
_EPISODE_LOG: Optional[Path] = None
_episode_lock = threading.Lock()
_LLM_TIMEOUT = 60
_LLM_RETRIES = 3
_BACKOFF_BASE = 2.0  # seconds; delay = _BACKOFF_BASE ** attempt


def generate_content_with_resilience(*, label: str = "", **kwargs):
    """Run one Gemini generate_content call with the shared timeout/retry policy.

    All Gemini content-generation paths should use this helper (or llm_call, which
    delegates here) so Lab 8 resilience behavior is uniform across text, tool, and
    vision calls.
    """
    import concurrent.futures as _cf

    last_err = ""
    for attempt in range(1, _LLM_RETRIES + 1):
        executor = _cf.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(get_client().models.generate_content, **kwargs)
        try:
            result = future.result(timeout=_LLM_TIMEOUT)
            executor.shutdown(wait=False)
            return result
        except _cf.TimeoutError:
            future.cancel()
            executor.shutdown(wait=False)
            last_err = f"timed out after {_LLM_TIMEOUT}s"
            logger.warning(
                f"LLM_TIMEOUT [{label}] attempt {attempt}/{_LLM_RETRIES} - retrying..."
            )
        except Exception as exc:
            executor.shutdown(wait=False)
            last_err = str(exc)
            logger.warning(
                f"LLM_ERROR [{label}] attempt {attempt}/{_LLM_RETRIES}: {exc}"
            )
        if attempt < _LLM_RETRIES:
            backoff = _BACKOFF_BASE ** attempt
            logger.info(
                f"LLM_BACKOFF [{label}] sleeping {backoff:.1f}s before attempt {attempt + 1}"
            )
            time.sleep(backoff)
    raise RuntimeError(f"Gemini generate_content failed after {_LLM_RETRIES} attempts: {last_err}")

def _get_episode_log() -> Path:
    global _EPISODE_LOG
    if _EPISODE_LOG is None:
        log_dir = Path(os.environ.get("EPISODE_LOG_DIR", "logs"))
        log_dir.mkdir(parents=True, exist_ok=True)
        _EPISODE_LOG = log_dir / "episodes.jsonl"
    return _EPISODE_LOG


def _write_episode(entry: dict) -> None:
    """Append a single episode record (one line of JSON) to the episode log."""
    input_tokens = int(entry.get("input_tokens", entry.get("prompt_tokens", 0)) or 0)
    output_tokens = int(entry.get("output_tokens", entry.get("completion_tokens", 0)) or 0)
    cache_read_tokens = int(entry.get("cache_read_tokens", 0) or 0)
    cache_write_tokens = int(entry.get("cache_write_tokens", 0) or 0)
    cost_usd = entry.get("cost_usd")
    if cost_usd is None:
        cost_usd = (input_tokens * 0.25 + output_tokens * 1.50) / 1_000_000
    enriched = {
        "ts": entry.get("ts") or entry.get("timestamp") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event_type": entry.get("event_type", "llm_call"),
        "model": entry.get("model", GEMINI_MODEL),
        "provider": entry.get("provider", "google-genai"),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "cost_usd": round(float(cost_usd), 8),
        "latency_ms": int(entry.get("latency_ms", 0) or 0),
        "fallback_triggered": bool(entry.get("fallback_triggered", False)),
        "error": entry.get("error"),
    }
    entry = {**enriched, **entry}
    entry.setdefault("timestamp", entry["ts"])
    entry.setdefault("prompt_tokens", input_tokens)
    entry.setdefault("completion_tokens", output_tokens)
    path = _get_episode_log()
    line = json.dumps(entry, ensure_ascii=False)
    with _episode_lock:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

_client: Optional[genai.Client] = None
_client_lock = threading.Lock()

_tokens_in: int = 0
_tokens_out: int = 0
_call_count: int = 0
_token_lock = threading.Lock()


def _track_tokens(response_or_usage) -> None:
    """Thread-safe accumulation of token counters from Anthropic/Gemini responses."""
    usage = response_or_usage
    if hasattr(response_or_usage, "usage_metadata"):
        usage = getattr(response_or_usage, "usage_metadata")
    in_tokens = (
        getattr(usage, "input_tokens", None)
        or getattr(usage, "prompt_token_count", None)
        or 0
    )
    out_tokens = (
        getattr(usage, "output_tokens", None)
        or getattr(usage, "candidates_token_count", None)
        or 0
    )
    global _tokens_in, _tokens_out, _call_count
    with _token_lock:
        _tokens_in += int(in_tokens or 0)
        _tokens_out += int(out_tokens or 0)
        _call_count += 1


def get_client() -> genai.Client:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = genai.Client(
                    api_key=os.environ["GEMINI_API_KEY"],
                    http_options={"api_version": "v1beta"},
                )
    return _client


def token_summary() -> str:
    with _token_lock:
        calls = _call_count
        t_in = _tokens_in
        t_out = _tokens_out
    total = t_in + t_out
    cost = (t_in * 0.25 + t_out * 1.50) / 1_000_000
    return (
        f"calls={calls}  "
        f"in={t_in:,}  out={t_out:,}  total={total:,}  "
        f"~${cost:.4f}"
    )


_CONFIDENCE_MAP = {
    "a": 1.5,
    "b": 2.5,
    "c": 5.0,
    "d": 8.0,
}


def _perplexity_from_content(text: str) -> float:
    """Content-based perplexity heuristic — fallback when verbal elicitation fails."""
    if not text or len(text) < 10:
        return 8.0
    if text.lower().startswith("[error"):
        return 10.0
    score = 2.0
    hedges = ["might", "could", "perhaps", "unclear", "i think",
              "probably", "not sure", "may need", "i believe", "it seems",
              "possibly", "i'm not", "hard to say"]
    hedge_count = sum(text.lower().count(h) for h in hedges)
    score += min(hedge_count * 0.4, 3.0)
    if "STANCE:" not in text:
        score += 2.0
    words = text.lower().split()
    if words:
        unique_ratio = len(set(words)) / len(words)
        if unique_ratio < 0.4:
            score += 2.0
    if len(text) < 200:
        score += 1.5
    return min(score, 10.0)


def _do_call_config(system: Optional[str]):
    from google.genai import types as _gtypes

    return _gtypes.GenerateContentConfig(
        max_output_tokens=8096,
        **({"system_instruction": system} if system else {}),
    )


def llm_call(
    prompt: str,
    label: str = "",
    get_logprobs: bool = False,
    system: Optional[str] = None,
) -> Union[str, Tuple[str, float]]:
    if system is None:
        system = _SYSTEM_WORKER

    last_err: str = ""
    episode_id = f"{label or 'call'}-{int(time.time() * 1000)}"
    total_start = time.monotonic()

    for _attempt in (1,):
        t_start = time.monotonic()
        try:
            r = generate_content_with_resilience(
                label=label,
                model=GEMINI_MODEL,
                contents=prompt,
                config=_do_call_config(system),
            )

            text = (getattr(r, "text", "") or "").strip()

            _track_tokens(r)
            u = getattr(r, "usage_metadata", None)
            t_in = getattr(u, "prompt_token_count", 0) or 0
            t_out = getattr(u, "candidates_token_count", 0) or 0
            cache_read = getattr(u, "cached_content_token_count", 0) or 0
            cache_write = 0

            latency_ms = int((time.monotonic() - t_start) * 1000)

            tag = f"[{label}] " if label else ""
            logger.info(
                f"{tag}({len(text)}c | in={t_in} out={t_out} cache_read={cache_read} "
                f"latency={latency_ms}ms) [total: {token_summary()}]: "
                f"{text[:80]}{'...' if len(text) > 80 else ''}"
            )

            from .state import _get_agent_id, _get_sprint_num, _get_task_file
            _write_episode({
                "episode_id": episode_id,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "agent_id": _get_agent_id() or "unknown",
                "sprint": _get_sprint_num(),
                "task_file": _get_task_file() or "",
                "label": label,
                "attempt": _attempt,
                "prompt_tokens": t_in,
                "completion_tokens": t_out,
                "input_tokens": t_in,
                "output_tokens": t_out,
                "cache_read_tokens": cache_read,
                "cache_write_tokens": cache_write,
                "latency_ms": latency_ms,
                "fallback_triggered": False,
                "error": None,
            })

            if get_logprobs:
                perplexity = _perplexity_from_content(text)
                try:
                    elicit_prompt = (
                        f"You just produced this response:\n\"\"\"\n{text[:800]}\n\"\"\"\n\n"
                        "Rate your confidence in this response:\n"
                        "A) Very confident — output is complete, correct, and well-reasoned\n"
                        "B) Confident — minor gaps possible but core is solid\n"
                        "C) Uncertain — notable gaps or assumptions made\n"
                        "D) Very uncertain — significant issues or missing information\n\n"
                        "Reply with only the letter A, B, C, or D."
                    )
                    reply = llm_call(elicit_prompt, label="", get_logprobs=False, system="")
                    letter = reply.strip().upper()[:1].lower()
                    if letter in _CONFIDENCE_MAP:
                        perplexity = _CONFIDENCE_MAP[letter]
                except Exception:
                    pass
                return text, perplexity
            return text
        except Exception as e:
            last_err = str(e)
            logger.warning(f"LLM_ERROR [{label}] attempt {_attempt}/{_LLM_RETRIES}: {e}")

    logger.error(f"LLM_ERROR [{label}]: all {_LLM_RETRIES} attempts failed — {last_err}")
    fallback = f"[ERROR: {last_err}]\nSTANCE: PRAGMATIC"
    _write_episode({
        "episode_id": episode_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agent_id": "unknown",
        "sprint": 0,
        "task_file": "",
        "label": label,
        "attempt": _LLM_RETRIES,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "latency_ms": int((time.monotonic() - total_start) * 1000),
        "fallback_triggered": True,
        "error": last_err,
    })
    return (fallback, 10.0) if get_logprobs else fallback
