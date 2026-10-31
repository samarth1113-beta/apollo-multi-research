"""
Judge & Reviser Agent (backend/agents/judge.py).
Optional Judge Mode step between `write` and `truth_check`:
- Judge (SMART_MODEL) scores the report 0 to 10 and lists fixes as JSON:
  {"score": 7, "fixes": ["...", "..."]}
- Reviser (FAST_MODEL) applies the fixes using ONLY existing sources and [n] citations.
- Repeats until score >= 8 or 3 rounds (capped in Python code).
- Emits live events for each judge score and fix count.
"""
import time
from typing import Any, Dict, List

from events import emit_event
from tools.llm import call_llm, get_fast_model, get_smart_model

MAX_JUDGE_ROUNDS = 3
PASSING_JUDGE_SCORE = 8


async def run_judge_loop(
    topic: str,
    report_markdown: str,
    sources: List[Dict[str, Any]],
    run_id: str,
    start_time: float,
    run_timeout_seconds: int = 360,
) -> Dict[str, Any]:
    """
    Run up to MAX_JUDGE_ROUNDS of Judge (SMART_MODEL) + Reviser (FAST_MODEL).
    Returns {"report_markdown": current_report, "judge_history": [...]}.
    """
    if not sources or not report_markdown.strip():
        emit_event(
            run_id,
            "judge",
            "Judge",
            "Judge Mode skipped: no verified sources available to revise against.",
            {"score": 0, "fixes_count": 0, "round": 0},
        )
        return {"report_markdown": report_markdown, "judge_history": []}

    source_blocks = []
    for s in sources[:20]:
        source_blocks.append(
            f"SOURCE [{s['id']}] ({s.get('title')} - {s.get('domain')}, {s.get('published_date') or 'n.d.'}):\n"
            f"{(s.get('content') or '')[:1200]}"
        )
    sources_context = "\n\n---\n\n".join(source_blocks)

    current_report = report_markdown
    judge_history: List[Dict[str, Any]] = []

    for judge_round in range(1, MAX_JUDGE_ROUNDS + 1):
        # Enforce overall run timeout in Python code
        if (time.time() - start_time) >= (run_timeout_seconds - 45):
            emit_event(
                run_id,
                "judge",
                "Judge",
                f"Judge loop stopped at round {judge_round} due to time limit.",
                {"round": judge_round, "stopped_at_time_limit": True},
            )
            break

        judge_system = (
            "You are Apollo's Chief Research Judge.\n"
            "Evaluate the drafted research report on a 0 to 10 scale based on:\n"
            "1. Completeness & depth in answering the research topic using the provided sources.\n"
            "2. Strict inline citation coverage: every factual sentence must end with valid [n] citations from the source list.\n"
            "3. Clarity, synthesis of numbers/perspectives, and logical flow.\n\n"
            "Return ONLY valid JSON matching this exact schema:\n"
            '{"score": 7, "fixes": ["Specific actionable fix 1", "Specific actionable fix 2"]}'
        )
        judge_user = (
            f"Research Topic: {topic}\n"
            f"Judge Round: {judge_round} of {MAX_JUDGE_ROUNDS}\n\n"
            f"Available Verified Sources:\n{sources_context}\n\n"
            f"Current Report Draft:\n{current_report}\n\n"
            "Score this report from 0 to 10 and list specific fixes needed (or empty list if score >= 8). Return JSON only."
        )

        default_eval = {"score": 8, "fixes": []}
        eval_res = await call_llm(
            model=get_smart_model(),
            messages=[
                {"role": "system", "content": judge_system},
                {"role": "user", "content": judge_user},
            ],
            json_mode=True,
            run_id=run_id,
            default_json=default_eval,
            agent_name="Judge",
        )

        if not isinstance(eval_res, dict):
            eval_res = default_eval

        raw_score = eval_res.get("score", 8)
        try:
            score = max(0, min(10, int(float(raw_score))))
        except Exception:
            score = 8

        raw_fixes = eval_res.get("fixes") or []
        if not isinstance(raw_fixes, list):
            raw_fixes = [str(raw_fixes)]
        fixes = [str(f).strip() for f in raw_fixes if str(f).strip()][:5]

        judge_entry = {
            "round": judge_round,
            "score": score,
            "fixes": fixes,
            "fixes_count": len(fixes),
        }
        judge_history.append(judge_entry)

        emit_event(
            run_id,
            "judge",
            "Judge",
            (
                f"Judge Round {judge_round}/{MAX_JUDGE_ROUNDS}: Score {score}/10 — "
                f"{len(fixes)} fix(es) requested"
                + (f": {'; '.join(fixes[:2])}" if fixes else " (Passed threshold!)")
            ),
            judge_entry,
        )

        # Pure Python cap: stop if score >= 8, no fixes listed, or reached MAX_JUDGE_ROUNDS (3)
        if score >= PASSING_JUDGE_SCORE or len(fixes) == 0 or judge_round >= MAX_JUDGE_ROUNDS:
            break

        # Reviser (FAST_MODEL) applies fixes using ONLY existing sources and [n] citations
        emit_event(
            run_id,
            "writing",
            "Writer",
            f"Reviser applying {len(fixes)} judge fix(es) (Round {judge_round}/{MAX_JUDGE_ROUNDS})...",
            {"round": judge_round, "fixes_count": len(fixes), "stage": "judge_revision"},
        )

        fixes_bullet_text = "\n".join(f"- {fx}" for fx in fixes)
        reviser_system = (
            "You are Apollo's Report Reviser.\n"
            "Apply the Judge's requested fixes to improve the report while obeying these STRICT rules:\n"
            "1. Use ONLY facts present in the provided SOURCE [n] blocks. Never use outside memory.\n"
            "2. Keep valid [n] inline citations at the end of every factual sentence.\n"
            "3. Never invent source IDs.\n"
            "4. Return the complete revised Markdown report."
        )
        reviser_user = (
            f"Research Topic: {topic}\n\n"
            f"Judge Score: {score}/10\n"
            f"Fixes to Apply:\n{fixes_bullet_text}\n\n"
            f"Verified Sources:\n{sources_context}\n\n"
            f"Current Report Draft:\n{current_report}\n\n"
            "Output the full revised Markdown report now."
        )

        revised_md = await call_llm(
            model=get_fast_model(),
            messages=[
                {"role": "system", "content": reviser_system},
                {"role": "user", "content": reviser_user},
            ],
            json_mode=False,
            run_id=run_id,
            timeout=60.0,
            agent_name="Writer",
        )

        if revised_md and revised_md.strip():
            current_report = revised_md.strip()

    return {
        "report_markdown": current_report,
        "judge_history": judge_history,
    }
