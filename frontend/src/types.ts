export type ViewName = "chat" | "herbs" | "saved" | "about";

export type Confidence = "high" | "medium" | "low";

export interface RetrievedVerse {
  verse_id: string;
  chapter: string;
  score: number;
  text?: string;
  confidence?: string;
}

export interface StreamStage {
  node: string;
  label: string;
  ms: number;
}

export interface GroundingInfo {
  score: number | null;
  cited: number[];
  notes: string[];
}

export interface ReasoningTrace {
  steps: string[];
  canonical_term: string | null;
  retrieved_verses: RetrievedVerse[];
  confidence_score: number | null;
  herbs_found: string[];
  dosha_scores: Record<string, number> | null;
  safety_sources: Record<string, string> | null;
  verification_notes: string[];
  source_disagreements: string[];
  grounding?: GroundingInfo | null;
}

export interface AskResponse {
  answer: string;
  is_emergency: boolean;
  is_clarification?: boolean;
  confidence: Confidence | null;
  chapter: string | number | null;
  category_tag: string | null;
  safety_flags: string[];
  dosha: string | null;
  latency_ms?: number | null;
  conversation_id?: string | null;
  conversation_title?: string | null;
  grounding?: GroundingInfo | null;
  reasoning_trace?: ReasoningTrace;
}

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export type FeedbackRating = "up" | "down";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: number;
  query?: string;
  isEmergency?: boolean;
  isClarification?: boolean;
  confidence?: Confidence | null;
  chapter?: string | number | null;
  categoryTag?: string | null;
  dosha?: string | null;
  safetyFlags?: string[];
  reasoning?: ReasoningTrace | null;
  feedback?: FeedbackRating | null;
  showReasoning?: boolean;
  saved?: boolean;
  streaming?: boolean;
  stages?: StreamStage[] | null;
  latencyMs?: number | null;
}

export interface HerbSummary {
  name: string;
  aliases: string[];
  botanical: string | null;
  dosha_tags: string[];
  modern_source_verified: boolean;
  api_of_india_verified: boolean;
  dosha_caution: string;
  contraindications: string[];
  interactions: string[];
  pregnancy_flag: string;
  classical_source: string;
  modern_source: string;
  verification_note: string;
}

export interface SavedAnswer {
  id: string;
  title: string;
  category_tag: string | null;
  dosha: string | null;
  snippet: string;
  answer: string;
  savedAt: number;
  reasoning: ReasoningTrace | null;
}

export type CitationBadge = "verified" | "api" | "ref" | "ai" | "neutral" | "safety";

export interface Citation {
  title: string;
  detail: string;
  badge?: CitationBadge;
  badgeText?: string;
  verseId?: string;
  verseText?: string;
  score?: number;
  citeIndex?: number;
}

export type TraceCheckKind = "emergency" | "pattern" | "source" | "safety";

export interface TraceCheck {
  kind: TraceCheckKind;
  status: string;
}