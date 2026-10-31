"""
Truth Meter Agent (backend/agents/truth_meter.py).
Pipeline Step 7 from APOLLO_SPEC.md:
- Split the final report into sentences (keeping markdown headings out).
- For each sentence with [n] citations, collect the cited sources' content.
- If any cited source ID does not exist in verified sources, mark UNSUPPORTED automatically in code.
- Batch by section: one FAST_MODEL call per section batch returning JSON list:
  [{"sentence_index": 0, "verdict": "SUPPORTED|PARTIAL|UNSUPPORTED", "evidence": "short quote from source or empty"}]
- Compute overall trust_score = percent of checked sentences that are SUPPORTED.
- Emit "truth_check" progress events and final "trust_score" event.
"""
import asyncio
import re
from typing import Any, Dict, List, Tuple

from events import emit_event
from tools.llm import call_llm, get_fast_model

CITATION_GROUP_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


def extract_citations_from_sentence(sentence: str) -> List[int]:
    """Extract all unique integer citation IDs from `[1]`, `[2, 3]`, etc. in a sentence."""
    ids: List[int] = []
    for match in CITATION_GROUP_RE.finditer(sentence):
        raw_nums = match.group(1).split(",")
        for num_str in raw_nums:
            num_str = num_str.strip()
            if num_str.isdigit():
                val = int(num_str)
                if val not in ids:
                    ids.append(val)
    return ids


def split_paragraph_into_sentences(text: str) -> List[str]:
    """
    Split a paragraph or list item into individual sentences while keeping trailing
    citations like `... text. [1]` or `... text [1].` attached to their sentence.
    """
    cleaned = text.strip()
    if not cleaned:
        return []

    # Split on sentence-ending punctuation followed by whitespace and a capital letter,
    # keeping trailing [n] citations attached to the preceding sentence.
    parts = re.split(
        r"(?<=[.!?])(?:\s*(?:\[\d+(?:\s*,\s*\d+)*\])+)?\s+(?=[A-Z0-9\"'(\[])",
        cleaned,
    )
    # Wait: re.split with non-capturing group drops the matched separator if not careful!
    # Instead, let's use re.findall or a regex that matches each full sentence + its trailing citations.
    pattern = re.compile(
        r"[^.!?]+[.!?]+(?:\s*\[\d+(?:\s*,\s*\d+)*\])*\.*|[^.!?]+$"
    )
    sentences = [m.group(0).strip() for m in pattern.finditer(cleaned) if m.group(0).strip()]
    return sentences if sentences else [cleaned]


def extract_sections_and_cited_sentences(
    report_markdown: str,
) -> List[Dict[str, Any]]:
    """
    Parse markdown into sections (excluding headings themselves from sentence checks)
    and collect all sentences that contain at least one [n] citation.
    Returns a list of section batches:
    [{"section_title": "...", "sentences": [{"sentence_index": int, "sentence": str, "citations": [int]}]}]
    """
    lines = (report_markdown or "").splitlines()
    sections: List[Dict[str, Any]] = []
    current_section = {"section_title": "Introduction", "sentences": []}
    sections.append(current_section)

    global_idx = 0

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        # Keep headings and markdown table rows out of sentence checks
        if line.startswith("#"):
            heading_title = line.lstrip("#").strip()
            if heading_title:
                current_section = {"section_title": heading_title, "sentences": []}
                sections.append(current_section)
            continue

        if line.startswith("|") and line.endswith("|"):
            continue

        # Strip leading bullet or numbered list marker for clean sentence extraction
        body_line = re.sub(r"^(?:[-*+]|\d+\.)\s+", "", line).strip()
        if not body_line:
            continue

        for sent in split_paragraph_into_sentences(body_line):
            cites = extract_citations_from_sentence(sent)
            if not cites:
                continue
            current_section["sentences"].append(
                {
                    "sentence_index": global_idx,
                    "section_title": current_section["section_title"],
                    "sentence": sent,
                    "citations": cites,
                }
            )
            global_idx += 1

    return [sec for sec in sections if len(sec["sentences"]) > 0]


def _lexical_fallback_verdict(
    sentence: str,
    cited_sources: List[Dict[str, Any]],
) -> Tuple[str, str]:
    """
    Pure Python fallback verifier used only if the LLM call fails or returns invalid JSON.
    Checks word overlap between the claim sentence and the cited sources' real text,
    and extracts the closest sentence from the source as the evidence quote.
    """
    claim_clean = CITATION_GROUP_RE.sub("", sentence).lower()
    claim_words = [
        w for w in re.findall(r"[a-z0-9]{4,}", claim_clean)
        if w not in {"this", "that", "with", "from", "have", "been", "were", "their", "which", "while"}
    ]
    if not claim_words or not cited_sources:
        return "UNSUPPORTED", ""

    best_quote = ""
    best_overlap = 0.0

    for src in cited_sources:
        content = (src.get("content") or "").strip()
        if not content:
            continue
        src_sentences = re.split(r"(?<=[.!?])\s+", content)
        for s_sent in src_sentences:
            s_low = s_sent.lower()
            matched = sum(1 for w in claim_words if w in s_low)
            ratio = matched / max(1, len(claim_words))
            if ratio > best_overlap:
                best_overlap = ratio
                best_quote = s_sent.strip()[:240]

    if best_overlap >= 0.35:
        return "SUPPORTED", best_quote
    if best_overlap >= 0.15:
        return "PARTIAL", best_quote
    return "UNSUPPORTED", best_quote


async def _verify_section_batch(
    section_batch: Dict[str, Any],
    source_map: Dict[int, Dict[str, Any]],
    run_id: str,
) -> List[Dict[str, Any]]:
    """
    Verify one section's cited sentences.
    - Sentences citing any non-existent source ID are marked UNSUPPORTED in code automatically.
    - Remaining sentences in the section are checked in ONE FAST_MODEL call.
    """
    sec_title = section_batch["section_title"]
    items = section_batch["sentences"]

    emit_event(
        run_id,
        "truth_check",
        "TruthMeter",
        f"Checking {len(items)} cited sentence(s) in section '{sec_title}'...",
        {"section": sec_title, "count": len(items)},
    )

    code_verdicts: Dict[int, Dict[str, Any]] = {}
    llm_items: List[Dict[str, Any]] = []
    referenced_source_ids: List[int] = []

    for item in items:
        s_idx = item["sentence_index"]
        cites = item["citations"]
        missing_ids = [cid for cid in cites if cid not in source_map]

        # Pure Python rule: if a cited source ID does not exist, mark UNSUPPORTED automatically in code
        if missing_ids:
            code_verdicts[s_idx] = {
                "sentence_index": s_idx,
                "section": sec_title,
                "sentence": item["sentence"],
                "citations": cites,
                "verdict": "UNSUPPORTED",
                "evidence": f"Cited source ID(s) {missing_ids} do not exist in verified sources.",
            }
        else:
            llm_items.append(item)
            for cid in cites:
                if cid not in referenced_source_ids:
                    referenced_source_ids.append(cid)

    if not llm_items:
        return [code_verdicts[item["sentence_index"]] for item in items]

    # Build source context for this section batch
    source_blocks = []
    for cid in referenced_source_ids:
        src = source_map[cid]
        source_blocks.append(
            f"SOURCE [{cid}] ({src.get('title', '')} - {src.get('domain', '')}):\n"
            f"{(src.get('content') or '')[:2500]}"
        )
    sources_text = "\n\n---\n\n".join(source_blocks)

    sentences_payload = [
        {
            "sentence_index": item["sentence_index"],
            "sentence": item["sentence"],
            "cited_sources": item["citations"],
        }
        for item in llm_items
    ]

    system_prompt = (
        "You are Apollo's Truth Meter, a strict fact-verification agent.\n"
        "For each sentence in the input list, compare its factual claim against the text of the SOURCE [n] it cites.\n"
        "Assign one of three verdicts:\n"
        "- SUPPORTED: The core factual claims and numbers in the sentence are directly supported by the cited source text.\n"
        "- PARTIAL: Part of the sentence is in the cited source, but some detail or nuance is extrapolated or incomplete.\n"
        "- UNSUPPORTED: The cited source text does not contain or contradicts the claim.\n\n"
        "Also extract a short exact quote (`evidence`, 1 sentence max) from the cited source that supports or relates to the claim (or empty string if UNSUPPORTED).\n"
        "Return ONLY a valid JSON list matching this exact schema:\n"
        '[{"sentence_index": 0, "verdict": "SUPPORTED", "evidence": "short quote from source or empty"}]'
    )
    user_prompt = (
        f"Section: {sec_title}\n\n"
        f"Cited Sources Content:\n{sources_text}\n\n"
        f"Sentences to Verify:\n{sentences_payload}\n\n"
        "Return JSON list only."
    )

    raw_verdicts = await call_llm(
        model=get_fast_model(),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        json_mode=True,
        run_id=run_id,
        default_json=None,
        agent_name="TruthMeter",
        max_tokens=800,
    )

    # Allow either a list `[...]` or `{"verdicts": [...]}`
    parsed_list: List[Dict[str, Any]] = []
    if isinstance(raw_verdicts, list):
        parsed_list = raw_verdicts
    elif isinstance(raw_verdicts, dict):
        for key in ("verdicts", "results", "sentences", "items"):
            if isinstance(raw_verdicts.get(key), list):
                parsed_list = raw_verdicts[key]
                break

    llm_verdict_map: Dict[int, Dict[str, Any]] = {}
    for entry in parsed_list:
        if not isinstance(entry, dict):
            continue
        idx_val = entry.get("sentence_index")
        if idx_val is None or not str(idx_val).isdigit():
            continue
        verdict_str = str(entry.get("verdict") or "").upper().strip()
        if verdict_str not in ("SUPPORTED", "PARTIAL", "UNSUPPORTED"):
            continue
        evidence_str = str(entry.get("evidence") or "").strip()
        llm_verdict_map[int(idx_val)] = {
            "verdict": verdict_str,
            "evidence": evidence_str,
        }

    # Combine results in original sentence order
    batch_results: List[Dict[str, Any]] = []
    for item in items:
        s_idx = item["sentence_index"]
        if s_idx in code_verdicts:
            batch_results.append(code_verdicts[s_idx])
            continue

        cites = item["citations"]
        cited_objs = [source_map[cid] for cid in cites if cid in source_map]

        if s_idx in llm_verdict_map:
            v_info = llm_verdict_map[s_idx]
            verdict = v_info["verdict"]
            evidence = v_info["evidence"]
            # If LLM left evidence blank on SUPPORTED/PARTIAL, grab a real quote from the source
            if not evidence and verdict in ("SUPPORTED", "PARTIAL"):
                _, fallback_quote = _lexical_fallback_verdict(item["sentence"], cited_objs)
                evidence = fallback_quote
        else:
            verdict, evidence = _lexical_fallback_verdict(item["sentence"], cited_objs)

        batch_results.append(
            {
                "sentence_index": s_idx,
                "section": sec_title,
                "sentence": item["sentence"],
                "citations": cites,
                "verdict": verdict,
                "evidence": evidence,
            }
        )

    return batch_results


async def run_truth_meter(
    report_markdown: str,
    sources: List[Dict[str, Any]],
    run_id: str,
) -> Dict[str, Any]:
    """
    Execute Truth Meter verification across the assembled report.
    Batches cited sentences by section, runs FAST_MODEL checks in parallel,
    computes trust_score, and emits 'truth_check' and 'trust_score' events.
    """
    source_map: Dict[int, Dict[str, Any]] = {}
    for s in sources:
        sid = s.get("id")
        if sid is not None and str(sid).isdigit():
            source_map[int(sid)] = s

    section_batches = extract_sections_and_cited_sentences(report_markdown)
    total_sentences = sum(len(b["sentences"]) for b in section_batches)

    if total_sentences == 0:
        emit_event(
            run_id,
            "truth_check",
            "TruthMeter",
            "No cited sentences found in report to verify.",
            {"checked_sentences": 0},
        )
        emit_event(
            run_id,
            "trust_score",
            "TruthMeter",
            "Trust Score: 0% (0 cited sentences checked).",
            {
                "trust_score": 0,
                "supported": 0,
                "partial": 0,
                "unsupported": 0,
                "total": 0,
            },
        )
        return {
            "report_markdown": report_markdown,
            "sentences_with_verdicts": [],
            "trust_score": 0,
        }

    emit_event(
        run_id,
        "truth_check",
        "TruthMeter",
        f"Starting Truth Meter verification on {total_sentences} cited sentence(s) across {len(section_batches)} section(s)...",
        {"total_sentences": total_sentences, "sections": len(section_batches)},
    )

    batch_tasks = [
        _verify_section_batch(batch, source_map, run_id)
        for batch in section_batches
    ]
    batch_outputs = await asyncio.gather(*batch_tasks)

    all_verdicts: List[Dict[str, Any]] = []
    for bout in batch_outputs:
        all_verdicts.extend(bout)

    all_verdicts.sort(key=lambda x: x["sentence_index"])

    supported_count = sum(1 for v in all_verdicts if v["verdict"] == "SUPPORTED")
    partial_count = sum(1 for v in all_verdicts if v["verdict"] == "PARTIAL")
    unsupported_count = sum(1 for v in all_verdicts if v["verdict"] == "UNSUPPORTED")
    total_checked = len(all_verdicts)

    trust_score = round((supported_count * 100.0) / total_checked) if total_checked > 0 else 0

    emit_event(
        run_id,
        "trust_score",
        "TruthMeter",
        (
            f"Trust Score {trust_score}%: {supported_count} supported, "
            f"{partial_count} partial, {unsupported_count} unsupported "
            f"(out of {total_checked} checked sentences)."
        ),
        {
            "trust_score": trust_score,
            "supported": supported_count,
            "partial": partial_count,
            "unsupported": unsupported_count,
            "total": total_checked,
        },
    )

    return {
        "report_markdown": report_markdown,
        "sentences_with_verdicts": all_verdicts,
        "trust_score": trust_score,
    }
