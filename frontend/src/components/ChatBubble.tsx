import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import type { ChatMessage, FeedbackRating } from "../types";
import { buildChatCitations, chapterLabel, stepsFromTrace, categoryLabel } from "../lib/format";
import {
  IconBook,
  IconBookmark,
  IconBookmarkFilled,
  IconChevronDown,
  IconLeaf,
  IconShield,
  IconThumbDown,
  IconThumbUp,
} from "./Icons";

interface ChatBubbleProps {
  message: ChatMessage;
  onFeedback: (id: string, rating: FeedbackRating) => void;
  onToggleReasoning: (id: string) => void;
  onSave: (id: string) => void;
  isNew?: boolean;
  onContentChange?: () => void;
}

export function ChatBubble({
  message,
  onFeedback,
  onToggleReasoning,
  onSave,
  isNew,
  onContentChange,
}: ChatBubbleProps) {
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [displayedChars, setDisplayedChars] = useState(
    isNew ? 0 : message.content.length,
  );

  const isTyping = displayedChars < message.content.length;
  const isTyped = displayedChars >= message.content.length;

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Typewriter — mount-only, reveals content at ~200 chars/sec
  useEffect(() => {
    if (!isNew) return;
    const target = message.content.length;
    if (target === 0) return;

    const charsPerTick = Math.max(3, Math.ceil(target / 180));
    let current = 0;

    intervalRef.current = setInterval(() => {
      current = Math.min(current + charsPerTick, target);
      setDisplayedChars(current);
      onContentChange?.();
      if (current >= target) {
        clearInterval(intervalRef.current!);
        intervalRef.current = null;
      }
    }, 18);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // If isNew flips to false before typewriter finishes, complete instantly
  useEffect(() => {
    if (!isNew && displayedChars < message.content.length) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      setDisplayedChars(message.content.length);
    }
  }, [isNew, displayedChars, message.content.length]);

  // When typing completes, let metadata settle before scrolling to bottom
  const completedRef = useRef(false);
  useEffect(() => {
    if (!isNew) return;
    if (isTyped && !completedRef.current) {
      completedRef.current = true;
      const t = setTimeout(() => {
        onContentChange?.();
      }, 80);
      return () => clearTimeout(t);
    }
  }, [isTyped, isNew, onContentChange]);

  const citations = buildChatCitations(message);
  const rt = message.reasoning;
  const steps = stepsFromTrace(rt?.steps);
  const isEmergency = message.isEmergency === true;

  return (
    <div
      className={`msg ${message.role === "user" ? "msg--user" : "msg--assistant"} ${
        isEmergency ? "msg--emergency" : ""
      }`}
    >
      <div className="msg__bubble">
        <div className="md-body">
          <ReactMarkdown>{message.content.slice(0, displayedChars)}</ReactMarkdown>
          {isTyping && <span className="chat-cursor">|</span>}
        </div>
      </div>

      {message.role === "assistant" && isTyping && (
        <div className="chat-generating">
          <span className="chat-generating__dot" />
          <span className="chat-generating__dot" />
          <span className="chat-generating__dot" />
          <span>Generating…</span>
        </div>
      )}

      {message.role === "assistant" && isTyped && (
        <>
          {(message.dosha || message.confidence || message.chapter) && (
            <div
              className="msg__meta chat-reveal"
              style={{ animationDelay: "0ms" }}
            >
              {message.dosha && (
                <span className="badge chip-dosha">
                  <IconLeaf width={13} height={13} />
                  {message.dosha} pattern
                </span>
              )}
              {message.confidence && (
                <span className="badge chip-confidence">
                  Confidence: {message.confidence}
                </span>
              )}
              {message.chapter && (
                <span className="badge chip-confidence">
                  {chapterLabel(message.chapter)}
                </span>
              )}
            </div>
          )}

          {isEmergency && (
            <div
              className="msg__meta chat-reveal"
              style={{ animationDelay: "0ms" }}
            >
              <span className="badge badge--ai">
                <IconShield width={13} height={13} />
                Emergency redirect
              </span>
              {message.categoryTag && (
                <span className="badge chip-confidence">
                  {categoryLabel(message.categoryTag)}
                </span>
              )}
            </div>
          )}

          {!isEmergency && message.safetyFlags && message.safetyFlags.length > 0 && (
            <div
              className="safety-note chat-reveal"
              style={{ animationDelay: "60ms" }}
            >
              <div className="safety-note__heading">
                <IconShield width={15} height={15} />
                Safety note
              </div>
              <ul>
                {message.safetyFlags.slice(0, 4).map((flag, i) => (
                  <li key={i}>{flag}</li>
                ))}
              </ul>
            </div>
          )}

          {!isEmergency && (
            <div
              className="msg__sources chat-reveal"
              style={{ animationDelay: "120ms" }}
            >
              <div className="sources-row">
                <button
                  className="sources-row__trigger"
                  aria-expanded={sourcesOpen}
                  onClick={() => setSourcesOpen((o) => !o)}
                >
                  <IconBook width={16} height={16} />
                  <span>Sources ({citations.length})</span>
                  <IconChevronDown className="chev" width={15} height={15} />
                </button>
                {sourcesOpen && citations.length > 0 && (
                  <div className="sources-row__body">
                    {citations.map((c, i) => (
                      <div
                        className="source-item chat-reveal"
                        key={i}
                        style={{ animationDelay: `${i * 50}ms` }}
                      >
                        <div className="source-item__title">
                          {c.title}
                          {c.badge && (
                            <span
                              className={`badge ${
                                c.badge === "ai" ? "badge--ai" : "badge--neutral"
                              }`}
                            >
                              {c.badgeText}
                            </span>
                          )}
                        </div>
                        <div className="source-item__meta">{c.detail}</div>
                      </div>
                    ))}
                  </div>
                )}
                {sourcesOpen && citations.length === 0 && (
                  <div className="sources-row__body">
                    <div className="source-item">
                      <div className="source-item__meta">
                        No verse-level sources available for this reply.
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {!isEmergency && message.showReasoning && (
            <div
              className="inline-reason chat-reveal"
              style={{ animationDelay: "0ms" }}
            >
              <div className="inline-reason__title">Reasoning trace</div>
              {steps.length > 0 ? (
                steps.map((s, i) => (
                  <div
                    className="timeline__step chat-reveal"
                    key={i}
                    style={{ animationDelay: `${i * 50}ms` }}
                  >
                    <span>{s}</span>
                  </div>
                ))
              ) : (
                <div className="source-item__meta">No trace recorded.</div>
              )}
            </div>
          )}

          {!isEmergency && (
            <div
              className="msg__actions chat-reveal"
              style={{ animationDelay: "180ms" }}
            >
              <button
                className={`icon-btn ${
                  message.feedback === "up" ? "icon-btn--active" : ""
                }`}
                onClick={() => onFeedback(message.id, "up")}
                title="Helpful"
                aria-label="Mark helpful"
              >
                <IconThumbUp width={16} height={16} />
              </button>
              <button
                className={`icon-btn ${
                  message.feedback === "down" ? "icon-btn--active" : ""
                }`}
                onClick={() => onFeedback(message.id, "down")}
                title="Not helpful"
                aria-label="Mark not helpful"
              >
                <IconThumbDown width={16} height={16} />
              </button>
              <button
                className={`icon-btn ${message.saved ? "icon-btn--saved" : ""}`}
                onClick={() => onSave(message.id)}
                title={message.saved ? "Saved" : "Save answer"}
                aria-label="Save answer"
              >
                {message.saved ? (
                  <IconBookmarkFilled width={16} height={16} />
                ) : (
                  <IconBookmark width={16} height={16} />
                )}
              </button>

              <label className="toggle">
                <span>Show reasoning</span>
                <button
                  className="toggle__switch"
                  role="switch"
                  aria-checked={message.showReasoning === true}
                  onClick={() => onToggleReasoning(message.id)}
                />
              </label>
            </div>
          )}
        </>
      )}
    </div>
  );
}
