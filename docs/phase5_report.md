# Phase 5 — MCP Tool Integration: Final Report

> **Status:** ✅ **COMPLETE & COMMITTED**
> **Commit:** `ab813b4` — authored by `madhumita <mahighosh149@gmail.com>` — pushed to `origin/main`
> **Date:** Aug 2026
> **Next:** Phase 6 — Safety & Trust Layer (entry criteria met; gaps listed in §7)

---

## 1. Executive Summary

Phase 5 added a **pluggable external-tool layer** to Charaka AI via the **Model Context Protocol (MCP)**. The agent now has a real, spawnable herb-safety tool (`charaka-herb-safety`) wired into the LangGraph safety-check node through `langchain-mcp-adapters`, and it demonstrably uses that tool when herbs are present in a query — not just vector retrieval alone.

Contrast with prior phases: Phases 1–4 built corpus → embeddings → agent pipeline → safety **within hardcoded lookup logic**. Phase 5 moves the safety layer out of the monolith into an **external, standard-protocol tool server**, while adding a **herb-aware fast path** across expansion, retrieval, safety, and synthesis so herb questions behave differently from generic condition questions.

**All Phase 5 deliverables are committed and pushed.** The eval harness now captures per-row herb/safety/source evidence, and a committed retrieval-mode run proves the MCP path end to end: **10/10 herb queries resolved their safety flags via `src:mcp`**.

---

## 2. Phase 5 Goal & Deliverables (vs. Plan)

| Phase 5 deliverable (plan) | Status | Where it lives |
|---|---|---|
| Build a small MCP server (herb-safety lookup) | ✅ **Done** | `backend/app/mcp_server.py` + `backend/reference/herb_safety.json` |
| Connect it into the LangGraph agent via `langchain-mcp-adapters` | ✅ **Done** | `backend/app/nodes/safety.py` |
| Test the agent correctly choosing MCP vs. retrieval-alone | ✅ **Done** | `backend/scripts/eval_run.py` + 8 new eval questions; evidence committed (see §6) |

---

## 3. What Was Built — File by File, and How

### 3.1 NEW — `backend/app/mcp_server.py` (the MCP server itself)

**How it's built:**
- A **FastMCP** server named `charaka-herb-safety`, run over **stdio transport** (`mcp.run(transport="stdio")` at `mcp_server.py:43`). stdio is the lightest transport and suits a subprocess-spawned, single-machine tool.
- **One tool:** `check_herb_safety(herb_name)` (`mcp_server.py:14`) with a docstring that tells the LLM when to use it ("whenever herbs are found in a query").
- **Data:** `reference/herb_safety.json` is loaded **once at import** into `SAFETY_DB` (`mcp_server.py:8-9`) — no per-call disk I/O.
- **Graceful miss:** unknown herb → `{"found": false, "message": "...Advise consulting a qualified Ayurvedic practitioner."}` (`mcp_server.py:27-32`) — the server **never fabricates** safety data.
- **Structured return:** contraindications, interactions, pregnancy_flag, dosha_caution (`mcp_server.py:33-40`).

### 3.2 NEW — `backend/reference/herb_safety.json` (the safety database)

**Verified contents:** **49 herb entries**, each with 8 fields:
`herb`, `contraindications`, `interactions`, `pregnancy_flag`, `dosha_caution`, `classical_source` (Charaka chapter/verse), `modern_source` (NCCIH / Ayurvedic Pharmacopoeia of India), `modern_source_verified` (**all 49 currently `false`** — see Phase 6 work).

Example, `ashwagandha` (live-tool output verified):
- Contraindications: autoimmune diseases, hyperthyroidism, surgery (>2 weeks)
- Interactions: sedative/CNS-depressant potentiation, thyroid-hormone interplay, etc.
- Pregnancy: **Avoid** — may cause uterine contractions
- Dosha caution + classical + modern sources recorded

### 3.3 MODIFIED — `backend/app/nodes/safety.py` (MCP integration, the core wiring)

**How it's done:**
1. **Spawn + connect:** `StdioServerParameters(command=sys.executable, args=[MCP_SERVER_SCRIPT])` + `stdio_client` + `ClientSession.initialize()` + `load_mcp_tools(session)` (`safety.py:71-77`).
   - *Note: the original code used bare `command="python"`, which resolves to the system interpreter (no `mcp` package). Fixed to `sys.executable` so the subprocess reuses the venv.*
2. **Async on a background thread:** the MCP session runs on a dedicated event loop in a daemon thread (`safety.py:39-45`), so the FastAPI request path never blocks.
3. **Crash resilience:** `_on_mcp_crash()` (`safety.py:119`) flips alive-flag off and schedules `_respawn_mcp()` on the background loop; respawn is rate-limited by a **30 s cooldown** (`RESPAWN_COOLDOWN`) and serialized by `RESPAWNING` lock.
4. **3-tier fallback chain** per herb (`safety.py:202-211`):
   1. **MCP tool** → `source="mcp"`
   2. **Direct JSON load** of the same file → `source="json_fallback"`
   3. **Legacy hardcoded** contraindications (guggulu–pregnancy, trikatu–acid reflux) → `source="legacy"`
5. **Flag builder** `_build_flags()` (`safety.py:170`) condenses pregnancy / contraindications / dosha / interactions into surfaceable strings.
6. **New state output** `safety_sources: {herb: source_tier}` — the seed of the Phase 6 source-tracking / reasoning trace.

### 3.4 MODIFIED — `backend/app/nodes/retriever.py` (herb-aware retrieval path)

**How it's done:**
- Builds regex `HERB_PATTERNS` from **all aliases** in `herbs.json` (96 herbs) (`retriever.py:31-35`).
- `_detect_herb(query)` (`retriever.py:64`): if a herb name/alias appears, **skip generic ChromaDB vector search** and use `_herb_retrieve()` (`retriever.py:71`):
  - Pull the verse IDs directly from the `herb_mentions.json` verse index (up to 10 candidates).
  - Rank by **numpy dot-product similarity** against the query embedding (`retriever.py:86-94`).
  - Return `top-3` with `confidence: "high"`.
- Non-herb path unchanged (embeddings + `mappings.json` metadata disambiguation; `high/low` from the `> 0.5` threshold at `retriever.py:143`).

### 3.5 MODIFIED — `backend/app/nodes/query_expansion.py` (herb-first expansion)

**How it's done:** Herb/canonical detection now runs **before** the generic condition-synonym map (`query_expansion.py:34-43`), so `canonical_term` resolves to the **herb name** (e.g. `ashwagandha`), making every downstream node herb-aware. Generic synonyms (diabetes→prameha, etc.) only apply when no herb is present.

### 3.6 MODIFIED — `backend/app/nodes/synthesis.py` (alias-aware answers)

**How it's done:**
- Builds a **HERB ALIASES block** from `herbs.json` (Sanskrit/Latin/English equivalences) injected into the prompt context (`synthesis.py:58-66`, `84`).
- New prompt rule: when an herb appears in context, **recognize and explain its alternate names** to the user (classical texts use different names for the same herb) (`synthesis.py:38`).

### 3.7 MODIFIED — `backend/app/state.py`

- Added `safety_sources: Optional[dict]` to `AgentState` (`state.py:15`).

### 3.8 MODIFIED — `backend/reference/eval_set.json` (20 → 28 questions)

Added **8 herb-focused questions** (`eval_21`–`eval_28`): ashwagandha (fever/cough), guggulu (skin/fever), turmeric (antidote), brahmi (skin/conception), shatavari (rejuvenator) — each with a **hand-verified verse ID** in the notes (e.g. `cs_sutra_4_11`, `cs_sharira_8_20`).

### 3.9 MODIFIED — `backend/scripts/eval_run.py` (Phase-5 eval evidence)

**How it's done:**
- Per-row capture of `herbs_found`, `safety_flags`, `safety_sources` (`eval_run.py:64-66`).
- **Safety coverage section**: `X/Y herb queries got flags` + `UNCOVERED` list (`eval_run.py:126-131`).
- **Source distribution** per query: `src:mcp=n, json=n, legacy=n` (`eval_run.py:103-110`).
- Fixed hardcoded `/20` percentages → dynamic `/total` (`eval_run.py:118-124`).

### 3.10 MODIFIED — `backend/requirements.txt`

- Added `mcp` and `langchain-mcp-adapters`.

### 3.11 MODIFIED — `README.md`

- Status badge + progress table → Phase 5 **Done**, Phase 6 **Next**, Phase 7 **Planned**.
- New "What's complete today" rows (MCP server, MCP wiring, herb-aware retrieval, herb-first expansion, alias-aware synthesis, safety DB, Phase 5 eval).
- Backend layout, tech stack, eval instructions updated.

---

## 4. How the Phase-5 Flow Works (end to end)

```
User query ("how is guggulu used for skin?")
   │
   ▼
[1] Emergency gate          — hardcoded RED_FLAGS; herbs are NOT emergencies → pass
   │
   ▼
[2] expand_query            — herb detected FIRST → canonical_term = "guggulu"
   │
   ▼
[3] retrieve                — herb path: skip vector search, jump to herb_mentions index
   │                          → top-3 verses, confidence="high"
   ▼
[4] safety: check_safety     — for each herb found:
   │                            MCP subprocess (sys.executable) → check_herb_safety(guggulu)
   │                            → flags + safety_sources["guggulu"] = "mcp"
   │                            (crash → json_fallback → legacy; never silent)
   ▼
[5] synthesize              — PRIMARY context + HERB ALIASES block + safety flags
   │                          → cited answer that also teaches alternate names
   ▼
   /ask response: answer, safety_flags, confidence, chapter
```

**Important nuance (agent "choosing" MCP vs. retrieval):** the tool-selection decision is made deterministically in the pipeline, not by an LLM emitting a tool call. The **herb detector** decides "herb present → herb-aware retrieval + MCP safety tool"; otherwise the generic retrieval-synthesis path runs. This is deliberate — it is cheaper, more reliable, and impossible to hallucinate a tool selection.

---

## 5. Verification Performed

| Check | Result |
|---|---|
| `mcp` + `FastMCP` import in venv | ✅ OK |
| `langchain-mcp-adapters` + `load_mcp_tools` import | ✅ OK |
| MCP server toolbox | ✅ 1 tool: `check_herb_safety` |
| Live tool call `check_herb_safety("ashwagandha")` via agent's own MCP client | ✅ `source="mcp"`, full contraindication/interaction JSON returned |
| Eval in `--mode retrieval` after `sys.executable` fix | ✅ `src:mcp` on **10/10** herb queries |
| `src:mcp` appears in committed eval output | ✅ (see §6) |
| Full commit + push | ✅ `ab813b4` by `madhumita` |

---

## 6. Committed Evaluation Evidence

Run: `python scripts/eval_run.py --mode retrieval` — **28 questions**, committed in the Phase-5 commit.

### 6.1 Retrieval & disambiguation accuracy

| Metric | Phase 3 baseline (20 Q) | Phase 5 (28 Q) |
|---|---|---|
| Resolved (top-1 equivalent) | 16/20 (80%) | **24/28 (85%)** |
| Top-3 | 17/20 (85%) | **25/28 (89%)** |
| False emergency positives | 0 | **0/28** |

### 6.2 Safety / MCP evidence

| Metric | Result |
|---|---|
| Herb queries detected | 10/10 |
| Herb queries that got safety flags | **10/10 (100%)** — 0 uncovered |
| Source tier used | **`src:mcp` for all 10** (0 json_fallback, 0 legacy in this run) |
| Sample source distribution | eval_21 ashwagandha `src:mcp=6`, eval_25 turmeric `src:mcp=5`, eval_26 brahmi `src:mcp=7` |

### 6.3 Remaining misses (known, documented)

| Eval | Expected | Resolved | Note |
|---|---|---|---|
| eval_10 | sutrasthana/1 | sutrasthana/27 | `conf=low` (correctly marked uncertain) |
| eval_18 | vimanasthana/1 | sutrasthana/26 | canonical=rasa disambiguation |
| eval_20 | sharirasthana/8 | vimanasthana/8 | canonical=prakriti, `conf=low` |
| eval_21 | chikitsasthana/3 | vimanasthana/8 | `conf=high` — worth reviewing in Phase 6/disagreement work |

> **Note:** `--mode full` (28 Groq end-to-end calls) is ready to run and is listed as a Phase-6 kick-off action (§8.1) so prompt-quality + safety-flag rendering can be scored.

---

## 7. Known Gaps & Risks Carried Into Phase 6

1. **Data completeness** — 48 of 96 herbs in `herbs.json` have **no** safety entry (`ajwain`, `bilva`, `cardamom`, `celery`, …). The MCP server and the `json_fallback` read the *same* file, so a fallback is **not** an independent source.
2. **Name mismatches** — e.g. `kustha` (herbs.json) vs `kushtha` (safety.json), `vasa` vs `vasaka`: these herbs silently land on `json_fallback`/no-flag. Needs a canonical-name reconciliation.
3. **No second-source verification** — every entry has `modern_source_verified: false`; Phase 1 collected NCCIH / AI-Pharmacopoeia data that must now be cross-checked.
4. **Binary confidence** — `high/low` at a 0.5 threshold; the herb path is always `"high"`. Phase 6 needs **numeric calibrated thresholding** + explicit "match uncertain" disclosure.
5. **No reasoning trace in `/ask`** — response exposes only `answer, is_emergency, confidence, chapter, safety_flags`. Phase 7's "show reasoning" toggle needs `retrieved`, `canonical_term`, `safety_sources`, and a step trace surfaced.
6. **No source-disagreement detection** — the `safety_sources` field exists but no logic yet compares classical vs. modern vs. safety-layer agreement.
7. **Subprocess lifetime** — MCP spawns one Python subprocess per FastAPI process; respawn is implemented but long-running-server + cold-start behavior hasn't been soak-tested.

---

## 8. Readiness for Phase 6

### 8.1 Phase 6 is ready to start because the plumbing already exists

| Phase 6 requirement (plan) | Phase 5 state → what unlocks it |
|---|---|
| Finalize **rule-based contraindication** table wired into the safety-checker tool | `herb_safety.json` + 3-tier fallback already wired into `check_herb_safety`; Phase 6 = **fill remaining 48 entries** + fix name mismatches, then flip `modern_source_verified` |
| **Retrieval-confidence thresholding** (low → explicit disclosure, never a guess) | `confidence` already flows through `AgentState` and the synthesis prompt ("If confidence is marked low, say the match is uncertain"); Phase 6 = swap `high/low` for **numeric score + calibrated bands** |
| **Source-disagreement flagging** | `safety_sources` dict is already populated per herb per query; Phase 6 = add comparison logic (classical vs. modern vs. safety disagreement → flag to user) |
| **Reasoning-trace output** (for the "show reasoning" UI toggle) | `retrieved`, `canonical_term`, `herbs_found`, `safety_flags`, `safety_sources` all exist in state; Phase 6 = expose the trace from `/ask` |

### 8.2 Recommended Phase 6 entry checklist

**Close out (quick, do on day 1):**
- [ ] Run `python scripts/eval_run.py --mode full` and commit the end-to-end (Groq) results
- [ ] Cross-check safety DB coverage: add the missing 48 herbs; rename `kushtha`→`kustha` / `vasa`→`vasaka` to canonical names
- [ ] Soak-test the MCP subprocess (long-running server, restart, cold start)

**Core Phase 6 work:**
- [ ] Complete & **cross-verify** all herb_safety entries against the NCCIH / Ayurvedic-Pharmacopoeia data collected in Phase 1; flip `modern_source_verified`
- [ ] Numeric retrieval-confidence bands (low → explicit "match uncertain")
- [ ] Source-disagreement detection + user-facing flag
- [ ] Reasoning-trace output exposed from `/ask` (Phase 7 dependency)

---

## 9. Commit / Attribution

- **Commit:** `ab813b4 — Phase 5: MCP tool integration with herb-safety server, herb-aware retrieval, and 28-question eval`
- **Author:** `madhumita <mahighosh149@gmail.com>`
- **Files:** 11 (2 new: `mcp_server.py`, `herb_safety.json`; 9 modified: `safety.py`, `retriever.py`, `query_expansion.py`, `synthesis.py`, `state.py`, `eval_set.json`, `eval_run.py`, `requirements.txt`, `README.md`)
- **Pushed to:** `origin/main` (`https://github.com/Madhu-204/Charaka-AI.git`)

_Report generated from verified live-state: git history, live MCP tool call, and a committed 28-question retrieval eval run._