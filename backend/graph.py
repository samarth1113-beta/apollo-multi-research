"""
LangGraph State Machine for the Apollo Research Pipeline (backend/graph.py).
Nodes (in order): plan -> search -> score -> review -> (loop to search OR write) -> truth_check -> done
"""
import time
from typing import Any, Dict, List, Optional, TypedDict
from urllib.parse import urlparse

from langgraph.graph import END, StateGraph

from agents.apollo_planner import plan_research
from agents.athena_search import run_searches
from agents.hermes_review import review_sources
from agents.judge import run_judge_loop
from agents.truth_meter import run_truth_meter
from agents.writer import write_report
from events import emit_event, get_run_events, set_run_result
from tools.llm import get_llm_calls, reset_llm_calls
from tools.source_scoring import score_domestic_source, score_source

# Limits (constants required by APOLLO_SPEC.md)
MAX_SECTIONS = 5
MAX_REVIEW_ROUNDS = 3
MAX_PARALLEL_RESEARCHERS = 5
RESULTS_PER_SEARCH = 5
RUN_TIMEOUT_SECONDS = 360
MIN_SOURCE_SCORE = 35


class ResearchState(TypedDict, total=False):
    run_id: str
    topic: str
    search_type: str
    max_rounds: int
    judge_mode: bool
    start_time: float
    round: int
    plan: List[Dict[str, Any]]
    pending_queries: List[Dict[str, str]]
    pending_sources: List[Dict[str, Any]]
    sources: List[Dict[str, Any]]
    dropped_sources: List[Dict[str, Any]]
    seen_urls: List[str]
    searches_count: int
    complete: bool
    gaps: List[Dict[str, str]]
    conflicts: List[Dict[str, Any]]
    continue_loop: bool
    stopped_at_time_limit: bool
    report_markdown: str
    judge_history: List[Dict[str, Any]]
    sentences_with_verdicts: List[Dict[str, Any]]
    trust_score: Optional[int]
    final_result: Dict[str, Any]


def _normalize_url(url: str) -> str:
    """Normalize URL for deduplication."""
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
        host = (parsed.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        path = (parsed.path or "").rstrip("/")
        query = f"?{parsed.query}" if parsed.query else ""
        return f"{host}{path}{query}"
    except Exception:
        return url.strip().lower().rstrip("/")


async def plan_node(state: ResearchState) -> Dict[str, Any]:
    """Node 1: Apollo creates the research plan (3 to 5 sections)."""
    run_id = state["run_id"]
    topic = state["topic"]
    search_type = state.get("search_type", "industrial")
    max_rounds = min(int(state.get("max_rounds", MAX_REVIEW_ROUNDS)), MAX_REVIEW_ROUNDS)

    sections = await plan_research(topic=topic, run_id=run_id, search_type=search_type)
    sections = sections[:MAX_SECTIONS]

    # Build initial Round 1 search queries from all sections
    initial_queries: List[Dict[str, str]] = []
    for sec in sections:
        for q in sec.get("questions", []):
            initial_queries.append({"section_id": sec["id"], "query": q})

    emit_event(
        run_id,
        "round",
        "Apollo",
        f"Starting Round 1 of {max_rounds} with {len(initial_queries)} planned search queries.",
        {"round": 1, "max_rounds": max_rounds, "queries_count": len(initial_queries)},
    )

    return {
        "max_rounds": max_rounds,
        "round": 1,
        "plan": sections,
        "pending_queries": initial_queries,
    }


async def search_node(state: ResearchState) -> Dict[str, Any]:
    """Node 2: Athena runs parallel searches for pending_queries."""
    run_id = state["run_id"]
    topic = state["topic"]
    search_type = state.get("search_type", "industrial")
    current_round = state.get("round", 1)
    pending_queries = state.get("pending_queries", [])

    new_sources, executed_count = await run_searches(
        topic=topic,
        queries=pending_queries,
        run_id=run_id,
        current_round=current_round,
        search_type=search_type,
    )

    return {
        "pending_sources": new_sources,
        "pending_queries": [],
        "searches_count": state.get("searches_count", 0) + executed_count,
    }


async def score_node(state: ResearchState) -> Dict[str, Any]:
    """
    Node 3 (Pure Python code only): Score every new source, deduplicate URLs,
    drop sources below MIN_SOURCE_SCORE (35), and emit 'source_scored' per source.
    """
    run_id = state["run_id"]
    search_type = state.get("search_type", "industrial")
    is_domestic = str(search_type or "industrial").lower() == "domestic"
    pending_sources = state.get("pending_sources", [])
    kept_sources = list(state.get("sources", []))
    dropped_sources = list(state.get("dropped_sources", []))
    seen_urls = set(state.get("seen_urls", []))

    next_id = len(kept_sources) + 1

    for src in pending_sources:
        norm_url = _normalize_url(src.get("url", ""))
        if not norm_url or norm_url in seen_urls:
            continue
        seen_urls.add(norm_url)

        if is_domestic:
            scoring = score_domestic_source(src)
            source_type_val = scoring.get("source_type") or src.get("source_type") or "User opinion"
        else:
            scoring = score_source(src)
            source_type_val = src.get("source_type") or "tavily"

        score = scoring["score"]
        badge = scoring["badge"]
        reasons = scoring["reasons"]
        platform_val = src.get("platform") or ("arXiv" if source_type_val == "arxiv" else "Web")

        enriched = {
            **src,
            "platform": platform_val,
            "source_type": source_type_val,
            "score": score,
            "badge": badge,
            "reasons": reasons,
        }

        kept = score >= MIN_SOURCE_SCORE
        if kept:
            enriched["id"] = next_id
            next_id += 1
            kept_sources.append(enriched)
        else:
            enriched["id"] = None
            dropped_sources.append(enriched)

        emit_event(
            run_id,
            "source_scored",
            "System",
            (
                f"{'Kept' if kept else 'Dropped'} source ({badge}, {score}/100): "
                f"{enriched.get('title', '')[:70]} [{enriched.get('domain', '')}]"
            ),
            {
                "id": enriched["id"],
                "url": enriched.get("url"),
                "title": enriched.get("title"),
                "domain": enriched.get("domain"),
                "platform": platform_val,
                "source_type": source_type_val,
                "section_id": enriched.get("section_id"),
                "published_date": enriched.get("published_date"),
                "score": score,
                "badge": badge,
                "reasons": reasons,
                "kept": kept,
            },
        )

    return {
        "pending_sources": [],
        "sources": kept_sources,
        "dropped_sources": dropped_sources,
        "seen_urls": list(seen_urls),
    }


async def review_node(state: ResearchState) -> Dict[str, Any]:
    """
    Node 4: Hermes checks gaps (code checks first, then SMART_MODEL) and detects Both-Sides conflicts.
    Then evaluates the loop continuation decision in pure Python code.
    """
    run_id = state["run_id"]
    topic = state["topic"]
    search_type = state.get("search_type", "industrial")
    sections = list(state.get("plan", []))
    sources = state.get("sources", [])
    current_round = state.get("round", 1)
    max_rounds = min(int(state.get("max_rounds", MAX_REVIEW_ROUNDS)), MAX_REVIEW_ROUNDS)
    start_time = state.get("start_time", time.time())

    review_res = await review_sources(
        topic=topic,
        sections=sections,
        sources=sources,
        run_id=run_id,
        current_round=current_round,
        search_type=search_type,
    )

    complete = review_res["complete"]
    gaps = review_res["gaps"]
    new_conflicts = review_res["conflicts"]

    # Merge conflicts across rounds (deduplicate by normalized topic and verify source_ids in code)
    valid_source_ids = {
        int(s["id"]) for s in sources if s.get("id") is not None and str(s["id"]).isdigit()
    }
    existing_conflicts = list(state.get("conflicts", []))
    seen_conflict_topics = {
        " ".join(c.get("topic", "").lower().split()) for c in existing_conflicts
    }
    for c in new_conflicts:
        norm_t = " ".join(c.get("topic", "").lower().split())
        ids_a = c.get("side_a", {}).get("source_ids", [])
        ids_b = c.get("side_b", {}).get("source_ids", [])
        if (
            not norm_t
            or norm_t in seen_conflict_topics
            or not ids_a
            or not ids_b
            or any(sid not in valid_source_ids for sid in ids_a)
            or any(sid not in valid_source_ids for sid in ids_b)
        ):
            continue
        seen_conflict_topics.add(norm_t)
        existing_conflicts.append(c)

    # Pure Python STOP / LOOP decision check
    elapsed = time.time() - start_time
    time_remaining = RUN_TIMEOUT_SECONDS - elapsed
    can_continue = (
        (not complete)
        and (len(gaps) > 0)
        and (current_round < max_rounds)
        and (current_round < MAX_REVIEW_ROUNDS)
        and (time_remaining > 60)
    )

    if can_continue:
        next_round = current_round + 1
        follow_up_queries: List[Dict[str, str]] = []
        for g in gaps:
            sec_id = g["section_id"]
            fq = g["follow_up_query"]
            follow_up_queries.append({"section_id": sec_id, "query": fq})
            # Record follow-up question in plan's question_history for the Plan tab
            for sec in sections:
                if sec["id"] == sec_id:
                    history = list(sec.get("question_history", []))
                    history.append({"query": fq, "round": next_round, "reason": g.get("reason", "")})
                    sec["question_history"] = history

        emit_event(
            run_id,
            "round",
            "Apollo",
            f"Advancing to Round {next_round} of {max_rounds}: running {len(follow_up_queries)} follow-up search(es) for gaps.",
            {
                "round": next_round,
                "max_rounds": max_rounds,
                "queries_count": len(follow_up_queries),
                "gaps": gaps,
            },
        )
        return {
            "complete": complete,
            "gaps": gaps,
            "conflicts": existing_conflicts,
            "round": next_round,
            "plan": sections,
            "pending_queries": follow_up_queries,
            "continue_loop": True,
        }

    if not complete and len(gaps) > 0:
        hit_timeout = time_remaining <= 60
        stop_reason = (
            "Stopped at time limit"
            if hit_timeout
            else f"Reached max review rounds ({current_round}/{max_rounds})"
        )
        emit_event(
            run_id,
            "review",
            "Hermes",
            f"Stopping search loop ({stop_reason}). Proceeding to report writing with {len(sources)} verified sources.",
            {"round": current_round, "stop_reason": stop_reason, "stopped_at_time_limit": hit_timeout},
        )
        return {
            "complete": complete,
            "gaps": gaps,
            "conflicts": existing_conflicts,
            "continue_loop": False,
            "stopped_at_time_limit": hit_timeout,
        }

    return {
        "complete": complete,
        "gaps": gaps,
        "conflicts": existing_conflicts,
        "continue_loop": False,
        "stopped_at_time_limit": False,
    }


def should_continue_after_review(state: ResearchState) -> str:
    """
    Pure Python conditional edge function after Hermes review.
    Enforces MAX_REVIEW_ROUNDS and RUN_TIMEOUT_SECONDS in code.
    """
    elapsed = time.time() - state.get("start_time", time.time())
    if elapsed >= (RUN_TIMEOUT_SECONDS - 45):
        return "write"
    if state.get("round", 1) > MAX_REVIEW_ROUNDS:
        return "write"
    if state.get("continue_loop") and len(state.get("pending_queries", [])) > 0:
        return "search"
    return "write"


async def write_node(state: ResearchState) -> Dict[str, Any]:
    """Node 6: Writer drafts sections in parallel (FAST_MODEL) and assembles final report (SMART_MODEL)."""
    run_id = state["run_id"]
    topic = state["topic"]
    search_type = state.get("search_type", "industrial")
    sections = state.get("plan", [])
    sources = state.get("sources", [])

    report_md = await write_report(
        topic=topic,
        sections=sections,
        sources=sources,
        run_id=run_id,
        search_type=search_type,
    )
    return {"report_markdown": report_md}


async def judge_node(state: ResearchState) -> Dict[str, Any]:
    """Optional Judge Mode node between write and truth_check."""
    if not state.get("judge_mode", False):
        return {"judge_history": []}

    run_id = state["run_id"]
    topic = state["topic"]
    report_md = state.get("report_markdown", "")
    sources = state.get("sources", [])
    start_time = state.get("start_time", time.time())

    judge_res = await run_judge_loop(
        topic=topic,
        report_markdown=report_md,
        sources=sources,
        run_id=run_id,
        start_time=start_time,
        run_timeout_seconds=RUN_TIMEOUT_SECONDS,
    )
    return {
        "report_markdown": judge_res["report_markdown"],
        "judge_history": judge_res["judge_history"],
    }


async def truth_check_node(state: ResearchState) -> Dict[str, Any]:
    """Node 7: Truth Meter check (Phase 1 stub returning report unchanged)."""
    run_id = state["run_id"]
    report_md = state.get("report_markdown", "")
    sources = state.get("sources", [])

    tm_res = await run_truth_meter(
        report_markdown=report_md,
        sources=sources,
        run_id=run_id,
    )
    return {
        "report_markdown": tm_res["report_markdown"],
        "sentences_with_verdicts": tm_res["sentences_with_verdicts"],
        "trust_score": tm_res["trust_score"],
    }


async def done_node(state: ResearchState) -> Dict[str, Any]:
    """
    Node 8: Assemble final result payload, store it, and emit 'done'.
    """
    run_id = state["run_id"]
    elapsed_seconds = round(time.time() - state.get("start_time", time.time()), 2)

    all_events = get_run_events(run_id)
    warnings = [
        e["message"]
        for e in all_events
        if e.get("type") == "warning"
    ]

    kept_sources = state.get("sources", [])
    dropped_sources = state.get("dropped_sources", [])

    stats = {
        "searches": state.get("searches_count", 0),
        "sources_kept": len(kept_sources),
        "sources_dropped": len(dropped_sources),
        "llm_calls": get_llm_calls(run_id),
        "seconds": elapsed_seconds,
    }

    final_result = {
        "run_id": run_id,
        "topic": state["topic"],
        "search_type": state.get("search_type", "industrial"),
        "plan": state.get("plan", []),
        "sources": kept_sources,
        "dropped_sources": dropped_sources,
        "report_markdown": state.get("report_markdown", ""),
        "judge_history": state.get("judge_history", []),
        "sentences_with_verdicts": state.get("sentences_with_verdicts", []),
        "trust_score": state.get("trust_score"),
        "conflicts": state.get("conflicts", []),
        "rounds_used": state.get("round", 1),
        "stopped_at_time_limit": bool(
            state.get("stopped_at_time_limit") or (elapsed_seconds >= RUN_TIMEOUT_SECONDS - 60 and not state.get("complete", True))
        ),
        "warnings": warnings,
        "stats": stats,
    }

    set_run_result(run_id, final_result)

    emit_event(
        run_id,
        "done",
        "Apollo",
        (
            f"Research complete in {elapsed_seconds}s across {state.get('round', 1)} round(s): "
            f"{len(kept_sources)} sources kept, {len(dropped_sources)} dropped."
        ),
        final_result,
    )

    return {"final_result": final_result}


def build_research_graph():
    """Compile and return the LangGraph StateGraph for Apollo."""
    workflow = StateGraph(ResearchState)

    workflow.add_node("plan", plan_node)
    workflow.add_node("search", search_node)
    workflow.add_node("score", score_node)
    workflow.add_node("review", review_node)
    workflow.add_node("write", write_node)
    workflow.add_node("judge", judge_node)
    workflow.add_node("truth_check", truth_check_node)
    workflow.add_node("done", done_node)

    workflow.set_entry_point("plan")
    workflow.add_edge("plan", "search")
    workflow.add_edge("search", "score")
    workflow.add_edge("score", "review")
    workflow.add_conditional_edges(
        "review",
        should_continue_after_review,
        {
            "search": "search",
            "write": "write",
        },
    )
    workflow.add_edge("write", "judge")
    workflow.add_edge("judge", "truth_check")
    workflow.add_edge("truth_check", "done")
    workflow.add_edge("done", END)

    return workflow.compile()


# Compiled singleton graph
apollo_graph = build_research_graph()


async def execute_research_run(
    run_id: str,
    topic: str,
    max_rounds: int = MAX_REVIEW_ROUNDS,
    judge_mode: bool = False,
    search_type: str = "industrial",
) -> Dict[str, Any]:
    """
    Execute the full Apollo LangGraph pipeline for `run_id` and `topic`.
    Enforces overall RUN_TIMEOUT_SECONDS and emits an 'error' event if an unexpected crash occurs.
    """
    reset_llm_calls(run_id)
    start_time = time.time()
    clamped_rounds = max(1, min(int(max_rounds), MAX_REVIEW_ROUNDS))
    norm_search_type = (
        "domestic" if str(search_type or "").strip().lower() == "domestic" else "industrial"
    )

    initial_state: ResearchState = {
        "run_id": run_id,
        "topic": topic.strip(),
        "search_type": norm_search_type,
        "max_rounds": clamped_rounds,
        "judge_mode": bool(judge_mode),
        "start_time": start_time,
        "round": 1,
        "plan": [],
        "pending_queries": [],
        "pending_sources": [],
        "sources": [],
        "dropped_sources": [],
        "seen_urls": [],
        "searches_count": 0,
        "complete": False,
        "gaps": [],
        "conflicts": [],
        "continue_loop": False,
        "stopped_at_time_limit": False,
        "report_markdown": "",
        "judge_history": [],
        "sentences_with_verdicts": [],
        "trust_score": None,
        "final_result": {},
    }

    try:
        final_state = await apollo_graph.ainvoke(initial_state)
        return final_state.get("final_result", {})
    except Exception as exc:
        emit_event(
            run_id,
            "error",
            "System",
            f"Pipeline error: {exc}",
            {"error": str(exc)},
        )
        fallback_result = {
            "run_id": run_id,
            "topic": topic,
            "plan": [],
            "sources": [],
            "dropped_sources": [],
            "report_markdown": f"# Error\n\nResearch run encountered an error: {exc}",
            "sentences_with_verdicts": [],
            "trust_score": None,
            "conflicts": [],
            "rounds_used": 1,
            "warnings": [str(exc)],
            "stats": {
                "searches": 0,
                "sources_kept": 0,
                "sources_dropped": 0,
                "llm_calls": get_llm_calls(run_id),
                "seconds": round(time.time() - start_time, 2),
            },
        }
        set_run_result(run_id, fallback_result)
        return fallback_result
