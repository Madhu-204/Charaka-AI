import type { ChatMessage, Citation, ReasoningTrace, SavedAnswer } from "../types";

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

export function chapterLabel(chapterKey: string | null): string {
  if (!chapterKey) return "";
  const [sthana, ch] = chapterKey.split("/");
  const name = STHANA_LABELS[sthana] ?? sthana;
  return ch ? `${name} · Ch. ${ch}` : name;
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
  return (trace ?? []).map((s) =>
    s
      .replace(/^(emergency gate|dosha tagger|query expansion|retrieval|safety):\s*/i, "")
      .replace(/\u2192/g, "→")
  );
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