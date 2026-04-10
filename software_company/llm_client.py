"""Gemini client singleton, token accounting, and ``llm_call``."""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional, Tuple, Union

from google import genai

from .config import GEMINI_MODEL
from .prompts_loaded import _SYSTEM_WORKER

logger = logging.getLogger("company")

__all__ = [
    "get_client",
    "llm_call",
    "token_summary",
    "_track_tokens",
    "_tokens_in",
    "_tokens_out",
    "_call_count",
    "_perplexity_from_content",
    "_CONFIDENCE_MAP",
]

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


def llm_call(
    prompt: str,
    label: str = "",
    get_logprobs: bool = False,
    system: Optional[str] = None,
) -> Union[str, Tuple[str, float]]:
    import concurrent.futures as _cf

    if system is None:
        system = _SYSTEM_WORKER

    _LLM_TIMEOUT = 60
    _LLM_RETRIES = 3

    def _do_call():
        from google.genai import types as _gtypes
        cfg = _gtypes.GenerateContentConfig(
            max_output_tokens=8096,
            **({"system_instruction": system} if system else {}),
        )
        return get_client().models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=cfg,
        )

    last_err: str = ""
    for _attempt in range(1, _LLM_RETRIES + 1):
        try:
            _llm_ex = _cf.ThreadPoolExecutor(max_workers=1)
            _llm_fut = _llm_ex.submit(_do_call)
            try:
                r = _llm_fut.result(timeout=_LLM_TIMEOUT)
                _llm_ex.shutdown(wait=False)
            except _cf.TimeoutError:
                _llm_ex.shutdown(wait=False)
                last_err = f"timed out after {_LLM_TIMEOUT}s"
                logger.warning(f"LLM_TIMEOUT [{label}] attempt {_attempt}/{_LLM_RETRIES} — retrying...")
                continue

            text = (getattr(r, "text", "") or "").strip()

            _track_tokens(r)
            u = getattr(r, "usage_metadata", None)
            t_in = getattr(u, "prompt_token_count", 0) or 0
            t_out = getattr(u, "candidates_token_count", 0) or 0

            tag = f"[{label}] " if label else ""
            logger.info(
                f"{tag}({len(text)}c | in={t_in} out={t_out}) "
                f"[total: {token_summary()}]: "
                f"{text[:80]}{'...' if len(text) > 80 else ''}"
            )
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
    return (fallback, 10.0) if get_logprobs else fallback
