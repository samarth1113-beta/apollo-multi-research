"""
OpenRouter LLM helper with retries, timeout, call counter, and safe JSON parsing.
"""
import asyncio
import json
import os
import re
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI

from events import emit_event, mask_secrets

load_dotenv()

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Per-run LLM call counters
_llm_call_counts: Dict[str, int] = {}


def reset_llm_calls(run_id: str) -> None:
    """Reset the LLM call counter for a run."""
    _llm_call_counts[run_id] = 0


def get_llm_calls(run_id: str) -> int:
    """Get total LLM calls made during a run."""
    return _llm_call_counts.get(run_id, 0)


def _increment_llm_calls(run_id: Optional[str]) -> None:
    if run_id:
        _llm_call_counts[run_id] = _llm_call_counts.get(run_id, 0) + 1


def get_fast_model() -> str:
    """Return FAST_MODEL from .env (with safe default)."""
    return os.getenv("FAST_MODEL", "openai/gpt-4o-mini").strip()


def get_smart_model() -> str:
    """Return SMART_MODEL from .env (with safe default)."""
    return os.getenv("SMART_MODEL", "openai/gpt-4o").strip()


def _get_client() -> AsyncOpenAI:
    """Create an AsyncOpenAI client pointed at OpenRouter."""
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    return AsyncOpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=api_key or "missing_key",
        default_headers={
            "HTTP-Referer": "http://localhost:5173",
            "X-Title": "Apollo Deep Research",
        },
    )


def strip_code_fences(text: str) -> str:
    """
    Strip markdown code fences (```json ... ``` or ``` ... ```) from LLM output.
    """
    if not text:
        return ""
    cleaned = text.strip()
    # Match ```json ... ``` or ``` ... ```
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    return cleaned


def parse_json_safely(text: str) -> Any:
    """
    Strip code fences and parse JSON. If extra text wraps the JSON object/array,
    extract the outermost {...} or [...] substring and try parsing again.
    Raises ValueError if valid JSON cannot be extracted.
    """
    cleaned = strip_code_fences(text)
    if not cleaned:
        raise ValueError("Empty LLM response")

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try finding outermost JSON object or array
        obj_start = cleaned.find("{")
        obj_end = cleaned.rfind("}")
        arr_start = cleaned.find("[")
        arr_end = cleaned.rfind("]")

        candidates = []
        if obj_start != -1 and obj_end > obj_start:
            candidates.append(cleaned[obj_start : obj_end + 1])
        if arr_start != -1 and arr_end > arr_start:
            candidates.append(cleaned[arr_start : arr_end + 1])

        # Try whichever starts earlier first
        candidates.sort(key=lambda c: cleaned.find(c))
        for candidate in candidates:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

        raise ValueError(f"Could not parse JSON from response: {cleaned[:200]}")


def _is_402_error(exc: Exception) -> bool:
    """Return True if the exception represents an OpenRouter HTTP 402 (credits/max_tokens) error."""
    status = getattr(exc, "status_code", None)
    if status == 402:
        return True
    return "402" in str(exc)


async def call_llm(
    model: str,
    messages: List[Dict[str, str]],
    json_mode: bool = False,
    run_id: Optional[str] = None,
    default_json: Any = None,
    timeout: float = 45.0,
    max_retries: int = 2,
    agent_name: str = "System",
    max_tokens: int = 1200,
) -> Any:
    """
    Call OpenRouter LLM with up to `max_retries` retries and timeout.
    - Always sends `max_tokens` (default 1200).
    - If a call fails with error code 402, retries once with `max_tokens` halved before giving up.
    - If `json_mode=False`: returns string content (or "" on failure).
    - If `json_mode=True`: strips code fences, tries json.loads; on parse failure
      retries once with "Return valid JSON only", then falls back to `default_json`.
    - Counts every LLM call for `run_id`.
    - Never raises uncaught exceptions; emits a warning event on failure.
    """
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key or api_key == "your_openrouter_api_key_here":
        if run_id:
            emit_event(
                run_id,
                "warning",
                agent_name,
                "OPENROUTER_API_KEY is not set in backend/.env. Using fallback response.",
                {"model": model},
            )
        return default_json if json_mode else ""

    client = _get_client()
    raw_text = ""
    last_error: Optional[Exception] = None
    current_max_tokens = int(max_tokens) if max_tokens and max_tokens > 0 else 1200

    # Attempt up to max_retries + 1 total tries for network/API errors
    for attempt in range(max_retries + 1):
        try:
            _increment_llm_calls(run_id)
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.2 if json_mode else 0.3,
                    max_tokens=current_max_tokens,
                ),
                timeout=timeout,
            )
            raw_text = (response.choices[0].message.content or "").strip()
            last_error = None
            break
        except Exception as exc:
            # If error code 402, retry once with max_tokens halved before giving up
            if _is_402_error(exc):
                halved_tokens = max(1, current_max_tokens // 2)
                try:
                    _increment_llm_calls(run_id)
                    response = await asyncio.wait_for(
                        client.chat.completions.create(
                            model=model,
                            messages=messages,
                            temperature=0.2 if json_mode else 0.3,
                            max_tokens=halved_tokens,
                        ),
                        timeout=timeout,
                    )
                    current_max_tokens = halved_tokens
                    raw_text = (response.choices[0].message.content or "").strip()
                    last_error = None
                    break
                except Exception as exc_402:
                    last_error = exc_402
                    if run_id:
                        safe_err = mask_secrets(str(exc_402))
                        emit_event(
                            run_id,
                            "warning",
                            agent_name,
                            f"LLM call to {model} failed with 402 even after halving max_tokens to {halved_tokens}: {safe_err}",
                            {"model": model, "max_tokens": halved_tokens, "error": safe_err},
                        )
                    break

            last_error = exc
            if attempt < max_retries:
                await asyncio.sleep(1.5 * (attempt + 1))
            else:
                if run_id:
                    safe_err = mask_secrets(str(exc))
                    emit_event(
                        run_id,
                        "warning",
                        agent_name,
                        f"LLM call to {model} failed after {max_retries + 1} attempts: {safe_err}",
                        {"model": model, "error": safe_err},
                    )

    if last_error is not None:
        return default_json if json_mode else ""

    if not json_mode:
        return raw_text

    # JSON mode parsing + 1 retry with "Return valid JSON only"
    try:
        return parse_json_safely(raw_text)
    except Exception as parse_err:
        retry_messages = list(messages) + [
            {"role": "assistant", "content": raw_text or "(empty)"},
            {
                "role": "user",
                "content": "Return valid JSON only. Do not include markdown fences or any explanation.",
            },
        ]
        try:
            _increment_llm_calls(run_id)
            retry_resp = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    messages=retry_messages,
                    temperature=0.1,
                    max_tokens=current_max_tokens,
                ),
                timeout=timeout,
            )
            retry_text = (retry_resp.choices[0].message.content or "").strip()
            return parse_json_safely(retry_text)
        except Exception as retry_err:
            if _is_402_error(retry_err):
                halved_tokens = max(1, current_max_tokens // 2)
                try:
                    _increment_llm_calls(run_id)
                    retry_resp = await asyncio.wait_for(
                        client.chat.completions.create(
                            model=model,
                            messages=retry_messages,
                            temperature=0.1,
                            max_tokens=halved_tokens,
                        ),
                        timeout=timeout,
                    )
                    retry_text = (retry_resp.choices[0].message.content or "").strip()
                    return parse_json_safely(retry_text)
                except Exception as retry_402_err:
                    retry_err = retry_402_err
            if run_id:
                emit_event(
                    run_id,
                    "warning",
                    agent_name,
                    f"JSON parse failed after retry on {model}; using safe fallback ({retry_err}).",
                    {"model": model, "initial_error": str(parse_err)},
                )
            return default_json
