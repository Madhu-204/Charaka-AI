# 🌿 Charaka AI

> **Agentic RAG over the Charaka Samhita** — grounded, cited, safety-checked answers for general wellness, straight from classical Ayurvedic texts.

<div align="center">

![Status](https://img.shields.io/badge/status-Complete-grey)
![Corpus](https://img.shields.io/badge/Corpus-2%2C490%20Verses%20%E2%80%A2%2020%20Chapters-3b82f6)
![License](https://img.shields.io/badge/license-Custom-gray)
![Stack](https://img.shields.io/badge/Python-LangGraph%20%7C%20FastAPI%20%7C%20React-4ea94b)

</div>

---

## ✨ What is it?

Charaka AI is an **Ayurvedic wellness assistant** that answers general health and lifestyle questions — not from an LLM's guesswork, but from **2,490 real verses of the Charaka Samhita**, a classical Ayurvedic text.

Every answer is:

- 🔎 **Retrieved** — pulled from curated, real verses
- 📚 **Cited** — traceable to a specific chapter & verse
- 🛡️ **Safety-checked** — before it ever reaches you
- 🎯 **Clearly scoped** — honest about what software can and cannot responsibly say

> ⚠️ **What it is NOT:** A doctor, a diagnostic tool, or an emergency service. It never handles emergencies, chronic conditions, pregnancy, pediatrics, or mental-health diagnoses.

---

## 🎯 Why it exists

Ayurvedic advice online is scattered, unsourced, and often wrong or contradictory. Charaka AI replaces confident-sounding guesses with **grounded, cited answers** — every claim verifiable against an actual text.

---

## ❓ What you can ask

Common things it supports: bloating, digestion, sleep habits, everyday stress, minor skin, seasonal colds, mild stiffness, weight/lifestyle, seasonal routines, and general onboarding to Ayurvedic ideas.

<details>
<summary><b>📋 Full scope (in / out)</b> — click to expand</summary>

**✅ In scope** — general wellness & lifestyle: digestive health, sleep, energy & immunity, everyday stress, minor skin & hair, seasonal ailments, mild joint stiffness, metabolism, menstrual comfort (lifestyle level), seasonal (*ritucharya*) routines, mild eye/ENT tips.

**❌ Out of scope** — always redirected to a doctor:
emergencies, chronic or diagnosed conditions, pregnancy & children, mental-health diagnoses, anything surgical, or worsening/persistent symptoms. These rules are **hardcoded** — there is no way to talk the agent into answering them.

</details>

---

## 🗺️ How it was built — the journey

Built in **11 phases**, from raw text to a polished, deployable product:

| Phase | What happened | Status |
|-------|---------------|--------|
| **1–2** | Curated & structured the corpus (raw texts → clean, tagged verses) | ✅ |
| **3** | Retrieval pipeline — turned 2,490 verses into a searchable knowledge store | ✅ |
| **4** | Agentic reasoning + safety guardrails | ✅ |
| **5–6** | Herb-safety layer & trust (source verification, confidence, reasoning trace) | ✅ |
| **7** | Interactive frontend — streaming chat UI | ✅ |
| **8** | Agentic depth — memory, conversations & multi-turn reasoning | ✅ |
| **9** | Product polish — corpus explorer, search, summaries, dosha awareness | ✅ |
| **10** | Observability & production — tracing, analytics, caching, rate limits, Docker **→ deployed live** | ✅ |
| **11** | Stretch — sentence-level attribution, bilingual (English ⇄ हिंदी), document upload, voice input, offline PWA, free hosting kit | ✅ |

Each phase was regression-tested as it landed; the agent scores **~85%** on its evaluation set, with **zero** false emergency positives.

---

## ⚙️ How it works (in simple terms)

1. Your question passes through a **safety gate** (emergencies are immediately redirected).
2. The **retriever** finds the most relevant verses + herb references.
3. The **agent** synthesizes a cited answer, grounded in those exact verses.
4. A **grounding & attribution pass** links every sentence back to its source.

<details>
<summary><b>🔬 Tech deep-dive</b> — click to expand</summary>

**Backend** — Python · LangGraph agent · FastAPI · ChromaDB vector store · sentence-transformers · Groq (LLM inference) · MCP herb-safety tool.

**Frontend** — React · TypeScript · Vite · PWA (offline shell) · Web Speech voice input.

**Deployment** — Self-contained Docker image (FastAPI serves both the API and the built UI on one origin). Free hosting via Render with a keep-awake heartbeat.

</details>

---

## 🚀 Try it

### 🌐 Live demo

**https://charaka-ai-ygln.onrender.com**

> Free Render tier spins down after ~15 min idle — first load after a gap can take ~1 min to wake up. A heartbeat keeps it as warm as free hosting allows.

<details open>
<summary><b>💻 Run locally</b> — click to expand</summary>

**Backend**

```bash
cd backend
python -m venv .venv                     # once
# Windows: .venv\Scripts\activate · macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt          # once
copy .env.example .env                   # add GROQ_API_KEY (free tier), never commit
uvicorn app.main:app --reload
```

**Frontend** *(optional, browser dev mode)*

```bash
cd frontend
npm install
npm run dev                              # → http://localhost:5173
```

Or the whole stack in one command with Docker:

```bash
docker compose up --build
```

</details>

### 🆓 Free hosting

The same Docker image deploys **free on Render** (no credit card) via the included `render.yaml` blueprint — or as a Hugging Face Space if you have a paid HF plan. See the deploy notes in the repo for details. Live instance: **https://charaka-ai-ygln.onrender.com**.

---

## 🤝 Disclaimer

**Charaka AI is for educational and general-wellness purposes only.** It is not a medical device and does not provide medical advice, diagnosis, or treatment. Always consult a qualified healthcare professional for any health concern — especially for emergencies, chronic conditions, pregnancy, or children.

---

<p align="center">🌿 Built with patience, verses, and a strong safety guardrail.</p>