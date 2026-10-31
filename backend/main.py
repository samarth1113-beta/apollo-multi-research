"""
Apollo Backend - FastAPI Entry Point (backend/main.py).
Routes:
- GET  /api/health
- GET  /api/keys
- POST /api/keys
- POST /api/research
- GET  /api/research/{run_id}/stream (SSE via sse-starlette)
- GET  /api/research/{run_id}/result
"""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import time
from typing import Dict, Optional
import uuid

from dotenv import dotenv_values, load_dotenv, set_key, unset_key
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from events import API_KEY_ENV_NAMES, get_run_queue, get_run_result, init_run_events
from graph import MAX_REVIEW_ROUNDS, execute_research_run

ENV_PATH = Path(__file__).resolve().parent / ".env"
KEY_EXPIRY_DAYS = 30
PLACEHOLDER_VALUES = {
    "your_openrouter_api_key_here",
    "your_tavily_api_key_here",
    "missing_key",
}

load_dotenv(dotenv_path=ENV_PATH, override=True)


def _ensure_local_request(request: Request) -> None:
    """Allow GET/POST /api/keys only from localhost (127.0.0.1, localhost, ::1)."""
    client_host = (request.client.host if request.client else "").strip().lower()
    if client_host not in ("127.0.0.1", "localhost", "::1"):
        raise HTTPException(
            status_code=403,
            detail="Access to /api/keys is restricted to local requests only.",
        )


def _is_timestamp_expired(saved_at_str: Optional[str]) -> bool:
    """Return True if KEYS_SAVED_AT ISO timestamp is older than 30 days."""
    if not saved_at_str or not saved_at_str.strip():
        return False
    try:
        cleaned = saved_at_str.strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        saved_dt = datetime.fromisoformat(cleaned)
        if saved_dt.tzinfo is None:
            saved_dt = saved_dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - saved_dt) > timedelta(days=KEY_EXPIRY_DAYS)
    except Exception:
        return False


def _safe_set_key(env_path: Path, key_to_set: str, value_to_set: str) -> None:
    """
    Call python-dotenv's set_key with brief retries for Windows OneDrive file locks.
    Also cleans up any leftover .tmp_* files if os.replace was interrupted.
    """
    for attempt in range(6):
        try:
            set_key(str(env_path), key_to_set, value_to_set, quote_mode="never")
            return
        except PermissionError:
            time.sleep(0.06 * (attempt + 1))
    # Cleanup any stale dotenv temp files in backend/
    for tmp_file in env_path.parent.glob(".tmp_*"):
        try:
            tmp_file.unlink(missing_ok=True)
        except Exception:
            pass
    # Fallback direct line update preserving all other lines
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    prefix = f"{key_to_set}="
    replaced = False
    new_lines = []
    for line in lines:
        if line.strip().startswith(prefix):
            if not replaced:
                new_lines.append(f"{key_to_set}={value_to_set}")
                replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        new_lines.append(f"{key_to_set}={value_to_set}")
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _safe_unset_key(env_path: Path, key_to_unset: str) -> None:
    """Call python-dotenv's unset_key with brief retries for Windows OneDrive file locks."""
    for attempt in range(6):
        try:
            unset_key(str(env_path), key_to_unset, quote_mode="never")
            return
        except PermissionError:
            time.sleep(0.06 * (attempt + 1))
        except Exception:
            break
    for tmp_file in env_path.parent.glob(".tmp_*"):
        try:
            tmp_file.unlink(missing_ok=True)
        except Exception:
            pass
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
        prefix = f"{key_to_unset}="
        new_lines = [line for line in lines if not line.strip().startswith(prefix)]
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _clear_expired_keys_in_env() -> None:
    """Blank all 9 API key values in backend/.env, remove KEYS_SAVED_AT, and reload env."""
    ENV_PATH.touch(exist_ok=True)
    for key_name in API_KEY_ENV_NAMES:
        _safe_set_key(ENV_PATH, key_name, "")
        os.environ[key_name] = ""
    _safe_unset_key(ENV_PATH, "KEYS_SAVED_AT")
    os.environ.pop("KEYS_SAVED_AT", None)
    load_dotenv(dotenv_path=ENV_PATH, override=True)


def _check_and_handle_key_expiry(print_if_expired: bool = False) -> Dict[str, object]:
    """
    Read backend/.env and check KEYS_SAVED_AT.
    If older than 30 days, clear all 9 keys, remove KEYS_SAVED_AT, reload env,
    and return {"expired": True, "keys": {}}.
    Otherwise return {"expired": False, "saved_at": ..., "keys": {...}}.
    """
    ENV_PATH.touch(exist_ok=True)
    load_dotenv(dotenv_path=ENV_PATH, override=True)
    raw_env = dotenv_values(ENV_PATH)

    saved_at = (raw_env.get("KEYS_SAVED_AT") or os.getenv("KEYS_SAVED_AT") or "").strip()
    if saved_at and _is_timestamp_expired(saved_at):
        _clear_expired_keys_in_env()
        if print_if_expired:
            print("API keys expired and were cleared")
        return {"expired": True, "keys": {}}

    keys_dict: Dict[str, str] = {}
    for key_name in API_KEY_ENV_NAMES:
        val = (raw_env.get(key_name) if key_name in raw_env else os.getenv(key_name, "")) or ""
        val = val.strip()
        if val in PLACEHOLDER_VALUES:
            val = ""
        keys_dict[key_name] = val

    return {
        "expired": False,
        "saved_at": saved_at or None,
        "keys": keys_dict,
    }


# Run the 30-day expiry check once when the backend starts
_check_and_handle_key_expiry(print_if_expired=True)


app = FastAPI(
    title="Apollo API",
    description="Multi-agent deep research web app - Research you can trust",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ResearchRequest(BaseModel):
    topic: str = Field(..., min_length=3, description="Research topic or question")
    max_rounds: int = Field(default=MAX_REVIEW_ROUNDS, ge=1, le=MAX_REVIEW_ROUNDS)
    judge_mode: bool = Field(default=False, description="Enable optional Judge & Reviser loop")
    search_type: str = Field(default="industrial", description="'industrial' or 'domestic'")


class ApiKeysPayload(BaseModel):
    OPENROUTER_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    TAVILY_API_KEY: str = ""
    PERPLEXITY_API_KEY: str = ""
    REDDIT_CLIENT_ID: str = ""
    REDDIT_SECRET: str = ""
    YOUTUBE_API_KEY: str = ""
    GITHUB_TOKEN: str = ""


@app.get("/api/health")
async def health_check():
    """Health check endpoint to verify backend is running."""
    return {"ok": True}


@app.get("/api/platforms")
async def get_platforms():
    """
    Return the 6 domestic consumer platforms with their name, domain, and access type ('api' or 'web search').
    YouTube is 'api' only if YOUTUBE_API_KEY is set.
    Reddit is 'api' only if REDDIT_CLIENT_ID and REDDIT_SECRET are set.
    Everything else is 'web search'. Never returns key values.
    """
    load_dotenv(dotenv_path=ENV_PATH, override=True)
    yt_key = (os.getenv("YOUTUBE_API_KEY") or "").strip()
    reddit_id = (os.getenv("REDDIT_CLIENT_ID") or "").strip()
    reddit_secret = (os.getenv("REDDIT_SECRET") or "").strip()

    has_yt_api = bool(yt_key and yt_key not in PLACEHOLDER_VALUES)
    has_reddit_api = bool(
        reddit_id
        and reddit_secret
        and reddit_id not in PLACEHOLDER_VALUES
        and reddit_secret not in PLACEHOLDER_VALUES
    )

    platforms = [
        {
            "name": "Reddit",
            "domain": "reddit.com",
            "access": "api" if has_reddit_api else "web search",
        },
        {
            "name": "X",
            "domain": "x.com",
            "access": "web search",
        },
        {
            "name": "Quora",
            "domain": "quora.com",
            "access": "web search",
        },
        {
            "name": "YouTube",
            "domain": "youtube.com",
            "access": "api" if has_yt_api else "web search",
        },
        {
            "name": "Amazon",
            "domain": "amazon.in",
            "access": "web search",
        },
        {
            "name": "Flipkart",
            "domain": "flipkart.com",
            "access": "web search",
        },
    ]
    return {"platforms": platforms}


@app.get("/api/keys")
async def get_api_keys(request: Request):
    """
    Read backend/.env and return saved API keys (local requests only).
    Clears keys automatically if KEYS_SAVED_AT is older than 30 days.
    """
    _ensure_local_request(request)
    return _check_and_handle_key_expiry(print_if_expired=False)


@app.post("/api/keys")
async def save_api_keys(payload: ApiKeysPayload, request: Request):
    """
    Save all 9 API key fields and KEYS_SAVED_AT (UTC ISO timestamp) into backend/.env
    using python-dotenv's set_key, preserving FAST_MODEL and SMART_MODEL.
    Reloads environment immediately without restarting the server.
    """
    _ensure_local_request(request)
    ENV_PATH.touch(exist_ok=True)

    payload_dict = payload.model_dump()
    for key_name in API_KEY_ENV_NAMES:
        clean_val = (payload_dict.get(key_name) or "").strip()
        _safe_set_key(ENV_PATH, key_name, clean_val)
        os.environ[key_name] = clean_val

    saved_at_iso = datetime.now(timezone.utc).isoformat()
    _safe_set_key(ENV_PATH, "KEYS_SAVED_AT", saved_at_iso)
    os.environ["KEYS_SAVED_AT"] = saved_at_iso

    load_dotenv(dotenv_path=ENV_PATH, override=True)

    return {
        "ok": True,
        "saved_at": saved_at_iso,
    }


@app.post("/api/research")
async def start_research(req: ResearchRequest):
    """Start a new Apollo research run in the background and return its run_id."""
    topic = req.topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Topic must not be empty.")

    run_id = uuid.uuid4().hex[:12]
    init_run_events(run_id)

    # Launch LangGraph execution as a background asyncio task
    asyncio.create_task(
        execute_research_run(
            run_id=run_id,
            topic=topic,
            max_rounds=req.max_rounds,
            judge_mode=req.judge_mode,
            search_type=req.search_type,
        )
    )

    return {"run_id": run_id}


@app.get("/api/research/{run_id}/stream")
async def stream_research_events(run_id: str):
    """Stream live research events for `run_id` using Server-Sent Events (SSE)."""
    queue = get_run_queue(run_id)
    if queue is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")

    async def event_generator():
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15.0)
                yield {
                    "data": json.dumps(event),
                }
                if event["type"] in ("done", "error"):
                    break
            except asyncio.TimeoutError:
                # Send keepalive ping comment
                yield {"comment": "keepalive"}

    return EventSourceResponse(event_generator())


@app.get("/api/research/{run_id}/result")
async def get_research_result(run_id: str):
    """Return the final result JSON for `run_id` once completed."""
    queue = get_run_queue(run_id)
    if queue is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")

    result = get_run_result(run_id)
    if result is None:
        return {"status": "running", "run_id": run_id}

    return result
