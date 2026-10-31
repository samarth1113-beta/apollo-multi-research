"""
Tavily Search Tool wrapper (backend/tools/tavily_tool.py).
Async-friendly function returning Source dicts. Never raises; emits a warning
and returns [] on error or empty result.
"""
import asyncio
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from tavily import TavilyClient

from events import emit_event, mask_secrets
from tools.source_scoring import extract_domain

load_dotenv()

MAX_CONTENT_CHARS = 4000


def _sync_tavily_search(
    query: str,
    max_results: int = 5,
    include_domains: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Run synchronous Tavily search inside a worker thread."""
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key or api_key == "your_tavily_api_key_here":
        raise RuntimeError("TAVILY_API_KEY is not configured in backend/.env")

    client = TavilyClient(api_key=api_key)
    kwargs: Dict[str, Any] = {
        "query": query,
        "search_depth": "advanced",
        "max_results": max_results,
        "include_raw_content": False,
    }
    if include_domains:
        kwargs["include_domains"] = include_domains
    return client.search(**kwargs)


async def search_tavily(
    query: str,
    section_id: str,
    max_results: int = 5,
    run_id: Optional[str] = None,
    timeout: float = 25.0,
    include_domains: Optional[List[str]] = None,
    platform: str = "Web",
    empty_warning_message: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Search Tavily asynchronously and return a list of Source dicts:
    {id, url, title, content (max 4000 chars), published_date, section_id, domain, platform, source_type}.
    Never raises; emits a 'warning' event and returns [] on error or empty result.
    """
    try:
        raw = await asyncio.wait_for(
            asyncio.to_thread(_sync_tavily_search, query, max_results, include_domains),
            timeout=timeout,
        )
        items = raw.get("results", []) if isinstance(raw, dict) else []
        sources: List[Dict[str, Any]] = []

        for item in items:
            url = (item.get("url") or "").strip()
            content = (item.get("content") or item.get("raw_content") or "").strip()
            if not url or not content:
                continue

            published_date = (
                item.get("published_date")
                or item.get("publishedDate")
                or None
            )
            sources.append(
                {
                    "id": None,  # Assigned globally in score node
                    "url": url,
                    "title": (item.get("title") or url).strip(),
                    "content": content[:MAX_CONTENT_CHARS],
                    "published_date": str(published_date) if published_date else None,
                    "section_id": section_id,
                    "domain": extract_domain(url),
                    "platform": platform or "Web",
                    "source_type": "tavily",
                }
            )

        if not sources:
            if run_id:
                warn_msg = (
                    empty_warning_message
                    or f"Tavily returned 0 usable results for query: '{query}'"
                )
                emit_event(
                    run_id,
                    "warning",
                    "Athena",
                    warn_msg,
                    {
                        "query": query,
                        "section_id": section_id,
                        "tool": "tavily",
                        "platform": platform,
                    },
                )
            return []

        return sources

    except Exception as exc:
        if run_id:
            safe_err = mask_secrets(str(exc))
            emit_event(
                run_id,
                "warning",
                "Athena",
                f"{platform} search error for '{query}': {safe_err}",
                {
                    "query": query,
                    "section_id": section_id,
                    "tool": "tavily",
                    "platform": platform,
                    "error": safe_err,
                },
            )
        return []
