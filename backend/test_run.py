"""
CLI Runner to test the Apollo LangGraph pipeline from the command line (backend/test_run.py).
Usage:
    python test_run.py "Why do Indian farmers still burn crop stubble, and which solutions are actually working?"
"""
import asyncio
import sys
import uuid
from typing import Any, Dict

from dotenv import load_dotenv

from events import init_run_events
from graph import MAX_REVIEW_ROUNDS, execute_research_run

# Ensure UTF-8 console output on Windows PowerShell
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()


def print_event(event: Dict[str, Any]) -> None:
    """Callback that prints every emitted event live to the console."""
    etype = event.get("type", "info").upper()
    agent = event.get("agent", "System")
    msg = event.get("message", "")
    ts = (event.get("ts") or "")[11:19]
    print(f"[{ts}] [{agent:<10} | {etype:<13}] {msg}", flush=True)


async def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python test_run.py "<research topic>" [max_rounds]')
        sys.exit(1)

    topic = sys.argv[1]
    max_rounds = int(sys.argv[2]) if len(sys.argv) >= 3 and sys.argv[2].isdigit() else MAX_REVIEW_ROUNDS
    judge_mode = "--judge" in sys.argv
    run_id = f"cli-{uuid.uuid4().hex[:8]}"

    print("=" * 80)
    print(f"APOLLO CLI TEST RUN  (run_id={run_id}, max_rounds={max_rounds}, judge_mode={judge_mode})")
    print(f"Topic: {topic}")
    print("=" * 80)

    init_run_events(run_id, on_event=print_event)
    result = await execute_research_run(
        run_id=run_id,
        topic=topic,
        max_rounds=max_rounds,
        judge_mode=judge_mode,
    )

    print("\n" + "=" * 80)
    print("FINAL REPORT MARKDOWN")
    print("=" * 80)
    print(result.get("report_markdown", "(No report generated)"))

    print("\n" + "=" * 80)
    print("RUN SUMMARY STATS")
    print("=" * 80)
    stats = result.get("stats", {})
    print(f"Rounds Used     : {result.get('rounds_used')}")
    print(f"Searches Run    : {stats.get('searches')}")
    print(f"Sources Kept    : {stats.get('sources_kept')}")
    print(f"Sources Dropped : {stats.get('sources_dropped')}")
    print(f"Trust Score     : {result.get('trust_score')}% ({len(result.get('sentences_with_verdicts', []))} sentences checked)")
    print(f"Conflicts Found : {len(result.get('conflicts', []))}")
    print(f"Warnings Count  : {len(result.get('warnings', []))}")
    print(f"LLM Calls       : {stats.get('llm_calls')}")
    print(f"Elapsed Seconds : {stats.get('seconds')}s")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
