import type { ChatMessage, Citation, ReasoningTrace, SavedAnswer, TraceCheck } from "../types";

export const STHANA_LABELS: Record<string, string> = {
  sutrasthana: "Sutra Sthana",
  vimanasthana: "Vimana Sthana",
  sharirasthana: "Sharira Sthana",
  chikitsasthana: "Chikitsa Sthana",
};

export const CATEGORY_LABELS: Record<string, string> = {
  fever_acute: "Fever & Acute Care",
  metabolic: "Metabolism",
  skin: "Skin & Hair",
  digestive: "Digestive Health",
  respiratory: "Respiratory",
  joint_vata_sleep: "Joints, Vata & Sleep",
  foundational_dosha: "Dosha Theory",
  herb_groups: "Herb Groups",
  routine_dinacharya: "Daily Routine",
  routine_seasonal: "Seasonal Routine",
  preventive: "Prevention",
  vata_theory: "Vata Theory",
  disease_classification: "Disease Classification",
  disease_origin: "Disease Origin",
  taste_potency: "Taste & Potency",
  food_properties: "Food Properties",
  taste_theory: "Taste Theory",
  diagnosis_method: "Diagnosis",
  constitution_prakriti: "Constitution",
  constitution: "Constitution",
};

export function categoryLabel(tag: string | null | undefined): string {
  if (!tag) return "General Wellness";
  return CATEGORY_LABELS[tag] ?? tag;
}

export function chapterLabel(chapterKey: string | number | null | undefined): string {
  if (chapterKey === null || chapterKey === undefined || chapterKey === "") return "";
  const [sthana, ch] = String(chapterKey).split("/");
  const name = STHANA_LABELS[sthana] ?? sthana;
  if (ch) return `${name} · Ch. ${ch}`;
  if (/^\d+$/.test(sthana)) return `Ch. ${sthana}`;
  return name;
}

export function verseLabel(verseId: string): string {
  const parts = verseId.split("_");
  if (parts.length < 4) return verseId;
  const [, sthana, ch, range] = parts;
  const name = STHANA_LABELS[sthana] ?? sthana;
  const cleanRange = range.replace(/-(\d+)$/, range.startsWith("-") ? "" : "");
  return `${name} · Ch. ${ch} · v. ${cleanRange}`;
}

export function confidenceText(score: number | null): string {
  if (score === null) return "n/a";
  if (score > 0.6) return "high";
  if (score > 0.45) return "medium";
  return "low";
}

export function badgeForSafetySource(source: string | undefined): {
  badge?: Citation["badge"];
  badgeText?: string;
} {
  switch (source) {
    case "mcp":
      return { badge: "verified", badgeText: "Source verified" };
    case "json_fallback":
      return { badge: "api", badgeText: "Safety DB" };
    case "legacy":
      return { badge: "neutral", badgeText: "Legacy entry" };
    case "uncovered":
      return { badge: "ai", badgeText: "No monograph" };
    default:
      return {};
  }
}

export function buildChatCitations(msg: {
  reasoning?: ReasoningTrace | null;
}): Citation[] {
  const citations: Citation[] = [];
  const rt = msg.reasoning;
  if (!rt) return citations;

  const seen = new Set<string>();
  for (const v of rt.retrieved_verses ?? []) {
    if (seen.has(v.verse_id)) continue;
    seen.add(v.verse_id);
    citations.push({
      title: chapterLabel(v.chapter),
      detail: `${verseLabel(v.verse_id)} — confidence: ${confidenceText(v.score)}`,
      badge: "neutral",
      badgeText: "Retrieved",
    });
  }

  for (const h of rt.herbs_found ?? []) {
    const source = rt.safety_sources?.[h];
    const b = badgeForSafetySource(source);
    citations.push({
      title: h,
      detail: source ? `Safety source: ${source}` : "Safety: no monograph flagged",
      badge: b.badge,
      badgeText: b.badgeText ?? "Checked",
    });
  }

  for (const note of rt.verification_notes ?? []) {
    citations.push({
      title: "Identity / verification note",
      detail: note,
      badge: "ai",
      badgeText: "AI-compiled, unverified",
    });
  }

  for (const d of rt.source_disagreements ?? []) {
    citations.push({
      title: "Source disagreement",
      detail: d,
      badge: "safety",
      badgeText: "Practitioner caution",
    });
  }

  return citations.slice(0, 8);
}

export function stepsFromTrace(trace: string[] | undefined): string[] {
  return (trace ?? []).map((s) => cleanTraceStep(s));
}

function cleanTraceStep(s: string): string {
  return s
    .replace(/^(emergency gate|dosha tagger|query expansion|retrieval|safety):\s*/i, "")
    .replace(/\u2192/g, "→");
}

export function topDosha(scores: Record<string, number> | null | undefined): string | null {
  if (!scores) return null;
  const best = Object.entries(scores)
    .filter(([, v]) => v > 0)
    .sort(([, a], [, b]) => b - a);
  return best.length ? best[0][0] : null;
}

export function traceChecksFromTrace(trace: ReasoningTrace | null | undefined): TraceCheck[] {
  if (!trace) return [];

  const emergencyStep = (trace.steps ?? []).find((s) => /emergency/i.test(s));
  const redFlag = emergencyStep ? /RED_FLAG|red flag.*hit|\bhit\b/i.test(emergencyStep) : false;
  const dosha = topDosha(trace.dosha_scores);
  const src = trace.retrieved_verses?.[0];
  const herbs = trace.herbs_found ?? [];

  return [
    {
      kind: "emergency",
      status: redFlag ? "Red flag — doctor advised" : "Checked ✓",
    },
    {
      kind: "pattern",
      status: dosha ? `${dosha} pattern` : "No pattern matched",
    },
    {
      kind: "source",
      status: src ? chapterLabel(src.chapter) : "No source",
    },
    {
      kind: "safety",
      status: herbs.length ? `${herbs.length} herb(s) verified ✓` : "No herbs detected",
    },
  ];
}

export function primarySourceFromTrace(
  trace: ReasoningTrace | null | undefined
): Citation | null {
  const v = trace?.retrieved_verses?.[0];
  if (!v) return null;
  return {
    title: chapterLabel(v.chapter),
    detail: `${verseLabel(v.verse_id)} — confidence: ${confidenceText(v.score)}`,
    badge: "neutral",
    badgeText: "Retrieved",
  };
}

export function herbCardsFromTrace(trace: ReasoningTrace | null | undefined): Citation[] {
  if (!trace) return [];
  const notes = new Map<string, string>();
  for (const n of trace.verification_notes ?? []) {
    const idx = n.indexOf(":");
    if (idx === -1) continue;
    notes.set(n.slice(0, idx).trim().toLowerCase(), n.slice(idx + 1).trim());
  }
  return (trace.herbs_found ?? []).map((h) => {
    const source = trace.safety_sources?.[h];
    const b = badgeForSafetySource(source);
    const note = notes.get(h.toLowerCase());
    return {
      title: h,
      detail: note ?? (source ? `Safety source: ${source}` : "No safety monograph flagged"),
      badge: b.badge,
      badgeText: b.badgeText ?? "Checked",
    };
  });
}

export function savedFromMessage(msg: ChatMessage): SavedAnswer {
  return {
    id: msg.id,
    title: (msg.categoryTag ? categoryLabel(msg.categoryTag) : "General Wellness"),
    category_tag: msg.categoryTag ?? null,
    dosha: msg.dosha ?? null,
    snippet: msg.content.replace(/[#*`>]/g, "").slice(0, 160),
    answer: msg.content,
    savedAt: Date.now(),
    reasoning: msg.reasoning ?? null,
  };
}