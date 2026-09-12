import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  askStream,
  ApiError,
  deleteDocuments,
  feedbackPayload,
  fetchConversation,
  fetchDocuments,
  submitFeedback,
  uploadDocument,
} from "../api";
import type { ConversationRecord } from "../api";
import { buildChatCitations, herbCardsFromTrace, primarySourceFromTrace, stepsFromTrace, traceChecksFromTrace, savedFromMessage } from "../lib/format";
import { addSaved } from "../lib/saved";
import type { AskResponse, ChatMessage, Confidence, DocRecord, FeedbackRating, StreamStage } from "../types";
import type { ReasoningContent } from "../components/ReasoningPanel";
import { ChatBubble } from "../components/ChatBubble";
import { IconChat, IconMic, IconSend } from "../components/Icons";

interface ChatViewProps {
  onReasoning: (content: ReasoningContent | null) => void;
  conversationId: string | null;
  onConversationChange: (id: string | null) => void;
}

const SUGGESTIONS = [
  "I have bloating and poor appetite after meals",
  "What does Charaka say about coughing with phlegm?",
  "I feel anxious and can't sleep at night",
  "Is ashwagandha safe to take daily?",
];

function newId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
}

function reasoningFor(msg: ChatMessage): ReasoningContent {
  return {
    steps: stepsFromTrace(msg.reasoning?.steps),
    citations: buildChatCitations(msg),
    checks: msg.reasoning ? traceChecksFromTrace(msg.reasoning) : undefined,
    primarySource: primarySourceFromTrace(msg.reasoning),
    herbs: herbCardsFromTrace(msg.reasoning),
    showSearch: true,
  };
}

function mapStoredMessage(m: ConversationRecord["messages"][number]): ChatMessage {
  const parsed = m.timestamp ? Date.parse(m.timestamp) : NaN;
  return {
    id: m.id,
    role: m.role === "assistant" ? "assistant" : "user",
    content: m.content,
    createdAt: Number.isNaN(parsed) ? Date.now() : parsed,
    query: m.query,
    isEmergency: m.isEmergency,
    isClarification: m.is_clarification,
    confidence: (m.confidence as Confidence) ?? null,
    chapter: m.chapter ?? null,
    categoryTag: m.category_tag ?? null,
    dosha: m.dosha ?? null,
    safetyFlags: m.safety_flags ?? [],
    reasoning: m.reasoning_trace ?? null,
    feedback: null,
    showReasoning: false,
    saved: false,
    streaming: false,
    stages: null,
    latencyMs: m.latency_ms ?? null,
    summary: m.summary ?? null,
    suggestions: m.suggestions ?? null,
    attribution: m.attribution ?? null,
    usedDocuments: m.used_documents,
  };
}

function docSessionId(): string {
  if (typeof localStorage === "undefined") return "local";
  let id = localStorage.getItem("charaka-doc-session");
  if (!id) {
    id =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `${Date.now()}-doc`;
    localStorage.setItem("charaka-doc-session", id);
  }
  return id;
}

function langSetting(): "en" | "hin" {
  return typeof localStorage !== "undefined" &&
    localStorage.getItem("charaka-lang") === "hin"
    ? "hin"
    : "en";
}

export function ChatView({ onReasoning, conversationId, onConversationChange }: ChatViewProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lang, setLang] = useState<"en" | "hin">(langSetting);
  const [docsOpen, setDocsOpen] = useState(false);
  const [docs, setDocs] = useState<DocRecord[]>([]);
  const [docMsg, setDocMsg] = useState<string | null>(null);
  const [listening, setListening] = useState(false);
  const feedRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const loadedRef = useRef<string | null>(null);
  const uploadRef = useRef<HTMLInputElement>(null);

  const docSession = useMemo(() => docSessionId(), []);

  const speechSupported =
    typeof window !== "undefined" &&
    Boolean(
      (window as unknown as {
        webkitSpeechRecognition?: unknown;
        SpeechRecognition?: unknown;
      }).webkitSpeechRecognition ??
        (window as unknown as { SpeechRecognition?: unknown }).SpeechRecognition
    );

  const speechRef = useRef<{ stop: () => void } | null>(null);

  const refreshDocs = useCallback(() => {
    fetchDocuments(docSession)
      .then(setDocs)
      .catch(() => setDocs([]));
  }, [docSession]);

  useEffect(() => {
    refreshDocs();
  }, [refreshDocs]);

  useEffect(() => {
    return () => {
      speechRef.current?.stop();
    };
  }, []);

  const scrollToBottom = useCallback(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: "smooth" });
  }, []);

  const scrollToBottomFast = useCallback(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: "auto" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading, scrollToBottom]);

  useEffect(() => {
    onReasoning(null);
    textareaRef.current?.focus();
  }, [onReasoning]);

  useEffect(() => {
    onReasoning(null);
    setError(null);
    if (!conversationId) {
      loadedRef.current = null;
      setMessages([]);
      return;
    }
    if (loadedRef.current === conversationId) return;
    loadedRef.current = conversationId;
    let cancelled = false;
    setLoading(true);
    fetchConversation(conversationId)
      .then((rec) => {
        if (cancelled) return;
        setMessages(rec.messages.map(mapStoredMessage));
      })
      .catch(() => {
        if (!cancelled) setError("Could not load that conversation.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [conversationId, onReasoning]);

  async function handleSend(text?: string) {
    const query = (text ?? input).trim();
    if (!query || loading) return;

    const userMsg: ChatMessage = {
      id: newId(),
      role: "user",
      content: query,
      createdAt: Date.now(),
    };
    const assistantId = newId();
    const assistantMsg: ChatMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      query,
      createdAt: Date.now(),
      isEmergency: false,
      streaming: true,
      stages: [],
      feedback: null,
      showReasoning: false,
      saved: false,
    };
    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setInput("");
    setError(null);
    setLoading(true);

    const buffer = { text: "" };
    const appendDelta = (delta: string) => {
      buffer.text += delta;
      setMessages((prev) =>
        prev.map((m) => (m.id === assistantId ? { ...m, content: buffer.text } : m))
      );
    };

    const finalize = (res: AskResponse) => {
      const finalMsg: ChatMessage = {
        id: assistantId,
        role: "assistant",
        content: res.answer,
        query,
        createdAt: Date.now(),
        isEmergency: res.is_emergency,
        isClarification: res.is_clarification,
        confidence: res.confidence,
        chapter: res.chapter,
        categoryTag: res.category_tag,
        dosha: res.dosha,
        safetyFlags: res.safety_flags,
        reasoning: res.reasoning_trace ?? null,
        latencyMs: res.latency_ms ?? null,
        feedback: null,
        showReasoning: false,
        saved: false,
        streaming: false,
        stages: null,
        summary: res.summary ?? null,
        suggestions: res.suggestions ?? null,
        attribution: res.attribution ?? null,
        usedDocuments: res.used_documents,
      };
      setMessages((prev) => prev.map((m) => (m.id === assistantId ? finalMsg : m)));
      onReasoning(reasoningFor(finalMsg));
      if (res.conversation_id && res.conversation_id !== conversationId) {
        loadedRef.current = res.conversation_id;
        onConversationChange(res.conversation_id);
      }
    };

    try {
      await askStream(
        query,
        {
          onStage: (stage: StreamStage) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId ? { ...m, stages: [...(m.stages ?? []), stage] } : m
              )
            );
          },
          onToken: appendDelta,
          onDone: finalize,
          onError: (e) => {
            if (e instanceof ApiError && e.status === 408) {
              setError(e.message);
            } else {
              setError(
                e instanceof Error && "status" in e
                  ? "The backend could not answer just now. Make sure the server is running on port 8000."
                  : "Something went wrong. Please try again."
              );
            }
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId ? { ...m, streaming: false, stages: null } : m
              )
            );
          },
        },
        {
          conversationId,
          doshaProfile: lastDosha,
          lang,
          docSession,
          timeoutMs: 180_000,
        }
      );
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 408
          ? e.message
          : e instanceof Error && "status" in e
            ? "The backend could not answer just now. Make sure the server is running on port 8000."
            : "Something went wrong. Please try again."
      );
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  }

  function handleFeedback(id: string, rating: FeedbackRating) {
    setMessages((prev) =>
      prev.map((m) => (m.id === id ? { ...m, feedback: m.feedback === rating ? null : rating } : m))
    );
    const target = messages.find((m) => m.id === id);
    if (target) {
      const payload = feedbackPayload({ ...target, feedback: rating });
      void submitFeedback(payload).catch(() => {
        /* non-fatal */
      });
    }
  }

  function handleToggleReasoning(id: string) {
    setMessages((prev) =>
      prev.map((m) => (m.id === id ? { ...m, showReasoning: !m.showReasoning } : m))
    );
  }

  function handleSave(id: string) {
    const target = messages.find((m) => m.id === id);
    if (!target || target.saved) return;
    addSaved(savedFromMessage(target));
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, saved: true } : m)));
  }

  function handleSuggestion(text: string) {
    void handleSend(text);
  }

  function handleRegenerate(query: string) {
    if (!query.trim() || loading) return;
    void handleSend(query);
  }

  function handleLangToggle() {
    setLang((prev) => {
      const next = prev === "en" ? "hin" : "en";
      localStorage.setItem("charaka-lang", next);
      return next;
    });
  }

  function handleVoice() {
    if (!speechSupported || listening || loading) return;
    type AnyRecognition = new () => {
      lang: string;
      interimResults: boolean;
      maxAlternatives: number;
      continuous: boolean;
      onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
      onerror: (() => void) | null;
      onend: (() => void) | null;
      start: () => void;
      stop: () => void;
    };
    const recCtor = (window as unknown as {
      webkitSpeechRecognition?: AnyRecognition;
      SpeechRecognition?: AnyRecognition;
    });
    const Ctor = recCtor.webkitSpeechRecognition ?? recCtor.SpeechRecognition;
    if (!Ctor) return;
    const rec = new Ctor();
    rec.lang = "en-IN";
    rec.interimResults = true;
    rec.continuous = false;
    rec.maxAlternatives = 1;
    rec.onresult = (e) => {
      const last = e.results[e.results.length - 1];
      if (last) setInput(last[0]?.transcript ?? "");
    };
    rec.onerror = () => setListening(false);
    rec.onend = () => {
      setListening(false);
      speechRef.current = null;
    };
    speechRef.current = rec;
    setListening(true);
    rec.start();
  }

  async function handleUploadFile(file: File | null) {
    if (!file) return;
    setDocMsg("Uploading…");
    try {
      const res = await uploadDocument(docSession, file);
      setDocMsg(`Uploaded "${res.name}" (${res.chunks} chunk${res.chunks === 1 ? "" : "s"}).`);
      refreshDocs();
    } catch (e) {
      setDocMsg(e instanceof Error ? e.message : "Upload failed.");
    }
    if (uploadRef.current) uploadRef.current.value = "";
  }

  async function handleClearDocs() {
    setDocMsg("Clearing…");
    try {
      await deleteDocuments(docSession);
      setDocs([]);
      setDocMsg("Uploaded documents cleared.");
    } catch {
      setDocMsg("Could not clear documents.");
    }
  }

  const lastAssistantId = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "assistant") return messages[i].id;
    }
    return null;
  }, [messages]);

  const lastDosha = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const d = messages[i].dosha;
      if (d) return d;
    }
    return null;
  }, [messages]);

  return (
    <div className="chat-view">
      <div className="chat-feed" ref={feedRef}>
        {messages.length === 0 && !loading && (
          <div className="chat-feed__empty">
            <h3>Ask Charaka anything about general wellness</h3>
            <p>
              Grounded in 2,490 verses of the Charaka Samhita — every answer cited, every herb
              safety-checked.
            </p>
            <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 8, alignItems: "center" }}>
              {SUGGESTIONS.map((s) => (
                <button key={s} className="pill" onClick={() => void handleSend(s)}>
                  <IconChat width={14} height={14} />
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m) => (
          <ChatBubble
            key={m.id}
            message={m}
            isNew={m.id === lastAssistantId}
            onContentChange={scrollToBottomFast}
            onFeedback={handleFeedback}
            onToggleReasoning={handleToggleReasoning}
            onSave={handleSave}
            onSuggestion={handleSuggestion}
            onRegenerate={handleRegenerate}
          />
        ))}
      </div>

      {error && <div className="chat-error">{error}</div>}

      <div className="chat-input-bar">
        <div className="chat-toolbar">
          <button
            className={docsOpen ? "toolbar-btn toolbar-btn--on" : "toolbar-btn"}
            onClick={() => setDocsOpen((o) => !o)}
            aria-expanded={docsOpen}
          >
            <IconChat width={14} height={14} />
            My documents
            {docs.length > 0 && <span className="toolbar-btn__count">{docs.length}</span>}
          </button>
          <span className="toolbar-spacer" />
          <button
            className={lang === "hin" ? "toolbar-btn toolbar-btn--on" : "toolbar-btn"}
            onClick={handleLangToggle}
            title="Toggle summary language (English / हिंदी)"
          >
            {lang === "hin" ? "हिंदी" : "English"}
          </button>
        </div>

        {docsOpen && (
          <div className="docs-panel">
            <p className="docs-panel__hint">
              Upload a .txt, .md or .pdf — Charaka can answer using it alongside
              the classical corpus, clearly separated.
            </p>
            <div className="docs-panel__row">
              <input
                ref={uploadRef}
                type="file"
                accept=".txt,.md,.markdown,.pdf"
                hidden
                onChange={(e) => void handleUploadFile(e.target.files?.[0] ?? null)}
              />
              <button className="pill" onClick={() => uploadRef.current?.click()} disabled={loading}>
                Upload document
              </button>
              {docs.length > 0 && (
                <button className="pill pill--ghost" onClick={() => void handleClearDocs()}>
                  Clear all
                </button>
              )}
            </div>
            {docMsg && <p className="docs-panel__msg">{docMsg}</p>}
            {docs.length > 0 ? (
              <ul className="docs-panel__list">
                {docs.map((d) => (
                  <li key={d.name} className="docs-panel__item">
                    <span>{d.name}</span>
                    <span className="docs-panel__meta">{d.chunks} chunk{d.chunks === 1 ? "" : "s"}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="docs-panel__empty">No documents uploaded yet.</p>
            )}
          </div>
        )}

        <div className="chat-input">
          <textarea
            ref={textareaRef}
            rows={1}
            value={input}
            placeholder="Ask about remedies, herbs, digestion, sleep, stress…"
            onChange={(e) => {
              setInput(e.target.value);
              e.target.style.height = "auto";
              e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`;
            }}
            onKeyDown={handleKeyDown}
          />
          {speechSupported && (
            <button
              className={`mic-btn ${listening ? "mic-btn--live" : ""}`}
              onClick={handleVoice}
              disabled={loading}
              aria-label={listening ? "Stop listening" : "Speak your question"}
              title={listening ? "Listening…" : "Voice input"}
            >
              <IconMic />
            </button>
          )}
          <button
            className="send-btn"
            onClick={() => void handleSend()}
            disabled={!input.trim() || loading}
            aria-label="Send"
          >
            <IconSend />
          </button>
        </div>
      </div>
    </div>
  );
}