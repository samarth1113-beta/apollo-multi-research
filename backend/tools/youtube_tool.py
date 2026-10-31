"""
YouTube Data API v3 + youtube-transcript-api search tool for Domestic runs (backend/tools/youtube_tool.py).
- Reads YOUTUBE_API_KEY with os.getenv at call time.
- If YOUTUBE_API_KEY is set: searches YouTube Data API v3 (max 3 videos per question),
  then uses youtube-transcript-api to get the transcript (English or Hindi, first 4000 chars).
  If transcript fails, uses video title + description.
- If YOUTUBE_API_KEY is not set (or API call fails): falls back to Tavily youtube.com search.
"""
import asyncio
import os
from typing import Any, Dict, List, Optional

import httpx
from youtube_transcript_api import YouTubeTranscriptApi

from events import emit_event, mask_secrets
from tools.tavily_tool import search_tavily

MAX_CONTENT_CHARS = 4000
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"


def _fetch_transcript_sync(video_id: str) -> str:
    """
    Fetch English or Hindi transcript for a YouTube video_id using youtube-transcript-api.
    Supports both youtube-transcript-api v1.x (instance .fetch) and v0.x (static .get_transcript).
    Returns empty string if unavailable.
    """
    if not video_id:
        return ""
    try:
        # youtube-transcript-api >= 1.0.0
        if hasattr(YouTubeTranscriptApi, "fetch"):
            ytt = YouTubeTranscriptApi()
            fetched = ytt.fetch(video_id, languages=["en", "en-IN", "hi"])
            parts = []
            for snippet in fetched:
                text = getattr(snippet, "text", None) or (
                    snippet.get("text") if isinstance(snippet, dict) else ""
                )
                if text:
                    parts.append(str(text).strip())
            return " ".join(parts)[:MAX_CONTENT_CHARS]

        # youtube-transcript-api 0.x fallback
        if hasattr(YouTubeTranscriptApi, "get_transcript"):
            segments = YouTubeTranscriptApi.get_transcript(
                video_id, languages=["en", "en-IN", "hi"]
            )
            return " ".join(
                str(s.get("text", "")).strip() for s in segments if s.get("text")
            )[:MAX_CONTENT_CHARS]
    except Exception:
        return ""
    return ""


async def search_youtube_domestic(
    query: str,
    section_id: str,
    max_results: int = 3,
    run_id: Optional[str] = None,
    timeout: float = 25.0,
) -> List[Dict[str, Any]]:
    """
    Search YouTube for a Domestic consumer query.
    - With YOUTUBE_API_KEY: uses YouTube Data API v3 + youtube-transcript-api (or title + description).
    - Without YOUTUBE_API_KEY: uses Tavily site-limited search on youtube.com.
    """
    yt_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not yt_key:
        return await search_tavily(
            query=query,
            section_id=section_id,
            max_results=max_results,
            run_id=run_id,
            timeout=timeout,
            include_domains=["youtube.com"],
            platform="YouTube",
            empty_warning_message=f"YouTube returned no results (web search) for '{query}'",
        )

    try:
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": max_results,
            "key": yt_key,
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(YOUTUBE_SEARCH_URL, params=params)
            if resp.status_code != 200:
                raise RuntimeError(f"YouTube API HTTP {resp.status_code}")
            data = resp.json()

        items = data.get("items", []) if isinstance(data, dict) else []
        if not items:
            if run_id:
                emit_event(
                    run_id,
                    "warning",
                    "Athena",
                    f"YouTube returned no results for '{query}'",
                    {"query": query, "section_id": section_id, "platform": "YouTube"},
                )
            return []

        sources: List[Dict[str, Any]] = []
        for item in items[:max_results]:
            vid_id = (
                item.get("id", {}).get("videoId")
                if isinstance(item.get("id"), dict)
                else None
            )
            snippet = item.get("snippet", {}) if isinstance(item.get("snippet"), dict) else {}
            if not vid_id:
                continue

            title = (snippet.get("title") or f"YouTube Video {vid_id}").strip()
            description = (snippet.get("description") or "").strip()
            published_at = snippet.get("publishedAt")
            channel_title = (snippet.get("channelTitle") or "").strip()
            url = f"https://www.youtube.com/watch?v={vid_id}"

            transcript = await asyncio.to_thread(_fetch_transcript_sync, vid_id)
            if transcript:
                content = f"Video: {title} (Channel: {channel_title})\nTranscript: {transcript}"
            else:
                content = f"Video: {title} (Channel: {channel_title})\nDescription: {description or title}"

            sources.append(
                {
                    "id": None,
                    "url": url,
                    "title": title,
                    "content": content[:MAX_CONTENT_CHARS],
                    "published_date": str(published_at)[:10] if published_at else None,
                    "section_id": section_id,
                    "domain": "youtube.com",
                    "platform": "YouTube",
                    "source_type": "User opinion",
                }
            )

        return sources

    except Exception as exc:
        if run_id:
            safe_err = mask_secrets(str(exc))
            emit_event(
                run_id,
                "warning",
                "Athena",
                f"YouTube API error ({safe_err}); falling back to YouTube web search for '{query}'",
                {"query": query, "section_id": section_id, "platform": "YouTube", "error": safe_err},
            )
        return await search_tavily(
            query=query,
            section_id=section_id,
            max_results=max_results,
            run_id=run_id,
            timeout=timeout,
            include_domains=["youtube.com"],
            platform="YouTube",
            empty_warning_message=f"YouTube returned no results (web search) for '{query}'",
        )
