"""
Apollo Planner Agent (backend/agents/apollo_planner.py).
Creates a structured research plan of 3 to MAX_SECTIONS sections, each with targeted search questions.
"""
from typing import Any, Dict, List

from events import emit_event
from tools.llm import call_llm, get_smart_model

MAX_SECTIONS = 5


def _fallback_plan(topic: str) -> Dict[str, Any]:
    """Safe fallback plan in case the LLM fails or returns invalid JSON."""
    return {
        "sections": [
            {
                "id": "s1",
                "title": "Background & Core Drivers",
                "questions": [
                    f"{topic} background causes and main drivers",
                    f"{topic} key statistics and recent data",
                ],
            },
            {
                "id": "s2",
                "title": "Current Policies, Interventions & Solutions",
                "questions": [
                    f"{topic} government policies and interventions",
                    f"{topic} solutions working in practice evaluation",
                ],
            },
            {
                "id": "s3",
                "title": "Challenges, Debates & Future Outlook",
                "questions": [
                    f"{topic} implementation challenges and limitations",
                    f"{topic} expert recommendations and future outlook",
                ],
            },
        ]
    }


def _fallback_domestic_plan(topic: str) -> Dict[str, Any]:
    """Safe fallback plan for Domestic consumer/product research."""
    return {
        "sections": [
            {
                "id": "s1",
                "title": "Products and prices in India",
                "questions": [
                    f"{topic} price in India Amazon Flipkart ₹",
                ],
            },
            {
                "id": "s2",
                "title": "Specs and features",
                "questions": [
                    f"{topic} full specs features comparison India",
                ],
            },
            {
                "id": "s3",
                "title": "What real users say",
                "questions": [
                    f"{topic} real user review experience Reddit Quora India",
                ],
            },
            {
                "id": "s4",
                "title": "Common problems and complaints",
                "questions": [
                    f"{topic} problems issues heating battery service complaints",
                ],
            },
            {
                "id": "s5",
                "title": "Verdict",
                "questions": [
                    f"{topic} which one to buy worth it verdict India",
                ],
            },
        ]
    }


async def plan_research(
    topic: str,
    run_id: str,
    search_type: str = "industrial",
) -> List[Dict[str, Any]]:
    """
    Generate 3 to 5 research sections with targeted search questions using SMART_MODEL.
    Branches by `search_type` ("industrial" vs "domestic").
    Emits a 'plan' event and returns the list of validated section dicts.
    """
    model = get_smart_model()
    is_domestic = str(search_type or "industrial").lower() == "domestic"

    if is_domestic:
        system_prompt = (
            "You are Apollo, the lead consumer product research planner.\n"
            "Create a 5-section research plan for an Indian consumer/buyer using these exact 5 section titles:\n"
            '1. "Products and prices in India" (id: "s1")\n'
            '2. "Specs and features" (id: "s2")\n'
            '3. "What real users say" (id: "s3")\n'
            '4. "Common problems and complaints" (id: "s4")\n'
            '5. "Verdict" (id: "s5")\n'
            "For each section, write 1 concise, natural search query written the exact way a real buyer in India would search on Reddit, YouTube, Quora, Amazon, or Flipkart.\n"
            "Return ONLY valid JSON matching this exact schema:\n"
            '{"sections": [{"id": "s1", "title": "Products and prices in India", "questions": ["buyer search query"]}]}'
        )
        fallback = _fallback_domestic_plan(topic)
    else:
        system_prompt = (
            "You are Apollo, the lead research planner in a multi-agent research system.\n"
            "Break the user's research topic into 3 to 5 distinct, logical sections.\n"
            "For each section, write 2 concrete, search-engine-friendly questions/queries that will retrieve factual, high-credibility sources.\n"
            "Return ONLY valid JSON matching this exact schema:\n"
            '{"sections": [{"id": "s1", "title": "Section Title", "questions": ["search query 1", "search query 2"]}]}'
        )
        fallback = _fallback_plan(topic)

    user_prompt = f"Research Topic: {topic}\n\nReturn JSON only."
    raw_plan = await call_llm(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        json_mode=True,
        run_id=run_id,
        default_json=fallback,
        agent_name="Apollo",
        max_tokens=800,
    )

    sections_raw = raw_plan.get("sections", []) if isinstance(raw_plan, dict) else []
    if not isinstance(sections_raw, list) or len(sections_raw) == 0:
        sections_raw = fallback["sections"]

    validated_sections: List[Dict[str, Any]] = []
    for idx, sec in enumerate(sections_raw[:MAX_SECTIONS], start=1):
        if not isinstance(sec, dict):
            continue
        sec_id = str(sec.get("id") or f"s{idx}").strip()
        title = str(sec.get("title") or f"Section {idx}").strip()
        questions_raw = sec.get("questions") or []
        if not isinstance(questions_raw, list):
            questions_raw = [str(questions_raw)]
        max_q = 1 if is_domestic else 3
        questions = [str(q).strip() for q in questions_raw if str(q).strip()][:max_q]
        if not questions:
            questions = [f"{topic} {title}"]

        validated_sections.append(
            {
                "id": sec_id,
                "title": title,
                "questions": questions,
                "question_history": [{"query": q, "round": 1} for q in questions],
            }
        )

    if not validated_sections:
        validated_sections = fallback["sections"]
        for sec in validated_sections:
            sec["question_history"] = [{"query": q, "round": 1} for q in sec["questions"]]

    total_questions = sum(len(s["questions"]) for s in validated_sections)
    emit_event(
        run_id,
        "plan",
        "Apollo",
        f"Created research plan with {len(validated_sections)} sections and {total_questions} initial search queries.",
        {"sections": validated_sections},
    )

    return validated_sections
