import type {
  AskResponse,
  ChatMessage,
  FeedbackRating,
  HerbSummary,
  StreamStage,
} from "./types";

const API_URL = (import.meta.env?.VITE_API_URL ?? "http://localhost:8000").replace(
  /\/$/,
  ""
);

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
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
      headers: { "Content-Type": "application/json" },
      ...init,
      signal: controller.signal,
    });
    if (!res.ok) {
      throw new ApiError(res.status, `Request failed (${res.status})`);
    }
    return (await res.json()) as T;
  } catch (e) {
    if (controller.signal.aborted) {
      throw new ApiError(408, "The answer took too long — backend timed out.");
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

export async function askStream(
  query: string,
  handlers: StreamHandlers,
  timeoutMs = 180_000
): Promise<void> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_URL}/ask/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
      signal: controller.signal,
    });
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
        } else if (ev.type === "error") {
          const parsed = JSON.parse(ev.data) as { message?: string };
          throw new ApiError(500, parsed.message ?? "Stream error");
        }
      }
    }
  } catch (e) {
    if (controller.signal.aborted) {
      const err = new ApiError(408, "The answer took too long — backend timed out.");
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

export async function fetchHerbs(): Promise<HerbSummary[]> {
  const data = await request<{ herbs: HerbSummary[] }>("/herbs");
  return data.herbs;
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
} {
  return {
    query: msg.query ?? "",
    rating: msg.feedback ?? "up",
    message_id: msg.id,
    answer: msg.content,
    trace: msg.reasoning?.steps ?? null,
    dosha: msg.dosha ?? null,
  };
}