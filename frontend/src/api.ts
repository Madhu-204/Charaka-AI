import type {
  AnswerSummary,
  AskResponse,
  ChatMessage,
  ConversationSummary,
  CorpusSthana,
  CorpusVerse,
  CorpusSearchResult,
  DocRecord,
  EvalResult,
  EvalRow,
  FeedbackRating,
  HerbSummary,
  StreamStage,
} from "./types";

const API_URL = (import.meta.env?.VITE_API_URL ?? "http://localhost:8000").replace(
  /\/$/,
  ""
);

// Legacy shared-key header. Kept only for CHARAKA_AUTH_REQUIRED=0 single-user
// setups; real sessions use the bearer token below.
const API_KEY = (import.meta.env?.VITE_CHARAKA_API_KEY ?? "") as string;

const TOKEN_KEY = "charaka-token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private browsing — session stays in memory only */
  }
}

let onUnauthorized: (() => void) | null = null;

/** Registered by the app shell so an expired or revoked token bounces the
    user back to the sign-in screen instead of failing silently per request. */
export function setUnauthorizedHandler(fn: () => void): void {
  onUnauthorized = fn;
}

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = { ...(extra ?? {}) };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (API_KEY) headers["X-API-Key"] = API_KEY;
  return headers;
}

export class ApiError extends Error {
  status: number;
  /** True when re-sending the same request could plausibly succeed. */
  retryable: boolean;

  constructor(status: number, message: string, retryable = false) {
    super(message);
    this.status = status;
    this.retryable = retryable;
  }
}

async function request<T>(
  path: string,
  init?: RequestInit,
  timeoutMs = 60_000
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_URL}${path}`, {
      ...init,
      // Spread init last would drop the auth headers, so merge explicitly.
      headers: authHeaders({
        "Content-Type": "application/json",
        ...(init?.headers as Record<string, string> | undefined),
      }),
      signal: controller.signal,
    });
    if (res.status === 401) {
      onUnauthorized?.();
      // Read the server's message: it distinguishes a bad password from an
      // expired session.
      let detail = "Please sign in to continue.";
      try {
        const body = await res.json();
        if (body?.detail) detail = String(body.detail);
      } catch {
        /* non-JSON error body */
      }
      throw new ApiError(401, detail);
    }
    if (res.status === 503) {
      // A 503 from /ask means the LLM provider was unavailable or its quota is
      // spent. Prefer the server's own copy so the user sees the real cause.
      let detail = "The assistant is busy right now — retry in a moment.";
      try {
        const body = await res.json();
        if (body?.detail) detail = String(body.detail);
      } catch {
        /* keep the default message */
      }
      throw new ApiError(503, detail, true);
    }
    if (!res.ok) {
      let detail = `Request failed (${res.status})`;
      try {
        const body = await res.json();
        if (body?.detail) detail = String(body.detail);
      } catch {
        /* keep the status-based message */
      }
      throw new ApiError(res.status, detail);
    }
    return (await res.json()) as T;
  } catch (e) {
    if (controller.signal.aborted) {
      throw new ApiError(408, "The answer took too long — backend timed out.", true);
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

export async function ask(query: string): Promise<AskResponse> {
  return request<AskResponse>("/ask", {
    method: "POST",
    body: JSON.stringify({ query }),
  }, 120_000);
}

export interface StreamHandlers {
  onStage?: (stage: StreamStage) => void;
  onToken?: (delta: string) => void;
  onDone?: (resp: AskResponse) => void;
  onSummary?: (summary: AnswerSummary) => void;
  onError?: (err: Error) => void;
}

interface SseEvent {
  type: string;
  data: string;
}

function parseSse(part: string): SseEvent | null {
  let type = "message";
  const dataParts: string[] = [];
  for (const line of part.split("\n")) {
    const trimmed = line.trim();
    if (trimmed.startsWith("event:")) {
      type = trimmed.slice("event:".length).trim();
    } else if (trimmed.startsWith("data:")) {
      dataParts.push(trimmed.slice("data:".length).trimStart());
    }
  }
  if (dataParts.length === 0) return null;
  return { type, data: dataParts.join("\n") };
}

export interface AskStreamOptions {
  conversationId?: string | null;
  history?: { role: string; content: string }[];
  doshaProfile?: string | null;
  lang?: "en" | "hin" | null;
  docSession?: string | null;
  timeoutMs?: number;
  /**
   * Caller-owned abort signal for the Stop button. Aborting cancels the fetch
   * so the UI can release immediately; the backend also watches for client
   * disconnect and stops its own work.
   */
  signal?: AbortSignal;
  /**
   * Overwrite the previous answer for this turn instead of appending a
   * duplicate user/assistant pair. Sent when the user presses Regenerate.
   */
  regenerate?: boolean;
}

export async function askStream(
  query: string,
  handlers: StreamHandlers,
  opts: AskStreamOptions = {}
): Promise<void> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), opts.timeoutMs ?? 180_000);
  // Forward an external abort (Stop button) into our own controller.
  const external = opts.signal;
  const forwardAbort = () => controller.abort();
  if (external) {
    if (external.aborted) controller.abort();
    else external.addEventListener("abort", forwardAbort);
  }
  try {
    const res = await fetch(`${API_URL}/ask/stream`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        query,
        // Sent only when the caller actually supplies it. An explicit `[]` here
        // looks equivalent but is not: the backend loads the stored thread only
        // when `history is None`, so defaulting to an empty array permanently
        // shadowed the thread and made every turn read as the first one.
        history: opts.history,
        conversation_id: opts.conversationId ?? null,
        dosha_profile: opts.doshaProfile ?? null,
        lang: opts.lang ?? null,
        doc_session: opts.docSession ?? null,
        regenerate: opts.regenerate ?? false,
      }),
      signal: controller.signal,
    });
    if (res.status === 401) {
      onUnauthorized?.();
      let detail = "Your session has expired. Please sign in again.";
      try {
        const body = await res.json();
        if (body?.detail) detail = String(body.detail);
      } catch {
        /* non-JSON error body */
      }
      throw new ApiError(401, detail);
    }
    if (!res.ok) {
      throw new ApiError(res.status, `Request failed (${res.status})`);
    }
    if (!res.body) {
      throw new ApiError(-1, "No response stream from backend.");
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop() ?? "";
      for (const part of parts) {
        const ev = parseSse(part);
        if (!ev) continue;
        if (ev.type === "stage") {
          handlers.onStage?.(JSON.parse(ev.data) as StreamStage);
        } else if (ev.type === "token") {
          const parsed = JSON.parse(ev.data) as { delta: string };
          if (parsed.delta) handlers.onToken?.(parsed.delta);
        } else if (ev.type === "done") {
          handlers.onDone?.(JSON.parse(ev.data) as AskResponse);
        } else if (ev.type === "summary") {
          // Arrives after `done` so the answer bubble finalises without
          // waiting on the summary LLM call.
          const parsed = JSON.parse(ev.data) as { summary?: AnswerSummary | null };
          if (parsed.summary) handlers.onSummary?.(parsed.summary);
        } else if (ev.type === "error") {
          const parsed = JSON.parse(ev.data) as {
            message?: string;
            retryable?: boolean;
          };
          // The backend marks provider/quota and busy failures as retryable so
          // the UI can offer a Retry button instead of implying a broken app.
          throw new ApiError(
            parsed.retryable ? 503 : 500,
            parsed.message ?? "Stream error",
            Boolean(parsed.retryable)
          );
        }
      }
    }
  } catch (e) {
    if (controller.signal.aborted) {
      // A user-initiated stop is not an error: report it with a distinct 499 so
      // the UI can leave the partial answer on screen without raising an error.
      if (external?.aborted) {
        const stopped = new ApiError(499, "Generation stopped.");
        handlers.onError?.(stopped);
        throw stopped;
      }
      const err = new ApiError(
        408,
        "The answer took too long — backend timed out.",
        true
      );
      handlers.onError?.(err);
      throw err;
    }
    const err = e instanceof Error ? e : new Error(String(e));
    handlers.onError?.(err);
    throw err;
  } finally {
    clearTimeout(timer);
    external?.removeEventListener("abort", forwardAbort);
  }
}

export async function fetchHerbs(): Promise<HerbSummary[]> {
  const data = await request<{ herbs: HerbSummary[] }>("/herbs");
  return data.herbs;
}

export interface AuthUser {
  id: string;
  email: string;
  name: string;
  created_at: string;
}

export interface AuthConfig {
  auth_required: boolean;
  needs_registration: boolean;
}

/** Public: tells the client whether to gate on sign-in and whether the very
    first visitor should be nudged to create an account. */
export async function fetchAuthConfig(): Promise<AuthConfig> {
  const res = await fetch(`${API_URL}/auth/config`, {
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) {
    throw new ApiError(res.status, "Could not reach the sign-in service.");
  }
  return (await res.json()) as AuthConfig;
}

export async function fetchMe(): Promise<AuthUser | null> {
  try {
    const data = await request<{ user: AuthUser | null }>("/auth/me");
    return data.user;
  } catch (e) {
    // 401 is the expected "not signed in" answer here, not a failure.
    if (e instanceof ApiError && e.status === 401) return null;
    throw e;
  }
}

export async function register(
  email: string,
  password: string,
  name: string
): Promise<{ token: string; user: AuthUser }> {
  return request<{ token: string; user: AuthUser }>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, name }),
  });
}

export async function login(
  email: string,
  password: string
): Promise<{ token: string; user: AuthUser }> {
  return request<{ token: string; user: AuthUser }>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function logout(): Promise<void> {
  try {
    await request("/auth/logout", { method: "POST" });
  } catch {
    // Revoking server-side is best-effort; the local token is cleared either way.
  }
}

export interface HindiSummaryPayload {
  query: string;
  answer: string;
  retrieved?: { text?: string }[];
  is_emergency?: boolean;
  is_clarification?: boolean;
}

export async function fetchHindiSummary(
  payload: HindiSummaryPayload
): Promise<AnswerSummary | null> {
  const data = await request<{ ok: boolean; hindi: AnswerSummary | null }>(
    "/summary/hindi",
    { method: "POST", body: JSON.stringify(payload) }
  );
  return data.ok ? data.hindi : null;
}

export async function fetchLastEval(): Promise<EvalResult | null> {
  const data = await request<{ ok: boolean } & Partial<EvalResult>>("/eval/last");
  if (!data.ok || !data.summary) return null;
  return { summary: data.summary, rows: data.rows ?? [] };
}

export interface EvalHandlers {
  onItem?: (row: EvalRow & { index: number; total: number }) => void;
  onDone?: (result: EvalResult) => void;
  onError?: (err: Error) => void;
}

export async function runEvalStream(
  corner: boolean,
  mode: "retrieval" | "full",
  handlers: EvalHandlers,
): Promise<void> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 900_000);
  try {
    const res = await fetch(`${API_URL}/eval/run`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ corner, mode }),
      signal: controller.signal,
    });
    if (!res.ok) throw new ApiError(res.status, `Request failed (${res.status})`);
    if (!res.body) throw new ApiError(-1, "No response stream from backend.");

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop() ?? "";
      for (const part of parts) {
        const ev = parseSse(part);
        if (!ev) continue;
        if (ev.type === "item") {
          handlers.onItem?.(
            JSON.parse(ev.data) as EvalRow & { index: number; total: number },
          );
        } else if (ev.type === "done") {
          handlers.onDone?.(JSON.parse(ev.data) as EvalResult);
        } else if (ev.type === "error") {
          const parsed = JSON.parse(ev.data) as { message?: string };
          throw new ApiError(500, parsed.message ?? "Eval error");
        }
      }
    }
  } catch (e) {
    if (controller.signal.aborted) {
      const err = new ApiError(408, "The eval run took too long — timed out.");
      handlers.onError?.(err);
      throw err;
    }
    const err = e instanceof Error ? e : new Error(String(e));
    handlers.onError?.(err);
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export interface ConversationRecord {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages: {
    id: string;
    role: string;
    content: string;
    query?: string;
    isEmergency?: boolean;
    is_clarification?: boolean;
    confidence?: string | null;
    chapter?: string | number | null;
    category_tag?: string | null;
    dosha?: string | null;
    safety_flags?: string[];
    reasoning_trace?: AskResponse["reasoning_trace"];
    grounding?: AskResponse["grounding"];
    latency_ms?: number | null;
    timestamp?: string;
    summary?: AskResponse["summary"];
    suggestions?: string[];
    attribution?: AskResponse["attribution"];
    used_documents?: boolean;
  }[];
}

interface ConversationsResponse {
  conversations: ConversationSummary[];
}

export async function fetchConversations(): Promise<ConversationSummary[]> {
  const data = await request<ConversationsResponse>("/conversations");
  return data.conversations;
}

export async function fetchConversation(id: string): Promise<ConversationRecord> {
  const data = await request<{ ok: boolean; conversation: ConversationRecord }>(
    `/conversations/${encodeURIComponent(id)}`
  );
  if (!data.ok) {
    const err = new ApiError(404, "Conversation not found.");
    err.status = 404;
    throw err;
  }
  return data.conversation;
}

export async function deleteConversation(id: string): Promise<boolean> {
  const data = await request<{ ok: boolean }>(
    `/conversations/${encodeURIComponent(id)}`,
    { method: "DELETE" }
  );
  return data.ok;
}

export async function uploadDocument(
  sessionId: string,
  file: File
): Promise<{ ok: boolean; name: string; chunks: number }> {
  const form = new FormData();
  form.append("session_id", sessionId);
  form.append("file", file);
  const res = await fetch(`${API_URL}/documents/upload`, {
    method: "POST",
    headers: authHeaders(),
    body: form,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, (body as { detail?: string })?.detail ?? "Upload failed");
  }
  return (await res.json()) as { ok: boolean; name: string; chunks: number };
}

export async function fetchDocuments(sessionId: string): Promise<DocRecord[]> {
  const data = await request<{ ok: boolean; documents: DocRecord[] }>(
    `/documents/${encodeURIComponent(sessionId)}`
  );
  return data.documents;
}

export async function deleteDocuments(sessionId: string): Promise<void> {
  await request<{ ok: boolean }>(`/documents/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });
}

export async function fetchCorpusSthanas(): Promise<CorpusSthana[]> {
  const data = await request<{ sthanas: CorpusSthana[] }>("/corpus/sthanas");
  return data.sthanas;
}

export async function fetchChapterVerses(
  sthana: string,
  chapter: number
): Promise<CorpusVerse[]> {
  const data = await request<{ verses: CorpusVerse[] }>(
    `/corpus/${encodeURIComponent(sthana)}/${chapter}`
  );
  return data.verses;
}

export async function searchCorpus(
  query: string,
  limit = 10
): Promise<CorpusSearchResult[]> {
  const data = await request<{ results: CorpusSearchResult[] }>("/corpus/search", {
    method: "POST",
    body: JSON.stringify({ query, limit }),
  });
  return data.results;
}

export async function submitFeedback(payload: {
  query: string;
  rating: FeedbackRating;
  message_id?: string | null;
  answer?: string | null;
  trace?: string[] | null;
  dosha?: string | null;
}): Promise<void> {
  await request("/feedback", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function feedbackPayload(msg: ChatMessage): {
  query: string;
  rating: FeedbackRating;
  message_id: string | null;
  answer: string | null;
  trace: string[] | null;
  dosha: string | null;
  category_tag: string | null;
  chapter: string | null;
} {
  return {
    query: msg.query ?? "",
    rating: msg.feedback ?? "up",
    message_id: msg.id,
    answer: msg.content,
    trace: msg.reasoning?.steps ?? null,
    dosha: msg.dosha ?? null,
    category_tag: msg.categoryTag ?? null,
    chapter: msg.chapter != null ? String(msg.chapter) : null,
  };
}