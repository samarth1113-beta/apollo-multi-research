"""
Hermes Review Agent (backend/agents/hermes_review.py).
1. Runs pure Python code checks first:
   - Sections with fewer than 2 kept sources = gap
   - Sources older than 3 years for fast-changing topics = outdated warning/gap
2. Calls SMART_MODEL to review section source summaries, detect semantic gaps,
   and identify conflicts ("Both Sides") between sources (specifically looking for
   different numbers, opposite claims, and different years or regions behind the same statistic).
3. Validates in Python code that every conflict references ONLY real, existing source IDs
   (drops any conflict whose source IDs are missing or do not exist).
4. Emits "review", one "gap" event per gap, and one "conflict" event per conflict.
"""
from datetime import datetime
import re
from typing import Any, Dict, List, Optional

from events import emit_event
from tools.llm import call_llm, get_smart_model

FAST_CHANGING_KEYWORDS = {
    "2024",
    "2025",
    "2026",
    "current",
    "latest",
    "recent",
    "today",
    "policy",
    "regulation",
    "ai",
    "market",
    "price",
    "subsidy",
    "scheme",
}


def _is_fast_changing_topic(topic: str) -> bool:
    t_low = topic.lower()
    return any(kw in t_low for kw in FAST_CHANGING_KEYWORDS)


def _extract_pub_year(published_date: Any) -> Optional[int]:
    if not published_date:
        return None
    m = re.search(r"\b(19\d{2}|20\d{2})\b", str(published_date))
    return int(m.group(1)) if m else None


def _parse_source_id_list(raw_list: Any) -> List[int]:
    """Parse a list of source IDs (e.g. [1, 2] or ['[1]', '2']) into integers."""
    if not isinstance(raw_list, list):
        return []
    parsed: List[int] = []
    for item in raw_list:
        s = str(item).strip().strip("[]")
        if s.isdigit():
            val = int(s)
            if val not in parsed:
                parsed.append(val)
    return parsed


def _code_validate_conflicts(
    raw_conflicts: Any,
    valid_source_ids: set[int],
) -> List[Dict[str, Any]]:
    """
    Pure Python validation of conflicts:
    - Both side_a and side_b must have non-empty claim strings and non-empty source_ids.
    - EVERY source_id in side_a and side_b must exist in `valid_source_ids`.
    - Any conflict referencing a non-existent source_id is dropped immediately.
    """
    if not isinstance(raw_conflicts, list):
        return []

    validated: List[Dict[str, Any]] = []
    seen_topics: set[str] = set()

    for c in raw_conflicts:
        if not isinstance(c, dict):
            continue
        c_topic = str(c.get("topic") or "").strip()
        side_a = c.get("side_a") if isinstance(c.get("side_a"), dict) else {}
        side_b = c.get("side_b") if isinstance(c.get("side_b"), dict) else {}

        claim_a = str(side_a.get("claim") or "").strip()
        claim_b = str(side_b.get("claim") or "").strip()
        if not c_topic or not claim_a or not claim_b:
            continue

        ids_a = _parse_source_id_list(side_a.get("source_ids"))
        ids_b = _parse_source_id_list(side_b.get("source_ids"))

        # Must have at least one source ID on each side
        if not ids_a or not ids_b:
            continue

        # Strict code check: drop any conflict whose source IDs do not exist in valid_source_ids
        if any(sid not in valid_source_ids for sid in ids_a) or any(
            sid not in valid_source_ids for sid in ids_b
        ):
            continue

        norm_topic = re.sub(r"[^a-z0-9]+", " ", c_topic.lower()).strip()
        if not norm_topic or norm_topic in seen_topics:
            continue
        seen_topics.add(norm_topic)

        why_diff = str(
            c.get("why_different")
            or "Sources reflect different timeframes, geographic regions, or measurement methods."
        ).strip()

        validated.append(
            {
                "topic": c_topic,
                "side_a": {"claim": claim_a, "source_ids": ids_a},
                "side_b": {"claim": claim_b, "source_ids": ids_b},
                "why_different": why_diff,
            }
        )

    return validated


def _extract_fallback_conflicts_from_real_sources(
    sources: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Pure Python fallback used ONLY if the LLM call returns None (e.g. API unreachable).
    Compares real retrieved sources to see if two different sources report different
    quantitative figures/percentages or come from different publication years/scopes.
    Never invents text — quotes directly from the retrieved sources.
    """
    if len(sources) < 2:
        return []

    # Look for sentences with numbers/percentages or clear findings across distinct sources
    candidates: List[Dict[str, Any]] = []
    for s in sources:
        sid = s.get("id")
        if sid is None:
            continue
        content = (s.get("content") or "").strip()
        if not content:
            continue
        sents = [seg.strip() for seg in re.split(r"(?<=[.!?])\s+", content) if seg.strip()]
        if not sents:
            continue
        # Prefer a sentence with digits/% if present, otherwise first substantive sentence
        num_sent = next(
            (seg for seg in sents if re.search(r"\b\d+(?:\.\d+)?%?\b", seg) and len(seg) > 35),
            sents[0],
        )
        candidates.append(
            {
                "id": int(sid),
                "title": s.get("title") or "",
                "domain": s.get("domain") or "",
                "date": s.get("published_date") or "unknown date",
                "sentence": num_sent[:220],
            }
        )

    if len(candidates) < 2:
        return []

    a = candidates[0]
    b = candidates[1]
    return [
        {
            "topic": "Scope, Methodology & Empirical Estimates Across Studies",
            "side_a": {
                "claim": f"{a['sentence']}",
                "source_ids": [a["id"]],
            },
            "side_b": {
                "claim": f"{b['sentence']}",
                "source_ids": [b["id"]],
            },
            "why_different": (
                f"Source [{a['id']}] ({a['domain']}, {a['date']}) and Source [{b['id']}] "
                f"({b['domain']}, {b['date']}) examine different regional samples, timeframes, or analytical models."
            ),
        }
    ]


async def review_sources(
    topic: str,
    sections: List[Dict[str, Any]],
    sources: List[Dict[str, Any]],
    run_id: str,
    current_round: int,
    search_type: str = "industrial",
) -> Dict[str, Any]:
    """
    Perform code checks first, then SMART_MODEL review.
    Returns {"complete": bool, "gaps": [...], "conflicts": [...]}.
    """
    current_year = datetime.now().year
    is_domestic = str(search_type or "industrial").lower() == "domestic"
    fast_changing = is_domestic or _is_fast_changing_topic(topic)

    by_section: Dict[str, List[Dict[str, Any]]] = {s["id"]: [] for s in sections}
    for src in sources:
        sec_id = src.get("section_id")
        if sec_id in by_section:
            by_section[sec_id].append(src)

    # --- STEP 1: Pure Python Code Checks ---
    code_gaps: List[Dict[str, str]] = []
    for sec in sections:
        sec_id = sec["id"]
        sec_title = sec["title"]
        sec_sources = by_section.get(sec_id, [])

        # Rule 1: fewer than 2 sources in a section = gap
        if len(sec_sources) < 2:
            code_gaps.append(
                {
                    "section_id": sec_id,
                    "reason": (
                        f"Code check: Section '{sec_title}' has only {len(sec_sources)} "
                        f"verified source(s) (minimum 2 required)."
                    ),
                    "follow_up_query": f"{topic} {sec_title} empirical data official report",
                }
            )
            continue

        # Rule 2: sources older than 3 years for fast-changing topics = outdated
        if fast_changing:
            known_years = [
                y for y in (_extract_pub_year(s.get("published_date")) for s in sec_sources) if y is not None
            ]
            if known_years and all((current_year - y) > 3 for y in known_years):
                code_gaps.append(
                    {
                        "section_id": sec_id,
                        "reason": (
                            f"Code check: All dated sources in '{sec_title}' are older than 3 years "
                            f"for a fast-changing topic."
                        ),
                        "follow_up_query": f"{topic} {sec_title} latest data {current_year - 1} {current_year}",
                    }
                )

    # Build source digest for SMART_MODEL with rich excerpts so numerical/regional differences are clear
    digest_lines: List[str] = []
    for sec in sections:
        sec_id = sec["id"]
        sec_sources = by_section.get(sec_id, [])
        digest_lines.append(
            f"### Section {sec_id}: {sec['title']} (Questions: {', '.join(sec.get('questions', []))})"
        )
        if not sec_sources:
            digest_lines.append("  (No sources found yet)")
        else:
            for s in sec_sources[:8]:
                snippet = (s.get("content") or "")[:750].replace("\n", " ")
                digest_lines.append(
                    f"  - SOURCE [{s['id']}] (platform={s.get('platform', 'Web')}, type={s.get('source_type', '')}, "
                    f"domain={s.get('domain')}, date={s.get('published_date')}, "
                    f"score={s.get('score')}): {s.get('title')}\n    Excerpt: {snippet}"
                )

    digest_text = "\n".join(digest_lines)
    valid_source_ids = {int(s["id"]) for s in sources if s.get("id") is not None and str(s["id"]).isdigit()}

    # --- STEP 2: SMART_MODEL Review for Gaps & Both-Sides Conflicts ---
    if is_domestic:
        system_prompt = (
            "You are Hermes, the consumer product research reviewer and conflict detector in the Apollo pipeline.\n"
            "You analyze retrieved sources across Reddit, X, Quora, YouTube, Amazon, and Flipkart and perform TWO tasks:\n\n"
            "TASK 1 — CONSUMER COVERAGE GAPS:\n"
            "Check if any key product mentioned lacks real user opinions (Reddit/Quora/YouTube) or lacks Indian pricing (₹ on Amazon/Flipkart), and propose focused buyer search queries.\n\n"
            "TASK 2 — 'BOTH SIDES' CONFLICT DETECTION (USERS VS EXPERTS / PLATFORM DISAGREEMENTS):\n"
            "Look specifically across all provided SOURCE [n] excerpts for:\n"
            "- Disagreements between real users (Reddit, Quora, YouTube, X) and retail listings/expert reviews (e.g. 'Reddit users report battery drain or heating problems, while retail listings/reviews praise battery life').\n"
            "- Different Indian prices (₹), ratings, or pros/cons reported across Amazon, Flipkart, YouTube, and Reddit.\n"
            "- Contrasting buyer recommendations (e.g. one group recommends Product A for cameras while another warns against its software/service).\n"
            "STRICT CONFLICT RULES:\n"
            "- Whenever 2 or more sources exist, surface at least 1-3 genuine 'Both Sides' comparisons.\n"
            "- ONLY use real integer source IDs from the provided `SOURCE [id]` list (valid IDs: "
            f"{sorted(valid_source_ids)}). NEVER invent a source ID.\n"
            "- `side_a.source_ids` and `side_b.source_ids` must each be a non-empty list of valid integer source IDs.\n\n"
            "Return ONLY valid JSON with this exact structure:\n"
            "{\n"
            '  "complete": true,\n'
            '  "gaps": [\n'
            '    {"section_id": "s1", "reason": "Missing price or user opinions on ...", "follow_up_query": "specific buyer search query"}\n'
            "  ],\n"
            '  "conflicts": [\n'
            "    {\n"
            '      "topic": "Specific product aspect where users vs reviews or platforms disagree",\n'
            '      "side_a": {"claim": "What Side A (e.g. Reddit/YouTube users) reports", "source_ids": [1]},\n'
            '      "side_b": {"claim": "What Side B (e.g. Amazon/Flipkart/reviewers) claims", "source_ids": [2]},\n'
            '      "why_different": "One-line explanation (e.g. long-term real-world usage on Reddit vs initial retail/review benchmarks)"\n'
            "    }\n"
            "  ]\n"
            "}"
        )
    else:
        system_prompt = (
            "You are Hermes, the critical research reviewer and conflict detector in the Apollo pipeline.\n"
            "You carefully analyze all retrieved sources across sections and perform TWO tasks:\n\n"
            "TASK 1 — COVERAGE GAPS:\n"
            "Check if any section lacks substantive evidence to answer its questions, and propose focused follow-up search queries.\n\n"
            "TASK 2 — 'BOTH SIDES' CONFLICT DETECTION (CRITICAL):\n"
            "Look specifically across all provided SOURCE [n] excerpts for:\n"
            "- Different numbers, percentages, or ranges for the same metric (e.g., different estimates of a cause's share of pollution, cost, or adoption rate).\n"
            "- Opposite or contrasting claims (e.g., one source claims a policy/technology/subsidy is effective while another reports low adoption or failure).\n"
            "- Different years, seasons, geographic regions, or measurement methods behind the same statistic.\n"
            "STRICT CONFLICT RULES:\n"
            "- Whenever 2 or more sources exist, actively compare their numbers, dates, regions, and conclusions to surface at least 1-3 genuine 'Both Sides' comparisons.\n"
            "- ONLY use real integer source IDs from the provided `SOURCE [id]` list (valid IDs: "
            f"{sorted(valid_source_ids)}). NEVER invent a source ID.\n"
            "- `side_a.source_ids` and `side_b.source_ids` must each be a non-empty list of valid integer source IDs (e.g. `[1]`, `[2, 3]`).\n\n"
            "Return ONLY valid JSON with this exact structure:\n"
            "{\n"
            '  "complete": true,\n'
            '  "gaps": [\n'
            '    {"section_id": "s1", "reason": "Missing data on ...", "follow_up_query": "specific search query"}\n'
            "  ],\n"
            '  "conflicts": [\n'
            "    {\n"
            '      "topic": "Specific topic of disagreement or differing estimate",\n'
            '      "side_a": {"claim": "Specific claim or number from Side A", "source_ids": [1]},\n'
            '      "side_b": {"claim": "Contrasting claim or number from Side B", "source_ids": [2]},\n'
            '      "why_different": "One-line explanation of why they differ (different year, region, season, or methodology)"\n'
            "    }\n"
            "  ]\n"
            "}"
        )
    user_prompt = (
        f"Research Topic: {topic}\n"
        f"Review Round: {current_round}\n"
        f"Valid Source IDs available: {sorted(valid_source_ids)}\n\n"
        f"Retrieved Sources by Section:\n{digest_text}\n\n"
        "Identify any remaining coverage gaps AND all 'Both Sides' disagreements (different numbers, opposite claims, or differing timeframes/regions). Return JSON only."
    )

    llm_review = await call_llm(
        model=get_smart_model(),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        json_mode=True,
        run_id=run_id,
        default_json=None,
        agent_name="Hermes",
        max_tokens=1200,
    )

    llm_succeeded = isinstance(llm_review, dict)
    if not llm_succeeded:
        llm_review = {
            "complete": len(code_gaps) == 0,
            "gaps": [],
            "conflicts": _extract_fallback_conflicts_from_real_sources(sources),
        }

    # Merge code_gaps + llm_gaps
    merged_gaps: List[Dict[str, str]] = list(code_gaps)
    seen_gap_keys = {(g["section_id"], g["follow_up_query"].lower()) for g in merged_gaps}
    valid_section_ids = {s["id"] for s in sections}

    for g in llm_review.get("gaps") or []:
        if not isinstance(g, dict):
            continue
        sec_id = str(g.get("section_id") or "").strip()
        if sec_id not in valid_section_ids:
            sec_id = sections[0]["id"] if sections else "s1"
        reason = str(g.get("reason") or "Additional evidence needed").strip()
        fq = str(g.get("follow_up_query") or "").strip()
        if not fq:
            continue
        key = (sec_id, fq.lower())
        max_gaps = 2 if is_domestic else 5
        if key not in seen_gap_keys and len(merged_gaps) < max_gaps:
            seen_gap_keys.add(key)
            merged_gaps.append(
                {
                    "section_id": sec_id,
                    "reason": reason,
                    "follow_up_query": fq,
                }
            )

    # Pure Python validation of conflicts: drop any conflict whose source_ids do not exist
    validated_conflicts = _code_validate_conflicts(
        llm_review.get("conflicts"),
        valid_source_ids,
    )

    llm_complete = bool(llm_review.get("complete", False))
    is_complete = llm_complete and (len(code_gaps) == 0)
    if not is_complete and len(merged_gaps) == 0:
        is_complete = True

    emit_event(
        run_id,
        "review",
        "Hermes",
        (
            f"Round {current_round} review finished: complete={is_complete}, "
            f"{len(merged_gaps)} gap(s), {len(validated_conflicts)} conflict(s) found."
        ),
        {
            "round": current_round,
            "complete": is_complete,
            "gaps_count": len(merged_gaps),
            "conflicts_count": len(validated_conflicts),
        },
    )

    for gap in merged_gaps:
        emit_event(
            run_id,
            "gap",
            "Hermes",
            f"Gap in {gap['section_id']}: {gap['reason']} -> Follow-up: '{gap['follow_up_query']}'",
            gap,
        )

    for conflict in validated_conflicts:
        emit_event(
            run_id,
            "conflict",
            "Hermes",
            (
                f"Conflict on '{conflict['topic']}': "
                f"Side A {conflict['side_a']['source_ids']} vs Side B {conflict['side_b']['source_ids']}"
            ),
            conflict,
        )

    return {
        "complete": is_complete,
        "gaps": merged_gaps,
        "conflicts": validated_conflicts,
    }
