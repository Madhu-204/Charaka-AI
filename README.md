# 🌿 Charaka AI

> **Agentic RAG over the Charaka Samhita** — grounded, cited, safety-checked answers for general wellness, straight from classical Ayurvedic texts.

<div align="center">

![Status](https://img.shields.io/badge/status-Phase%207%20%E2%80%94%20Interactive%20Frontend-f59e0b)
![Corpus](https://img.shields.io/badge/Corpus-20%20Chapters%20%E2%80%A2%202%2C490%20Verses-3b82f6)
![License](https://img.shields.io/badge/license-Custom-gray)
![AI](https://img.shields.io/badge/AI-Agentic%20RAG-f59e0b)

</div>

---

## 🧭 Overview

**Charaka AI** is an **Agentic Retrieval-Augmented Generation (Agentic RAG)** system that answers general-wellness questions using classical Ayurvedic texts as its grounded knowledge source.

It is **not** a chatbot that "knows Ayurveda" from an LLM's training data. Every answer is:

- 🔎 **Retrieved** from real, curated texts
- 📚 **Cited** — traceable back to a specific chapter & verse
- 🛡️ **Safety-checked** before it reaches the user
- 🎯 **Clearly scoped** to what a piece of software can responsibly offer

### ⚠️ What it is *not*

A diagnostic tool, a doctor replacement, or a system that handles emergencies, chronic conditions, pediatrics, mental health, or anything surgical.

---

## 🎯 Problem It Solves

Ayurvedic knowledge today is **scattered, inconsistent, and hard to search** — people rely on unsourced blogs or videos for remedy advice, with:

- ❌ No citation
- ❌ No safety checking
- ❌ No way to verify a claim traces back to an actual text

**Charaka AI** replaces confident-sounding guesses with **grounded, cited, safety-checked answers** — every claim verifiable against a real source.

---

## 📦 Scope — What the Agent Covers

### ✅ In scope *(Kayachikitsa / Rasayana — internal medicine & general wellness)*

| Area | Examples |
|------|----------|
| 🍽️ **Digestive health** | Bloating, acidity, mild indigestion, appetite, occasional constipation |
| 😴 **Sleep quality** | Insomnia tendencies, sleep hygiene & routines |
| ⚡ **Energy & immunity** | General vitality, immunity support |
| 🧘 **Everyday stress** | Stress & restlessness *(not clinical mental health)* |
| 💆 **Skin & hair** | Minor, non-pathological concerns |
| 🤧 **Seasonal ailments** | Common cold, mild congestion/cough |
| 🦴 **Joint & muscle** | Minor stiffness *(non-injury, non-chronic)* |
| ⚖️ **Metabolism & lifestyle** | General weight/lifestyle guidance |
| 🌸 **Menstrual support** | General discomfort / PMS lifestyle support |
| 📅 **Seasonal routine** | *Ritucharya* guidance |
| 👁️ **ENT / eyes** | Mild eye strain, general ENT lifestyle tips |

### ❌ Out of scope *(hardcoded exclusions — always redirected to a doctor)*

- 🚨 **Any emergency symptom** — chest pain, breathing difficulty, severe bleeding, stroke signs, loss of consciousness, suicidal ideation
- 🩺 **Chronic or diagnosed conditions** already under medical treatment
- 👶 **Pediatrics, pregnancy-specific care, reproductive health conditions**
- 🧠 **Mental health diagnoses** — anxiety, depression, etc.
- 🔪 **Anything surgical (*Shalya Tantra*)** — excluded from the corpus entirely
- ⚠️ **Worsening or persistent symptoms** — redirected regardless of category

> These exclusions are **hardcoded** — the agent cannot be talked into answering them.

---

## 🚧 Project Progress

<div align="center">

| Phase | What it does | Status |
|-------|--------------|--------|
| **1** | Data collection — raw text curation | ✅ **Done** |
| **2** | Data processing & structuring | ✅ **Done** |
| **3** | Retrieval & RAG pipeline | ✅ **Done** |
| **4** | Agentic reasoning & safety guardrails | ✅ **Done** |
| **5** | MCP tool integration & herb-safety layer | ✅ **Done** |
| **6** | Safety & trust layer (source verification) | ✅ **Done** |
| **7** | Interactive frontend | 🔄 **In progress** |

</div>

### ✅ What's complete today

| Component | Detail | Status |
|-----------|--------|--------|
| 📖 **Corpus** | **20 chapters across 4 Sthanas** of the Charaka Samhita | ✅ |
| 🗂️ **Manifest** | `manifest.json` tracks every chapter, parts & verse counts | ✅ |
| 🧹 **Cleaning pipeline** | `scripts/transform.py` — strips HTML, fixes OCR typos, removes labels | ✅ |
| 🧬 **Herb extraction** | 100+ herb entries w/ aliases matched per verse → `herb_mentions.json` | ✅ |
| 🏷️ **Tagging** | Every verse tagged with `traditional_condition` + `category_tag` | ✅ |
| 🔎 **ID normalization** | Stable `cs_<sthana>_<chapter>_<verse>` IDs w/ dedup | ✅ |
| ✅ **Audit** | `scripts/audit_ids.py` — verifies 1:1 verse↔record mapping | ✅ |
| 🎯 **Reference sets** | `eval_set.json`, `herbs.json`, `mappings.json`, `typo_fixes.json` | ✅ |
| 🔎 **Vector store** | 2,490 verse embeddings (`all-MiniLM-L6-v2`) → `chroma_db` | ✅ |
| 📊 **Eval baseline** | Phase 3: Top-1 **16/20 (80%)** · Top-3 **17/20 (85%)** · naive keyword hybrid rejected (13/20) | ✅ |
| 🤖 **Agent pipeline** | LangGraph: emergency gate → query expansion → top-3 retrieval + `mappings.json` disambiguation → safety check → cited synthesis | ✅ |
| 🧠 **LLM synthesis** | Groq `openai/gpt-oss-120b`, citation-forcing prompt, verse-level citations, honesty on low confidence | ✅ |
| 🛡️ **Safety** | `herb_mentions.json` direct lookup + contraindication flags before remedies | ✅ |
| 🚨 **Emergency gate** | Hardcoded, non-LLM RED_FLAGS w/ informational-query downgrade (cannot be talked into answering) | ✅ |
| 🔌 **API** | `POST /ask` FastAPI endpoint w/ CORS | ✅ |
| 📊 **Phase 4 eval** | Resolved **17/20 (85%)** · Top-3 **17/20 (85%)** · **0** false emergency positives | ✅ |
| 🧩 **MCP server** | FastMCP `charaka-herb-safety` over stdio — `check_herb_safety(herb_name)` tool | ✅ |
| 🔗 **MCP wiring** | LangGraph safety check spawns MCP subprocess via `langchain-mcp-adapters` w/ crash-respawn & 3-tier fallback (`mcp` → `json_fallback` → `legacy`) | ✅ |
| 🌿 **Herb-aware retrieval** | Herb/alias detection skips generic vector search → direct herb-mention index lookup, ranked by similarity, `confidence: high` | ✅ |
| 🧬 **Herb-first expansion** | `canonical_term` resolves to the herb name so downstream is herb-aware | ✅ |
| 🗣️ **Alias-aware synthesis** | Prompt includes herb Sanskrit/Latin/English aliases so answers explain alternate names | ✅ |
| 🔍 **Safety DB** | `herb_safety.json` — **92 entries** w/ contraindications, interactions, pregnancy flag, dosha caution. File coverage **93/93** herbs, but **runtime-reachable ≈ 70/92** (a herb is reachable only if an ingested verse mentions it) — remaining 22 are alias-gap or corpus-scope gaps tracked by `audit_safety_coverage.py` | ✅ (data) · 🔄 (reachability) |
| 📊 **Phase 5 eval** | 28 Qs (8 new herb-focused) · Resolved **24/28 (85%)** · Top-3 **25/28 (89%)** · **0** false positives · **10/10** herb queries safety-covered | ✅ |

### 📊 Corpus breakdown

<details>
<summary><b>2,490 verses · 20 chapters · 4 Sthanas</b> — click to expand</summary>

**Sutra Sthana** — general principles, daily & seasonal routine *(984 verses / 10 chapters)*
- ch.1 Deerghanjiviteeya • ch.4 Shadvirechanashatashritiya • ch.5 Matrashiteeya • ch.6 Tasyashiteeya • ch.7 Naveganadharaniya • ch.12 Vatakalakaliya • ch.20 Maharoga • ch.25 Yajjahpurushiya • ch.26 Atreyabhadrakapyiya • ch.27 Annapanavidhi

**Vimana Sthana** — diagnosis & measurement *(348 verses / 2 chapters)*
- ch.1 Rasa Vimana • ch.8 Rogabhishagjitiya

**Sharira Sthana** — body constitution *(115 verses / 1 chapter)*
- ch.8 Jatisutriya

**Chikitsa Sthana** — therapeutics *(1,043 verses / 7 chapters)*
- ch.3 Jwara (fever) • ch.6 Prameha (metabolic disorders) • ch.7 Kushtha (skin) • ch.15 Grahani (digestion) • ch.17 Hikka-Shwasa (respiratory) • ch.18 Kasa (cough) • ch.28 Vatavyadhi (vata disorders)

</details>

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         User Query                          │
└───────────────────────────┬─────────────────────────────────┘
                            │
                    ┌───────▼────────┐
                    │  Safety Gate   │◄── emergency / OOS → doctor redirect
                    └───────┬────────┘
                            │
                    ┌───────▼────────┐      ┌───────────────────────┐
                    │     Agent      │──────►  Retrieval (RAG)      │
                    │   reasoning    │      │  └─ verse store        │
                    └───────┬────────┘      │  └─ herb index         │
                            │               └───────────────────────┘
                    ┌───────▼────────┐
                    │  Citation +    │
                    │  Scoped reply  │
                    └────────────────┘
```

**Backend layout**

```
backend/
├── app/                  # Agent — LangGraph + FastAPI
│   ├── state.py          #   AgentState TypedDict (+ safety_sources trace)
│   ├── nodes/            #   emergency · query_expansion · retriever · safety · synthesis
│   ├── graph.py          #   StateGraph wiring
│   ├── mcp_server.py     #   FastMCP charaka-herb-safety server (stdio)
│   └── main.py           #   POST /ask FastAPI endpoint
├── charaka_data/          # curated source corpus (JSON per chapter)
│   ├── 01_sutra_sthana/
│   ├── 02_vimana_sthana/
│   ├── 03_sharira_sthana/
│   ├── 04_chikitsa_sthana/
│   └── manifest.json
├── reference/             # herbs, mappings, typo fixes, eval set, herb_safety.json
├── scripts/               # transform.py · audit_ids.py · eval_run.py
├── processed/             # regenerable structured output (git-ignored)
├── chroma_db/             # regenerable vector store (git-ignored)
└── .env                   # GROQ_API_KEY (git-ignored)
```

---

## 🛠️ Tech Stack

`Python` · `JSON` · `LangGraph` · `ChromaDB` · `SentenceTransformers` · `Groq` · `FastAPI` · `MCP` · `langchain-mcp-adapters`

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+

### Data pipeline

```bash
cd backend
python scripts/transform.py      # raw corpus → processed/ structured JSON
python scripts/audit_ids.py      # verify 1:1 verse↔record integrity
```

### Run the agent

```bash
cd backend
python -m venv .venv                     # once
# Windows: .venv\Scripts\activate · macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt          # once  (includes mcp + langchain-mcp-adapters)
copy .env.example .env                   # then set GROQ_API_KEY (never commit)
uvicorn app.main:app --reload
```

Try it:

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"query": "I have bloating and poor appetite"}'
```

### Regression eval

```bash
python scripts/eval_run.py --mode retrieval   # free — retrieval/disambiguation only (28 Qs)
python scripts/eval_run.py --mode full        # 28 Groq calls — end-to-end answers
```

- Emergency phrases short-circuit before any retrieval or LLM call.
- Safety flags surface before remedies; herbs resolved by direct `verse_id` lookup.
- Herb queries invoke the MCP `check_herb_safety` tool, falling back gracefully to a local JSON lookup if the MCP subprocess cannot start.
- Citations are verse-traceable (`cs_<sthana>_<chapter>_<verse>`).

---

### Outputs (`backend/processed/` — regenerable, git-ignored)
- `charaka_structured.json` — full corpus, one record per verse
- `<sthana>.json` — per-Sthana slices
- `herb_mentions.json` — herb → verse → condition lookup table

---

## 🗺️ Roadmap

- [x] **Phase 1** — Data collection & curation
- [x] **Phase 2** — Processing, structuring & integrity audit
- [x] **Phase 3** — Retrieval pipeline & verse embeddings
- [x] **Phase 4** — Agentic reasoning, tool use & safety guardrails
- [x] **Phase 5** — MCP tool integration & herb-safety layer
- [x] **Phase 6** — Safety & trust layer (2nd-source verification, numeric confidence, reasoning trace)
- [ ] **Phase 7** — Interactive frontend ("show reasoning" toggle)

---

## 🤝 Disclaimer

**Charaka AI is for educational and general-wellness purposes only.** It is not a medical device and does not provide medical advice, diagnosis, or treatment. Always consult a qualified healthcare professional for any health concern — especially for emergencies, chronic conditions, pregnancy, or children.
---
_Last updated 2026-09-02._
