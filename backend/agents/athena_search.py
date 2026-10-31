"""
Athena Search Agent (backend/agents/athena_search.py).
Runs parallel searches across Tavily (and arXiv for scientific/academic topics)
bounded by asyncio.Semaphore(MAX_PARALLEL_RESEARCHERS).
"""
import asyncio
from typing import Any, Dict, List, Tuple

from events import emit_event
from tools.arxiv_tool import search_arxiv
from tools.tavily_tool import search_tavily
from tools.youtube_tool import search_youtube_domestic

MAX_PARALLEL_RESEARCHERS = 5
RESULTS_PER_SEARCH = 5
DOMESTIC_RESULTS_PER_PLATFORM = 3

DOMESTIC_PLATFORMS = [
    {
        "name": "Reddit",
        "domain": "reddit.com",
        "empty_warning": "Reddit returned no results for this query",
    },
    {
        "name": "X",
        "domain": "x.com",
        "empty_warning": "X returned no results (site blocks crawlers)",
    },
    {
        "name": "Quora",
        "domain": "quora.com",
        "empty_warning": "Quora returned no results for this query",
    },
    {
        "name": "YouTube",
        "domain": "youtube.com",
        "empty_warning": "YouTube returned no results for this query",
    },
    {
        "name": "Amazon",
        "domain": "amazon.in",
        "empty_warning": "Amazon returned no results (site limits crawlers or no match)",
    },
    {
        "name": "Flipkart",
        "domain": "flipkart.com",
        "empty_warning": "Flipkart returned no results for this query",
    },
]

ACADEMIC_KEYWORDS = {
    "science",
    "scientific",
    "study",
    "studies",
    "research",
    "paper",
    "algorithm",
    "quantum",
    "neural",
    "machine learning",
    "ai",
    "climate",
    "emission",
    "emissions",
    "pollution",
    "particulate",
    "pm2.5",
    "aerosol",
    "crop",
    "stubble",
    "agricultural",
    "agriculture",
    "biomass",
    "soil",
    "agronomy",
    "vaccine",
    "clinical",
    "disease",
    "medical",
    "genome",
    "physics",
    "chemistry",
    "biology",
    "economic",
    "economics",
    "satellite",
    "remote sensing",
}


def is_academic_topic(topic: str, query: str) -> bool:
    """Pure Python check whether a topic/query has scientific or academic relevance for arXiv."""
    combined = f"{topic} {query}".lower()
    return any(kw in combined for kw in ACADEMIC_KEYWORDS)


async def run_searches(
    topic: str,
    queries: List[Dict[str, str]],
    run_id: str,
    current_round: int = 1,
    search_type: str = "industrial",
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Execute a batch of search queries in parallel using asyncio.gather and
    a semaphore of MAX_PARALLEL_RESEARCHERS.
    - Industrial: searches Tavily (and arXiv for academic topics).
    - Domestic: for each question, searches all 6 consumer platforms in parallel
      (Reddit, X, Quora, YouTube, Amazon, Flipkart) with max_results=3 per platform.
    Returns (new_sources_list, searches_executed_count).
    """
    semaphore = asyncio.Semaphore(MAX_PARALLEL_RESEARCHERS)
    is_domestic = str(search_type or "industrial").lower() == "domestic"
    arxiv_queried_sections = set()
    search_tasks = []

    async def _run_domestic_platform(
        section_id: str,
        query: str,
        platform_info: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        p_name = platform_info["name"]
        p_domain = platform_info["domain"]
        p_warn = platform_info["empty_warning"]

        async with semaphore:
            emit_event(
                run_id,
                "search_start",
                "Athena",
                f"[{p_name}] Searching {p_domain} ({section_id}): {query}",
                {
                    "section_id": section_id,
                    "query": query,
                    "tool": p_name.lower(),
                    "platform": p_name,
                    "round": current_round,
                },
            )
            if p_name == "YouTube":
                results = await search_youtube_domestic(
                    query=query,
                    section_id=section_id,
                    max_results=DOMESTIC_RESULTS_PER_PLATFORM,
                    run_id=run_id,
                )
            else:
                results = await search_tavily(
                    query=query,
                    section_id=section_id,
                    max_results=DOMESTIC_RESULTS_PER_PLATFORM,
                    run_id=run_id,
                    include_domains=[p_domain],
                    platform=p_name,
                    empty_warning_message=f"{p_warn} ('{query}')",
                )

            for r in results:
                r["platform"] = p_name
                r["round_found"] = current_round
                r["query_used"] = query

            emit_event(
                run_id,
                "search_result",
                "Athena",
                f"[{p_name}] Found {len(results)} result(s) for: {query}",
                {
                    "section_id": section_id,
                    "query": query,
                    "tool": p_name.lower(),
                    "platform": p_name,
                    "count": len(results),
                    "round": current_round,
                },
            )
            return results

    async def _run_single_tavily(section_id: str, query: str) -> List[Dict[str, Any]]:
        async with semaphore:
            emit_event(
                run_id,
                "search_start",
                "Athena",
                f"[Tavily] Searching ({section_id}): {query}",
                {"section_id": section_id, "query": query, "tool": "tavily", "round": current_round},
            )
            results = await search_tavily(
                query=query,
                section_id=section_id,
                max_results=RESULTS_PER_SEARCH,
                run_id=run_id,
            )
            for r in results:
                r["round_found"] = current_round
                r["query_used"] = query
            emit_event(
                run_id,
                "search_result",
                "Athena",
                f"[Tavily] Found {len(results)} results for: {query}",
                {
                    "section_id": section_id,
                    "query": query,
                    "tool": "tavily",
                    "count": len(results),
                    "round": current_round,
                },
            )
            return results

    async def _run_single_arxiv(section_id: str, query: str) -> List[Dict[str, Any]]:
        async with semaphore:
            emit_event(
                run_id,
                "search_start",
                "Athena",
                f"[arXiv] Searching academic papers ({section_id}): {query}",
                {"section_id": section_id, "query": query, "tool": "arxiv", "round": current_round},
            )
            results = await search_arxiv(
                query=query,
                section_id=section_id,
                max_results=3,
                run_id=run_id,
            )
            for r in results:
                r["round_found"] = current_round
                r["query_used"] = query
            emit_event(
                run_id,
                "search_result",
                "Athena",
                f"[arXiv] Found {len(results)} papers for: {query}",
                {
                    "section_id": section_id,
                    "query": query,
                    "tool": "arxiv",
                    "count": len(results),
                    "round": current_round,
                },
            )
            return results

    for item in queries:
        sec_id = item["section_id"]
        q_text = item["query"]
        if is_domestic:
            for p_info in DOMESTIC_PLATFORMS:
                search_tasks.append(_run_domestic_platform(sec_id, q_text, p_info))
        else:
            search_tasks.append(_run_single_tavily(sec_id, q_text))

            # If the topic/query looks scientific/academic, also query arXiv (once per section in round 1)
            if current_round == 1 and sec_id not in arxiv_queried_sections and is_academic_topic(topic, q_text):
                arxiv_queried_sections.add(sec_id)
                search_tasks.append(_run_single_arxiv(sec_id, q_text))

    if not search_tasks:
        return [], 0

    batches = await asyncio.gather(*search_tasks, return_exceptions=True)
    all_new_sources: List[Dict[str, Any]] = []

    for batch in batches:
        if isinstance(batch, Exception):
            emit_event(
                run_id,
                "warning",
                "Athena",
                f"Unexpected search task error: {batch}",
                {"error": str(batch)},
            )
            continue
        if isinstance(batch, list):
            all_new_sources.extend(batch)

    return all_new_sources, len(search_tasks)
