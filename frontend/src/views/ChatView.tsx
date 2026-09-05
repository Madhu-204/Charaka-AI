import { useCallback, useEffect, useRef, useState } from "react";
import { ask, feedbackPayload, submitFeedback } from "../api";
import { buildChatCitations, stepsFromTrace, savedFromMessage } from "../lib/format";
import { addSaved } from "../lib/saved";
import type { ChatMessage, FeedbackRating } from "../types";
import type { ReasoningContent } from "../components/ReasoningPanel";
import { ChatBubble } from "../components/ChatBubble";
import { IconChat, IconLeaf, IconSend } from "../components/Icons";

interface ChatViewProps {
  onReasoning: (content: ReasoningContent | null) => void;
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
    showSearch: true,
  };
}

export function ChatView({ onReasoning }: ChatViewProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const feedRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const scrollToBottom = useCallback(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading, scrollToBottom]);

  useEffect(() => {
    onReasoning(null);
    textareaRef.current?.focus();
  }, [onReasoning]);

  async function handleSend(text?: string) {
    const query = (text ?? input).trim();
    if (!query || loading) return;

    const userMsg: ChatMessage = {
      id: newId(),
      role: "user",
      content: query,
      createdAt: Date.now(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setError(null);
    setLoading(true);

    try {
      const res = await ask(query);
      const assistantMsg: ChatMessage = {
        id: newId(),
        role: "assistant",
        content: res.answer,
        query,
        createdAt: Date.now(),
        isEmergency: res.is_emergency,
        confidence: res.confidence,
        chapter: res.chapter,
        categoryTag: res.category_tag,
        dosha: res.dosha,
        safetyFlags: res.safety_flags,
        reasoning: res.reasoning_trace ?? null,
        feedback: null,
        showReasoning: false,
        saved: false,
      };
      setMessages((prev) => [...prev, assistantMsg]);
      onReasoning(reasoningFor(assistantMsg));
    } catch (e) {
      setError(
        e instanceof Error && "status" in e
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

  return (
    <div className="chat-view">
      <div className="chat-feed" ref={feedRef}>
        {messages.length === 0 && !loading && (
          <div className="chat-feed__empty">
            <IconLeaf width={42} height={42} />
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
            onFeedback={handleFeedback}
            onToggleReasoning={handleToggleReasoning}
            onSave={handleSave}
          />
        ))}

        {loading && (
          <div className="msg msg--assistant">
            <div className="msg__bubble">
              <div className="typing">
                <span />
                <span />
                <span />
              </div>
            </div>
          </div>
        )}
      </div>

      {error && <div className="chat-error">{error}</div>}

      <div className="chat-input-bar">
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