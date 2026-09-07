import type {
  AskResponse,
  ChatMessage,
  FeedbackRating,
  HerbSummary,
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