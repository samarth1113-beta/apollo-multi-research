"""
Writer Agent (backend/agents/writer.py).
1. Runs one writer call per section (FAST_MODEL) in parallel using ONLY that section's kept sources.
   Sources are numbered globally [1], [2], ... Every factual sentence must end with a citation like [3].
2. Runs ONE final assembler call (SMART_MODEL) that sees all drafted sections and writes:
   intro, smooth sections, conclusion, keeping all [n] citations intact.
"""
import asyncio
from typing import Any, Dict, List

from events import emit_event
from tools.llm import call_llm, get_fast_model, get_smart_model


async def _write_single_section(
    topic: str,
    section: Dict[str, Any],
    section_sources: List[Dict[str, Any]],
    run_id: str,
    search_type: str = "industrial",
) -> Dict[str, str]:
    """Write a single section using FAST_MODEL and only that section's globally numbered sources."""
    sec_id = section["id"]
    sec_title = section["title"]
    is_domestic = str(search_type or "industrial").lower() == "domestic"

    if not section_sources:
        emit_event(
            run_id,
            "writing",
            "Writer",
            f"Section '{sec_title}' has 0 verified sources; noting evidence limitation.",
            {"section_id": sec_id, "stage": "section_empty"},
        )
        return {
            "section_id": sec_id,
            "title": sec_title,
            "draft": (
                f"## {sec_title}\n\n"
                "No verified external sources met the credibility threshold for this section's specific queries."
            ),
        }

    emit_event(
        run_id,
        "writing",
        "Writer",
        f"Drafting section '{sec_title}' from {len(section_sources)} verified source(s)...",
        {"section_id": sec_id, "sources_count": len(section_sources), "stage": "section_start"},
    )

    source_blocks = []
    for s in section_sources:
        source_blocks.append(
            f"SOURCE [{s['id']}]\n"
            f"Title: {s.get('title')}\n"
            f"Platform: {s.get('platform', 'Web')} | Type: {s.get('source_type', '')} | Domain: {s.get('domain')} | Published: {s.get('published_date') or 'Unknown'}\n"
            f"Content:\n{s.get('content')}\n"
        )
    sources_context = "\n---\n".join(source_blocks)

    if is_domestic:
        system_prompt = (
            "You are a consumer product researcher in the Apollo pipeline.\n"
            "STRICT RULES:\n"
            "1. Write ONLY using facts, prices (in ₹), specs, ratings, and real user opinions explicitly stated in the provided SOURCE blocks. Never use outside memory.\n"
            "2. NEVER invent prices, ratings, or specs. If a price, rating, or spec is not present in the sources, explicitly write 'not found in sources'.\n"
            "3. Paraphrase real user experiences (from Reddit, Quora, YouTube, X) accurately and end EVERY single factual sentence with one or more citations in square brackets using the exact global source number, e.g., [1] or [2][5].\n"
            "4. Output markdown starting with `## <Section Title>`."
        )
    else:
        system_prompt = (
            "You are a rigorous research writer in the Apollo pipeline.\n"
            "STRICT RULES:\n"
            "1. Write ONLY using facts explicitly stated in the provided SOURCE blocks. Never use outside memory.\n"
            "2. Every single factual sentence MUST end with one or more citations in square brackets using the exact global source number, e.g., [1] or [2][5].\n"
            "3. Do NOT invent source numbers. Only cite from the provided SOURCE [n] blocks.\n"
            "4. If two sources report different numbers or perspectives, state both clearly with their respective citations.\n"
            "5. Output markdown starting with `## <Section Title>`."
        )
    user_prompt = (
        f"Overall Research Topic: {topic}\n"
        f"Section Title: {sec_title}\n"
        f"Guiding Questions: {', '.join(section.get('questions', []))}\n\n"
        f"Verified Sources for this Section:\n{sources_context}\n\n"
        f"Write the section `## {sec_title}` now with strict [n] citations on every factual sentence."
    )

    draft = await call_llm(
        model=get_fast_model(),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        json_mode=False,
        run_id=run_id,
        agent_name="Writer",
        max_tokens=900,
    )

    if not draft.strip():
        # Safe fallback built strictly from retrieved source snippets
        fallback_lines = [f"## {sec_title}", ""]
        for s in section_sources[:4]:
            first_sent = (s.get("content") or "").strip().split(". ")[0].strip()
            if first_sent:
                if not first_sent.endswith("."):
                    first_sent += "."
                fallback_lines.append(f"{first_sent} [{s['id']}]")
        draft = "\n\n".join(fallback_lines)

    emit_event(
        run_id,
        "writing",
        "Writer",
        f"Completed draft for section '{sec_title}'.",
        {"section_id": sec_id, "stage": "section_done"},
    )

    return {
        "section_id": sec_id,
        "title": sec_title,
        "draft": draft.strip(),
    }


async def write_report(
    topic: str,
    sections: List[Dict[str, Any]],
    sources: List[Dict[str, Any]],
    run_id: str,
    search_type: str = "industrial",
) -> str:
    """
    Draft all sections in parallel (FAST_MODEL), then assemble into one cohesive
    cited report (SMART_MODEL).
    """
    is_domestic = str(search_type or "industrial").lower() == "domestic"
    if not sources:
        emit_event(
            run_id,
            "warning",
            "Writer",
            "No verified sources passed the quality threshold. Producing minimal status report.",
            {"topic": topic},
        )
        return (
            f"# {topic}\n\n"
            "No external sources passed the minimum credibility score threshold (35/100) "
            "or returned usable text for this topic. In accordance with Apollo's strict "
            "zero-hallucination rule, no claims have been generated from model memory."
        )

    # Group sources by section_id; if a section has 0 sources but global sources exist,
    # keep it strictly tied to its section (or allow cross-referencing only if needed).
    by_section: Dict[str, List[Dict[str, Any]]] = {s["id"]: [] for s in sections}
    for src in sources:
        sec_id = src.get("section_id")
        if sec_id in by_section:
            by_section[sec_id].append(src)

    # Run per-section writers in parallel
    tasks = [
        _write_single_section(topic, sec, by_section.get(sec["id"], []), run_id, search_type=search_type)
        for sec in sections
    ]
    section_drafts = await asyncio.gather(*tasks)

    emit_event(
        run_id,
        "writing",
        "Writer",
        "Assembling final report with introduction, smooth transitions, and conclusion...",
        {"stage": "assembly_start", "sections_count": len(section_drafts)},
    )

    combined_drafts = "\n\n".join(d["draft"] for d in section_drafts)
    source_catalog = "\n".join(
        f"[{s['id']}] ({s.get('platform', 'Web')} / {s.get('source_type', '')}) {s.get('title')} ({s.get('domain')}, {s.get('published_date') or 'n.d.'})"
        for s in sources
    )

    if is_domestic:
        assembler_system = (
            "You are Apollo's Lead Consumer Research Report Assembler.\n"
            "You receive drafted sections where every factual sentence carries global citations like [1], [2].\n"
            "Structure the final Markdown report in this exact order:\n"
            "1. `# <Report Title>` followed by `## Short Summary` (concise overview with `[n]` citations on every factual sentence).\n"
            "2. `## Comparison Table` containing a Markdown table with columns: `| Product | Price in ₹ | Key Specs | Rating |`.\n"
            "   - CRITICAL: Never invent prices, ratings, or specs. If any price, spec, or rating is not explicitly in the sources, write `not found in sources` in that cell.\n"
            "3. `## What real users say` — paraphrased real user experiences from Reddit, YouTube, Quora, and X, with `[n]` citations at the end of every factual sentence.\n"
            "4. `## Common complaints` — recurring problems, drawbacks, or after-sales complaints reported in sources, with `[n]` citations at the end of every factual sentence.\n"
            "5. `## Who should buy which` — clear buyer guidance grounded strictly in the cited sources, with `[n]` citations on every factual sentence.\n"
            "6. `## Verdict` — final recommendation grounded strictly in the sources, with `[n]` citations on every factual sentence.\n"
            "NEVER invent facts, prices, ratings, specs, or citation numbers."
        )
    else:
        assembler_system = (
            "You are Apollo's Lead Report Assembler.\n"
            "You receive drafted research sections where every factual sentence already carries global citations like [1], [2].\n"
            "Your job:\n"
            "1. Write a clear `# Title` and a concise `## Executive Introduction` summarizing the scope (citing relevant [n] sources).\n"
            "2. Present each section cleanly, preserving ALL factual details and keeping EVERY `[n]` citation at the end of factual sentences.\n"
            "3. Add a `## Conclusion & Key Takeaways` section grounded strictly in the cited findings.\n"
            "4. NEVER invent facts or citation numbers not present in the drafts or source list. Do NOT append a bibliography at the bottom (the UI renders sources separately), or if you do, keep `[n]` inline citations intact."
        )
    assembler_user = (
        f"Research Topic: {topic}\n\n"
        f"Available Numbered Sources:\n{source_catalog}\n\n"
        f"Section Drafts:\n{combined_drafts}\n\n"
        "Assemble the final polished Markdown report now, keeping all [n] citations on every factual sentence."
    )

    final_report = await call_llm(
        model=get_smart_model(),
        messages=[
            {"role": "system", "content": assembler_system},
            {"role": "user", "content": assembler_user},
        ],
        json_mode=False,
        run_id=run_id,
        timeout=65.0,
        agent_name="Writer",
        max_tokens=2500,
    )

    if not final_report.strip():
        final_report = f"# {topic}\n\n{combined_drafts}"

    emit_event(
        run_id,
        "writing",
        "Writer",
        "Final report assembled with inline citations.",
        {"stage": "assembly_done", "length_chars": len(final_report)},
    )

    return final_report.strip()
