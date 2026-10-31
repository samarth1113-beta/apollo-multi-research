"""
Event emitter and per-run event queue for streaming SSE updates and CLI callbacks.
Never includes API keys in events, warnings, errors, or logs.
"""
import asyncio
from datetime import datetime, timezone
import os
import re
from typing import Any, Callable, Dict, List, Optional

API_KEY_ENV_NAMES = (
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "TAVILY_API_KEY",
    "PERPLEXITY_API_KEY",
    "REDDIT_CLIENT_ID",
    "REDDIT_SECRET",
    "YOUTUBE_API_KEY",
    "GITHUB_TOKEN",
)

# Regex patterns for common API keys/tokens (OpenRouter, OpenAI, Anthropic, Tavily, Perplexity, GitHub, Google/YouTube, Bearer tokens)
_SECRET_PATTERNS = [
    re.compile(r"sk-or-v1-[A-Za-z0-9_-]{8,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"tvly-[A-Za-z0-9_-]{8,}"),
    re.compile(r"pplx-[A-Za-z0-9_-]{8,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{8,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{8,}"),
    re.compile(r"AIza[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._\-]{10,}"),
]


def mask_secrets(text: str) -> str:
    """Mask any configured API keys or key-like tokens in text as '***'."""
    if not text or not isinstance(text, str):
        return text

    masked = text
    # Mask any currently set env key values
    for env_name in API_KEY_ENV_NAMES:
        val = (os.getenv(env_name) or "").strip()
        if len(val) >= 4 and val not in ("missing_key", "your_openrouter_api_key_here", "your_tavily_api_key_here"):
            masked = masked.replace(val, "***")

    # Mask anything matching known key patterns
    for pat in _SECRET_PATTERNS:
        if pat.groups:
            masked = pat.sub(r"\1***", masked)
        else:
            masked = pat.sub("***", masked)

    return masked


def _sanitize_data(obj: Any) -> Any:
    """Recursively mask secrets in event data dictionaries and lists."""
    if isinstance(obj, str):
        return mask_secrets(obj)
    if isinstance(obj, dict):
        return {k: _sanitize_data(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_data(item) for item in obj]
    return obj


# Per-run state registries
_run_queues: Dict[str, asyncio.Queue] = {}
_run_events: Dict[str, List[Dict[str, Any]]] = {}
_run_results: Dict[str, Dict[str, Any]] = {}
_run_callbacks: Dict[str, List[Callable[[Dict[str, Any]], None]]] = {}


def init_run_events(
    run_id: str,
    on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> asyncio.Queue:
    """Initialize the event queue and storage for a new research run."""
    queue: asyncio.Queue = asyncio.Queue()
    _run_queues[run_id] = queue
    _run_events[run_id] = []
    _run_callbacks[run_id] = [on_event] if on_event else []
    return queue


def get_run_queue(run_id: str) -> Optional[asyncio.Queue]:
    """Return the asyncio.Queue for a given run_id."""
    return _run_queues.get(run_id)


def get_run_events(run_id: str) -> List[Dict[str, Any]]:
    """Return all events emitted so far for a given run_id."""
    return _run_events.get(run_id, [])


def set_run_result(run_id: str, result: Dict[str, Any]) -> None:
    """Save the final result payload for a completed run."""
    _run_results[run_id] = result


def get_run_result(run_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve the final result payload for a completed run, or None if not done."""
    return _run_results.get(run_id)


def emit_event(
    run_id: str,
    event_type: str,
    agent: str,
    message: str,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Emit a structured event for the given run_id.
    Event schema from APOLLO_SPEC.md:
    {"type": "...", "agent": "Apollo|Athena|Hermes|Writer|TruthMeter|System", "message": "...", "data": {...}, "ts": "..."}
    """
    event = {
        "type": event_type,
        "agent": agent,
        "message": mask_secrets(message),
        "data": _sanitize_data(data or {}),
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    if run_id in _run_events:
        _run_events[run_id].append(event)
    else:
        _run_events[run_id] = [event]

    queue = _run_queues.get(run_id)
    if queue is not None:
        queue.put_nowait(event)

    for cb in _run_callbacks.get(run_id, []):
        try:
            cb(event)
        except Exception:
            pass

    return event
