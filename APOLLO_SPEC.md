\# APOLLO SPEC



\## What Apollo is

Apollo is a multi-agent deep research web app for the INNOVISTA hackathon (Problem Statement 01).

One research topic goes in. One fully cited report comes out.

Three agents work as one pipeline: Apollo (manager), Athena (searcher), Hermes (reviewer).

Apollo's signature: TRUST. Every claim is checked, every source is rated, and disagreements are shown openly.



\## The three signature features (what makes Apollo special)

1\. Truth Meter: after the report is written, every sentence that has a citation is checked against the text of the source it cites. Each sentence is marked SUPPORTED (green), PARTIAL (yellow) or UNSUPPORTED (red). The report shows an overall Trust Score = percent of checked sentences that are SUPPORTED.

2\. Both Sides: Hermes detects places where sources disagree (different numbers, opposite claims). These are shown in a "Both Sides" tab: the topic of disagreement, Side A with its sources, Side B with its sources, and a one-line note on why they might differ (different year, region, method).

3\. Source Quality badges: every source gets a credibility score from 0 to 100 computed IN PYTHON CODE (not by the LLM) from its domain and date. Sources below 35 are dropped before writing. Each source shows a badge: High (70+), Medium (50 to 69), Low (35 to 49).



\## Hackathon rules we must follow (judges check these)

\- Real data only. No hardcoded or pre-written findings or reports.

\- Planning, gap-check and STOP logic must be in Python code, not only in prompts.

\- Reports come only from retrieved sources, never from model memory.

\- The loop always stops: max rounds, max time, max researchers.

\- Failed or empty searches must never crash the run. Log a warning event and continue.

\- Every claim must point to a source that really contains it (Truth Meter does this).

\- No API keys in code. Use a .env file. Add .env to .gitignore.



\## Tech stack (fixed, do not change)

\- Backend: Python 3.11+, FastAPI, LangGraph, httpx, python-dotenv, pydantic, arxiv (python package), tavily-python, sse-starlette, uvicorn.

\- LLM: OpenRouter through its OpenAI-compatible API (openai python package with base\_url https://openrouter.ai/api/v1). Two models from .env: FAST\_MODEL (searchers, writers, truth checks) and SMART\_MODEL (Apollo planner, Hermes reviewer). Every LLM call that needs structure must return JSON and be parsed with a safe fallback.

\- Frontend: React + Vite + Tailwind CSS. Single page app. Dark theme.

\- Live updates: Server-Sent Events (SSE) from backend to frontend.

\- OS: Windows. Give Windows commands (PowerShell).



\## Folder structure

apollo/

&#x20; APOLLO\_SPEC.md

&#x20; backend/

&#x20;   main.py            (FastAPI app, routes, SSE)

&#x20;   graph.py           (LangGraph state machine)

&#x20;   agents/

&#x20;     apollo\_planner.py

&#x20;     athena\_search.py

&#x20;     hermes\_review.py

&#x20;     writer.py

&#x20;     truth\_meter.py

&#x20;   tools/

&#x20;     tavily\_tool.py

&#x20;     arxiv\_tool.py

&#x20;     source\_scoring.py

&#x20;     llm.py           (one helper to call OpenRouter, with retries and JSON parsing)

&#x20;   events.py          (event emitter used by all agents)

&#x20;   .env.example

&#x20;   requirements.txt

&#x20; frontend/

&#x20;   (Vite React app)

&#x20; README.md



\## Limits (constants in backend/graph.py)

MAX\_SECTIONS = 5

MAX\_REVIEW\_ROUNDS = 3

MAX\_PARALLEL\_RESEARCHERS = 5

RESULTS\_PER\_SEARCH = 5

RUN\_TIMEOUT\_SECONDS = 360

MIN\_SOURCE\_SCORE = 35



\## Pipeline (LangGraph nodes, in order)

1\. plan (Apollo): input topic. SMART\_MODEL returns JSON: {"sections": \[{"id": "s1", "title": "...", "questions": \["...", "..."]}]}. 3 to 5 sections. Emit event "plan".

2\. search (Athena): for every section, run searches IN PARALLEL with asyncio.gather (max MAX\_PARALLEL\_RESEARCHERS at once). Each question goes to Tavily. If the topic looks academic or scientific, also query arXiv (max 3 papers). Each result becomes a Source: {id, url, title, content (page text or abstract, max 4000 chars), published\_date, section\_id, domain}. Emit "search\_start" and "search\_result" per query. On error or empty result, emit "warning" and continue.

3\. score (code only): run source\_scoring.py on every new source. Drop sources below MIN\_SOURCE\_SCORE. Remove duplicate URLs. Emit "source\_scored" per source with score and badge.

4\. review (Hermes): code checks first (sections with fewer than 2 sources = gap, sources older than 3 years for fast-changing topics = outdated). Then SMART\_MODEL reads short summaries of each section's sources and returns JSON: {"complete": true/false, "gaps": \[{"section\_id": "...", "reason": "...", "follow\_up\_query": "..."}], "conflicts": \[{"topic": "...", "side\_a": {"claim": "...", "source\_ids": \[...]}, "side\_b": {"claim": "...", "source\_ids": \[...]}, "why\_different": "..."}]}. Emit "review", one "gap" event per gap and one "conflict" event per conflict.

5\. Decision in CODE (not prompt): if complete is false AND there are gaps AND round < MAX\_REVIEW\_ROUNDS AND time left, run follow-up searches for the gaps only (go back to search with only those queries), increment round, emit "round". Else go to write. Also stop if RUN\_TIMEOUT\_SECONDS is near.

6\. write: one writer call per section (FAST\_MODEL), in parallel, using ONLY that section's sources. Sources are numbered globally \[1], \[2]... Every factual sentence must end with a citation like \[3]. Then ONE final assembler call (SMART\_MODEL) that sees all sections and writes: intro, smooth sections, conclusion, and keeps all citations. Emit "writing" events.

7\. truth\_check (Truth Meter): split report into sentences. For each sentence with citations, take the cited sources' content. Batch per section: one FAST\_MODEL call returns JSON list \[{"sentence\_index": 0, "verdict": "SUPPORTED|PARTIAL|UNSUPPORTED", "evidence": "short quote from source or empty"}]. Compute trust\_score. Emit "truth\_check" progress and final "trust\_score".

8\. done: emit "done" with the full result: {topic, plan, sources, report\_markdown, sentences\_with\_verdicts, trust\_score, conflicts, rounds\_used, warnings, stats: {searches, sources\_kept, sources\_dropped, llm\_calls, seconds}}.



\## Source scoring rules (backend/tools/source\_scoring.py, pure Python)

Start at 50. Then:

\- Domain ends with .gov, .gov.in, .nic.in, .edu, .ac.in, or is who.int, worldbank.org, un.org, imf.org, rbi.org.in, pib.gov.in: +35

\- arxiv.org, nature.com, sciencedirect.com, springer.com, ieee.org, nih.gov, pubmed: +30

\- Reputed news (reuters.com, thehindu.com, indianexpress.com, livemint.com, economictimes.indiatimes.com, bbc.com, hindustantimes.com, downtoearth.org.in, business-standard.com): +20

\- wikipedia.org: +10

\- medium.com, blogspot.com, wordpress.com, quora.com, reddit.com: -10

\- Unknown domain with very short content (under 300 chars): -15

\- Published in last 2 years: +10. Older than 5 years: -10. Unknown date: 0.

Clamp to 0 to 100. Badge: High 70+, Medium 50 to 69, Low 35 to 49, Dropped below 35.

Return {score, badge, reasons: \[list of short strings explaining the score]}.



\## SSE events

Endpoint: POST /api/research with {"topic": "...", "max\_rounds": 3} returns {"run\_id"}.

Endpoint: GET /api/research/{run\_id}/stream streams events.

Every event: {"type": "...", "agent": "Apollo|Athena|Hermes|Writer|TruthMeter|System", "message": "human readable line", "data": {...}, "ts": "..."}.

Types: plan, search\_start, search\_result, warning, source\_scored, review, gap, conflict, round, writing, truth\_check, trust\_score, done, error.



\## Frontend screens (single page, dark theme, clean)

1\. Top bar: "Apollo" logo text + tagline "Research you can trust".

2\. Start panel: big topic input, max rounds slider (1 to 3), Start button, two example chips: "Why do Indian farmers still burn crop stubble, and which solutions are actually working?" and "Stubble burning policy in a single small village of Fatehgarh Sahib district 2026".

3\. Live run view (left 40%): timeline of events, each row with agent name color badge (Apollo blue, Athena green, Hermes orange, Writer purple, TruthMeter teal, System grey), message and time. Warnings in yellow, errors in red. Counters on top: Round x/3, Sources kept, Sources dropped, Searches, Elapsed time.

4\. Results (right 60%), tabs:

&#x20;  - Report: rendered markdown. Each cited sentence has a colored underline or background (green, yellow, red) from the Truth Meter. Hover shows verdict and evidence quote. Citations \[n] are clickable and scroll to the source. Big Trust Score card on top (for example "Trust Score 86%: 31 supported, 4 partial, 1 unsupported").

&#x20;  - Both Sides: one card per conflict. Topic as title. Two columns Side A and Side B, each with the claim and source chips. "Why they differ" line below. If none: "Sources agreed on all checked points."

&#x20;  - Sources: grouped by section. Each source shows title, domain, date, Quality badge (High green, Medium yellow, Low orange) with score, and reasons on hover. A separate collapsed list "Dropped sources" with their scores.

&#x20;  - Plan: the sections and questions Apollo made, and which round each follow-up came from.

5\. Export buttons: Download Markdown, Download PDF (use window.print with a print stylesheet that prints only the report, trust score and reference list).



\## Coding rules for the agent building this

\- Keep code simple and commented. The team cannot code by hand.

\- Never hardcode research content. Never fake events.

\- Wrap every external call (LLM, Tavily, arXiv) in try/except with a warning event.

\- LLM JSON parsing: strip code fences, try json.loads, on failure retry once with "Return valid JSON only", then fall back to a safe default.

\- Use the limits constants everywhere. Never loop without a cap.

\- After each phase, give exact PowerShell commands to run and test.

