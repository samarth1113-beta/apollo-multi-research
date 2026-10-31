# Apollo — Research you can trust

Multi-agent deep research web application built for the **INNOVISTA Hackathon (Problem Statement 01)**.
One research topic goes in. One fully cited, sentence-verified report comes out.

---

## Windows Setup Steps (PowerShell)

The repository includes the dependency manifests [backend/requirements.txt](backend/requirements.txt),
[frontend/package.json](frontend/package.json), and [frontend/package-lock.json](frontend/package-lock.json).
The `backend\venv`, `frontend\node_modules`, build output, and `.env` files are local generated files and
are intentionally excluded from Git.

### 1. Backend Setup
Open PowerShell in the project root (`apollo-PROJECT`) and run:

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Open `backend\.env` and set your keys and OpenRouter models:
- `OPENROUTER_API_KEY`: Your key from https://openrouter.ai/keys
- `TAVILY_API_KEY`: Your key from https://app.tavily.com
- `FAST_MODEL`: Fast model for section writing & Truth Meter (e.g. `openai/gpt-4o-mini` or `google/gemini-2.0-flash-001`)
- `SMART_MODEL`: Reasoning model for Apollo planning, Hermes gap/conflict review, and report assembly (e.g. `openai/gpt-4o` or `anthropic/claude-3.5-sonnet`)

### 2. Frontend Setup
Open a second PowerShell window in the project root (`apollo-PROJECT`) and run:

```powershell
cd frontend
npm ci
```

---

## How to Run

### Start Backend (Port 8000)
```powershell
cd backend
.\venv\Scripts\Activate.ps1
uvicorn main:app --reload --port 8000
```

### Start Frontend (Port 5173)
```powershell
cd frontend
npm run dev
```

Then open **http://localhost:5173** in your browser.

### Optional CLI Test Runner
```powershell
cd backend
.\venv\Scripts\Activate.ps1
python test_run.py "Why do Indian farmers still burn crop stubble, and which solutions are actually working?"
python test_run.py "Stubble burning policy in a single small village of Fatehgarh Sahib district 2026"
```

---

## Architecture in 10 Lines

1. **FastAPI + SSE Backend (`backend/main.py`, `events.py`)**: Starts asynchronous research runs (`POST /api/research`) and streams live agent events over Server-Sent Events (`GET /api/research/{run_id}/stream`).
2. **LangGraph State Machine (`backend/graph.py`)**: Orchestrates an 8-stage pipeline (`plan` → `search` → `score` → `review` → loop/stop → `write` → `truth_check` → `done`).
3. **Apollo Planner (`agents/apollo_planner.py`)**: Uses `SMART_MODEL` to decompose the topic into 3–5 sections with targeted search queries.
4. **Athena Searcher (`agents/athena_search.py`)**: Executes parallel Tavily web searches and arXiv academic paper queries bounded by `asyncio.Semaphore(MAX_PARALLEL_RESEARCHERS)`.
5. **Pure-Python Source Scorer (`tools/source_scoring.py`)**: Scores every source (`0–100`) by domain authority, content length, and recency, dropping sources below `35` and deduplicating URLs.
6. **Hermes Reviewer (`agents/hermes_review.py`)**: Runs deterministic Python coverage/recency checks first, then uses `SMART_MODEL` to identify missing evidence gaps and "Both Sides" source conflicts.
7. **Deterministic Loop Control (`backend/graph.py`)**: Pure Python conditional edge enforces `MAX_REVIEW_ROUNDS` (3) and `RUN_TIMEOUT_SECONDS` (360s) before looping back to search only for remaining gaps.
8. **Parallel Section Writers + Assembler (`agents/writer.py`)**: Drafts each section in parallel (`FAST_MODEL`) using strictly that section's globally numbered `[n]` sources, then assembles a cohesive report (`SMART_MODEL`).
9. **Truth Meter Verifier (`agents/truth_meter.py`)**: Splits the report into sentences, checks every cited sentence against its cited source text (`FAST_MODEL` + code check for valid IDs), and computes the overall Trust Score.
10. **React + Vite + Tailwind Dark UI (`frontend/src/App.jsx`)**: Displays the live SSE timeline and counters alongside interactive Report, Both Sides, Sources, and Plan tabs with Markdown/PDF export.

---

## The Three Signature Features

1. **Truth Meter (Sentence-Level Citation Verification)**:
   Every cited sentence in the final report is checked against the actual retrieved text of the source(s) it cites and marked `SUPPORTED` (green), `PARTIAL` (yellow), or `UNSUPPORTED` (red) with an extracted evidence quote on hover and an overall **Trust Score** percentage.
2. **Both Sides (Open Disagreement Detection)**:
   Hermes actively detects places where verified sources disagree (different numbers/percentages, opposite claims, or differing years/regions/methods) and presents Side A vs. Side B comparison cards with clickable source chips and a *"Why they differ"* explanation.
3. **Deterministic Source Quality Badges**:
   Every source receives a credibility score (`0–100`) computed purely in Python code from its domain category (`.gov`/`.edu`/WHO/UN/RBI/PIB, peer-reviewed journals, reputed news, Wikipedia, blogs/forums), content length, and publication recency — badged as **High (`70+`)**, **Medium (`50–69`)**, or **Low (`35–49`)**, while sources below `35` are dropped before writing.

---

## Future Ideas

- **Judge Mode**: Allow users or domain experts to upvote/override sentence verdicts and re-weight source credibility rules interactively.
- **Debate Mode**: Pit two specialized agents against each other on controversial topics, each defending one side using verified citations before a synthesis judge writes the conclusion.
- **More Domains**: Add specialized connectors for **Finance** (SEC/NSE filings, market data) and **Product Comparison** (synthesizing real user reviews from YouTube transcripts and Reddit threads).
- **API Key Screen in UI**: Provide an encrypted local settings modal in the web UI so users can paste or switch OpenRouter/Tavily keys and models without editing `.env`.
- **Hindi Reports**: One-click bilingual/Hindi report generation (`हिन्दी`) while preserving exact `[n]` source citations and Truth Meter highlights.
- **Run History**: Persist past research runs in local storage / SQLite so users can revisit, compare, and re-export previous reports anytime.
