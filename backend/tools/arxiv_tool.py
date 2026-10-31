"""
arXiv Search Tool wrapper (backend/tools/arxiv_tool.py).
Async-friendly function returning Source dicts (max 3 papers by default).
Never raises; emits a warning and returns [] on error or empty result.
"""
import asyncio
import re
from typing import Any, Dict, List, Optional
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from events import emit_event

MAX_CONTENT_CHARS = 4000

# Serialize arXiv API requests politely so concurrent requests don't trigger HTTP 429/503
_arxiv_lock = asyncio.Lock()

STOPWORDS = {
    "what", "why", "how", "when", "where", "which", "who", "are", "is", "was",
    "were", "the", "a", "an", "in", "on", "of", "to", "for", "and", "or", "but",
    "with", "from", "by", "at", "as", "into", "about", "still", "actually",
    "working", "single", "small", "background", "causes", "main", "drivers",
    "key", "statistics", "recent", "data", "government", "policies",
    "interventions", "solutions", "practice", "evaluation", "implementation",
    "challenges", "limitations", "expert", "recommendations", "future", "outlook",
    "empirical", "official", "report",
}


def _extract_keywords(query: str) -> List[str]:
    """Extract significant search terms from a natural-language query."""
    tokens = re.findall(r"[a-zA-Z0-9]{3,}", query.lower())
    keywords: List[str] = []
    for t in tokens:
        if t not in STOPWORDS and t not in keywords:
            keywords.append(t)
    return keywords[:8]


def _stem_match(keyword: str, text_lower: str) -> bool:
    """Match a keyword or its basic stem (e.g. indian->india, burning->burn, farmers->farm)."""
    if keyword in text_lower:
        return True
    for suffix in ("ing", "ers", "er", "s", "n"):
        if keyword.endswith(suffix) and len(keyword) - len(suffix) >= 3:
            if keyword[: -len(suffix)] in text_lower:
                return True
    return False


def _is_relevant_paper(title: str, summary: str, keywords: List[str]) -> bool:
    """
    Verify that the arXiv paper genuinely addresses the query's concepts.
    Requires at least half of the extracted keywords (min 2) to match.
    """
    if not keywords:
        return False
    text = f"{title} {summary}".lower()
    matched = sum(1 for kw in keywords if _stem_match(kw, text))
    required = 1 if len(keywords) == 1 else max(2, (len(keywords) + 1) // 2)
    return matched >= required


def _fetch_arxiv_atom(arxiv_query: str, max_fetch: int = 10) -> List[Dict[str, Any]]:
    """Query the official arXiv Atom API and parse entries."""
    encoded_q = urllib.parse.quote(arxiv_query)
    api_url = (
        f"http://export.arxiv.org/api/query?search_query={encoded_q}"
        f"&start=0&max_results={max_fetch}&sortBy=relevance&sortOrder=descending"
    )
    req = urllib.request.Request(api_url, headers={"User-Agent": "ApolloResearch/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        xml_bytes = resp.read()
    root = ET.fromstring(xml_bytes)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries: List[Dict[str, Any]] = []
    for entry in root.findall("atom:entry", ns):
        id_el = entry.find("atom:id", ns)
        title_el = entry.find("atom:title", ns)
        summary_el = entry.find("atom:summary", ns)
        pub_el = entry.find("atom:published", ns)
        url = (id_el.text if id_el is not None else "").strip()
        summary = (summary_el.text if summary_el is not None else "").replace("\n", " ").strip()
        if not url or not summary:
            continue
        title = (title_el.text if title_el is not None else url).replace("\n", " ").strip()
        pub_date = (pub_el.text[:10] if (pub_el is not None and pub_el.text) else None)
        entries.append(
            {
                "url": url,
                "title": title,
                "content": summary[:MAX_CONTENT_CHARS],
                "published_date": pub_date,
            }
        )
    return entries


def _sync_arxiv_search(query: str, max_results: int = 3) -> List[Dict[str, Any]]:
    """
    Query arXiv using keyword combinations and filter strictly for relevance.
    """
    keywords = _extract_keywords(query)
    if not keywords:
        return []

    candidate_queries = [" AND ".join(f"all:{kw}" for kw in keywords[:5])]
    if len(keywords) >= 2:
        # Also try OR-joined query with relevance sort, then filter in Python with _is_relevant_paper
        candidate_queries.append(" OR ".join(f"all:{kw}" for kw in keywords[:5]))

    seen_urls = set()
    relevant_results: List[Dict[str, Any]] = []

    for aq in candidate_queries:
        for paper in _fetch_arxiv_atom(aq, max_fetch=max_results * 5):
            if paper["url"] in seen_urls:
                continue
            if _is_relevant_paper(paper["title"], paper["content"], keywords):
                seen_urls.add(paper["url"])
                relevant_results.append(paper)
                if len(relevant_results) >= max_results:
                    return relevant_results

    return relevant_results


async def search_arxiv(
    query: str,
    section_id: str,
    max_results: int = 3,
    run_id: Optional[str] = None,
    timeout: float = 25.0,
) -> List[Dict[str, Any]]:
    """
    Search arXiv asynchronously and return a list of Source dicts:
    {id, url, title, content (max 4000 chars), published_date, section_id, domain}.
    Never raises; emits a 'warning' event and returns [] on error or empty result.
    """
    try:
        async with _arxiv_lock:
            papers = await asyncio.wait_for(
                asyncio.to_thread(_sync_arxiv_search, query, max_results),
                timeout=timeout,
            )
            await asyncio.sleep(0.4)

        sources: List[Dict[str, Any]] = []
        for paper in papers:
            sources.append(
                {
                    "id": None,
                    "url": paper["url"],
                    "title": paper["title"],
                    "content": paper["content"][:MAX_CONTENT_CHARS],
                    "published_date": paper["published_date"],
                    "section_id": section_id,
                    "domain": "arxiv.org",
                    "platform": "arXiv",
                    "source_type": "arxiv",
                }
            )

        if not sources:
            if run_id:
                emit_event(
                    run_id,
                    "warning",
                    "Athena",
                    f"arXiv returned 0 papers for query: '{query}'",
                    {"query": query, "section_id": section_id, "tool": "arxiv"},
                )
            return []

        return sources

    except Exception as exc:
        if run_id:
            emit_event(
                run_id,
                "warning",
                "Athena",
                f"arXiv search error for '{query}': {exc}",
                {"query": query, "section_id": section_id, "tool": "arxiv", "error": str(exc)},
            )
        return []
