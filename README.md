# 🌿 Charaka AI

> **Agentic RAG over the Charaka Samhita** — grounded, cited, safety-checked answers for general wellness, straight from classical Ayurvedic texts.

<div align="center">

![Status](https://img.shields.io/badge/status-Phase%203%20%E2%80%94%20Retrieval%20Ready-22c55e)
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
| **4** | Agentic reasoning & safety guardrails | 🔄 **Next** |
| **5** | Frontend interface | ⏳ Planned |

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
| 📊 **Eval baseline** | Top-1 **16/20 (80%)** · Top-3 **17/20 (85%)** · naive keyword hybrid rejected (13/20) | ✅ |

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
├── charaka_data/          # curated source corpus (JSON per chapter)
│   ├── 01_sutra_sthana/
│   ├── 02_vimana_sthana/
│   ├── 03_sharira_sthana/
│   ├── 04_chikitsa_sthana/
│   └── manifest.json
├── reference/             # herbs, mappings, typo fixes, eval set
├── scripts/               # transform.py · audit_ids.py
└── processed/             # regenerable structured output (git-ignored)
```

---

## 🛠️ Tech Stack

`Python` · `JSON` · RAG (planned) · Agentic framework (planned) · Web frontend (planned)

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

### Outputs (`backend/processed/` — regenerable, git-ignored)
- `charaka_structured.json` — full corpus, one record per verse
- `<sthana>.json` — per-Sthana slices
- `herb_mentions.json` — herb → verse → condition lookup table

---

## 🗺️ Roadmap

- [x] **Phase 1** — Data collection & curation
- [x] **Phase 2** — Processing, structuring & integrity audit
- [x] **Phase 3** — Retrieval pipeline & verse embeddings
- [ ] **Phase 4** — Agentic reasoning, tool use & safety guardrails
- [ ] **Phase 5** — Interactive frontend & live evaluation

---

## 🤝 Disclaimer

**Charaka AI is for educational and general-wellness purposes only.** It is not a medical device and does not provide medical advice, diagnosis, or treatment. Always consult a qualified healthcare professional for any health concern — especially for emergencies, chronic conditions, pregnancy, or children.