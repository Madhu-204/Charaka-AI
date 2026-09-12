import json
import os
import re

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_groq import ChatGroq

load_dotenv()

_summ_llm = ChatGroq(model="openai/gpt-oss-120b", api_key=os.environ["GROQ_API_KEY"])

SYSTEM_PROMPT = """You are the answer summariser for Charaka AI, an Ayurvedic wellness assistant.
Given the QUESTION, the ANSWER, and the CITED VERSE TEXTS, produce a JSON object with exactly this shape:
{
  "title": "a short label for this answer (max 8 words)",
  "takeaways": ["up to 3 very short bullet points, each grounded ONLY in the answer"],
  "doctor_check": ["up to 2 short 'See a doctor if...' lines, based ONLY on cautions, uncertainty or safety flags in the answer"]
}
Rules:
- takeaways must restate the answer, never add new facts.
- If the answer is a clarification request or emergency redirect, return empty takeaways.
- Return ONLY the JSON object — no markdown, no commentary."""

FALLBACK = {
    "title": "Classical guidance",
    "takeaways": [],
    "doctor_check": ["Consult a doctor if your symptoms persist or worsen."],
}

HINDI_SYSTEM_PROMPT = """You are the Hindi answer summariser for Charaka AI, an Ayurvedic wellness assistant.
Given the QUESTION, the ANSWER, and the CITED VERSE TEXTS, produce a JSON object with exactly this shape:
{
  "title": "a short label in Devanagari Hindi (max 8 words)",
  "takeaways": ["up to 3 very short bullet points in Devanagari Hindi, grounded ONLY in the answer"],
  "doctor_check": ["up to 2 short 'चिकित्सक से मिलें अगर...' lines in Devanagari Hindi, based ONLY on cautions or safety flags in the answer"]
}
Rules:
- takeaways must restate the answer, never add new facts.
- If the answer is a clarification request or emergency redirect, return empty takeaways.
- Use simple, natural Devanagari Hindi. Return ONLY the JSON object — no markdown, no commentary."""


def _clean(lines):
    out = []
    for line in lines or []:
        line = re.sub(r"\s+", " ", str(line or "")).strip().strip("-* ")
        if line:
            out.append(line)
    return out[:3]


def _template_summary(query, answer, result):
    rc = result.get("resolved_chapter") or {}
    takeaways = []
    meta = rc.get("meta", {}) or {}
    condition = meta.get("traditional_condition") or meta.get("category_tag")
    if condition:
        takeaways.append(
            f"The nearest classical match is on {condition} (Sth. {meta.get('sthana')} Ch.{meta.get('chapter')})."
        )
    for c in (result.get("retrieved") or [])[:1]:
        text = (c.get("text") or "").strip()
        if text:
            first = text.split(";")[0].split(",")[0].strip()
            if first:
                takeaways.append(first[:160])
    herbs = result.get("herbs_found", [])
    if herbs:
        takeaways.append(f"Classically relevant herbs: {', '.join(herbs[:3])}.")

    doctor_check = []
    if result.get("safety_flags"):
        doctor_check.append("Herb-specific safety cautions from the practitioner review — read before use.")
    if result.get("source_disagreements"):
        doctor_check.append("Modern sources flag cautions for some herbs mentioned here — see details below.")
    if not doctor_check:
        doctor_check.append("Consult a doctor if your symptoms persist or worsen.")

    return {
        "title": condition.title() if condition else "Classical guidance",
        "takeaways": takeaways[:3],
        "doctor_check": doctor_check[:2],
    }


def build_summary(query, answer, result, lang: str = "en"):
    if result.get("is_emergency") or result.get("is_clarification"):
        return {"title": "", "takeaways": [], "doctor_check": [], "hindi": None}
    rc = result.get("resolved_chapter") or {}
    verse_block = "\n".join(
        f"- {(c.get('text') or '')[:300]}" for c in result.get("retrieved", [])[:3]
    )
    human = (
        f"QUESTION: {query}\n\nANSWER:\n{answer[:2200]}\n\n"
        f"CITED VERSES:\n{verse_block or 'none'}"
    )
    parsed = _summarize_en(human, query, answer, result)
    if lang == "hin":
        try:
            out = _summ_llm.invoke(
                [
                    SystemMessage(content=HINDI_SYSTEM_PROMPT),
                    HumanMessage(content=human),
                ]
            ).content
            hindi = json.loads(out)
            parsed["hindi"] = {
                "title": str(hindi.get("title") or "").strip()[:80],
                "takeaways": _clean(hindi.get("takeaways"))[:3],
                "doctor_check": _clean(hindi.get("doctor_check"))[:2],
            }
        except Exception as e:  # noqa: BLE001
            print(f"[summarize] Hindi Groq call failed ({e}) → no Hindi summary")
            parsed["hindi"] = None
    else:
        parsed["hindi"] = None
    return parsed


def _summarize_en(human: str, query: str, answer: str, result: dict) -> dict:
    try:
        out = _summ_llm.invoke(
            [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=human)]
        ).content
        parsed = json.loads(out)
        parsed["takeaways"] = _clean(parsed.get("takeaways"))[:3]
        parsed["doctor_check"] = _clean(parsed.get("doctor_check"))[:2]
        parsed["title"] = str(parsed.get("title") or "").strip()[:80]
        return parsed
    except Exception as e:  # noqa: BLE001
        print(f"[summarize] Groq failed ({e}) → template summary")
        return _template_summary(query, answer, result)