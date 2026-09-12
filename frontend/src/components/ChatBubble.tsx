import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import type { ChatMessage, FeedbackRating } from "../types";
import {
  buildChatCitations,
  chapterLabel,
  confidencePercent,
  inlineCitations,
  stepsFromTrace,
  categoryLabel,
} from "../lib/format";
import {
  IconBook,
  IconBookmark,
  IconBookmarkFilled,
  IconCheck,
  IconChevronDown,
  IconCopy,
  IconInfo,
  IconLeaf,
  IconRefresh,
  IconShield,
  IconThumbDown,
  IconThumbUp,
} from "./Icons";

interface ChatBubbleProps {
  message: ChatMessage;
  onFeedback: (id: string, rating: FeedbackRating) => void;
  onToggleReasoning: (id: string) => void;
  onSave: (id: string) => void;
  onSuggestion?: (text: string) => void;
  onRegenerate?: (query: string) => void;
  isNew?: boolean;
  onContentChange?: () => void;
}

function CiteLink({
  href,
  children,
  onCite,
}: {
  href?: string;
  children: React.ReactNode;
  onCite: (n: number) => void;
}) {
  const match = /^#cite-(\d+)$/.exec(href ?? "");
  if (match) {
    const n = parseInt(match[1], 10);
    return (
      <button
        type="button"
        className="cite-chip"
        title={`View source ${n}`}
        aria-label={`View source ${n}`}
        onClick={() => onCite(n)}
      >
        <span className="cite-chip__num">{n}</span>
      </button>
    );
  }
  return (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}

function confidenceWidth(msg: ChatMessage): number {
  const score = msg.reasoning?.confidence_score;
  if (score != null) return confidencePercent(score) ?? 30;
  switch (msg.confidence) {
    case "high":
      return 85;
    case "medium":
      return 58;
    case "low":
      return 30;
    default:
      return 30;
  }
}

export function ChatBubble({
  message,
  onFeedback,
  onToggleReasoning,
  onSave,
  onSuggestion,
  onRegenerate,
  isNew,
  onContentChange,
}: ChatBubbleProps) {
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [activeCite, setActiveCite] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);
  const [displayedChars, setDisplayedChars] = useState(() =>
    isNew ? 0 : message.content.length,
  );
  const sourcesBodyRef = useRef<HTMLDivElement>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const streaming = message.streaming === true;
  const visibleContent = streaming
    ? message.content
    : message.content.slice(0, displayedChars);
  const isTyping = !streaming && displayedChars < message.content.length;
  const isTyped = !streaming && displayedChars >= message.content.length;

  // Typewriter — mount-only, reveals content at ~200 chars/sec. Skipped for
  // streaming messages: tokens arrive from the SSE stream live instead.
  useEffect(() => {
    if (!isNew || streaming) return;
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

  // When a streaming message finishes, settle the typewriter state instantly
  const wasStreamingRef = useRef<boolean>(streaming);
  useEffect(() => {
    if (wasStreamingRef.current && !streaming) {
      setDisplayedChars(message.content.length);
      wasStreamingRef.current = false;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [streaming]);

  // When typing/streaming completes, let metadata settle before scrolling
  const completedRef = useRef(false);
  useEffect(() => {
    if (!isNew) return;
    if ((isTyped || !streaming) && !completedRef.current) {
      completedRef.current = true;
      const t = setTimeout(() => {
        onContentChange?.();
      }, 80);
      return () => clearTimeout(t);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isTyped, isNew, streaming, onContentChange]);

  const citations = buildChatCitations(message);
  const rt = message.reasoning;
  const steps = stepsFromTrace(rt?.steps);
  const isEmergency = message.isEmergency === true;

  const g = message.reasoning?.grounding;
  const gPct = confidencePercent(g?.score);
  const latency = message.latencyMs ?? null;
  const stages = message.stages ?? [];

  function handleCite(n: number) {
    setSourcesOpen(true);
    setActiveCite(n);
    requestAnimationFrame(() => {
      const el = sourcesBodyRef.current?.querySelector(
        `[data-cite-index="${CSS.escape(String(n))}"]`,
      );
      el?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
    window.setTimeout(() => setActiveCite(null), 2400);
  }

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard unavailable */
    }
  }

  function renderSourceItem(c: (typeof citations)[number], i: number) {
    const pct = c.score != null ? confidencePercent(c.score) : null;
    return (
      <div
        className={`source-item chat-reveal ${
          activeCite === c.citeIndex ? "source-item--active" : ""
        }`}
        key={i}
        data-cite-index={c.citeIndex}
        style={{ animationDelay: `${i * 50}ms` }}
      >
        <div className="source-item__top">
          <span className="source-item__title">
            {c.citeIndex != null && <span className="cite-num">{c.citeIndex}</span>}
            {c.title}
          </span>
          {c.badge && (
            <span className={`badge ${c.badge === "ai" ? "badge--ai" : "badge--neutral"}`}>
              {c.badgeText}
            </span>
          )}
        </div>
        <div className="source-item__meta">{c.detail}</div>
        {c.verseText && (
          <p className="verse-text">
            <span className="verse-text__label">Verse</span>
            {c.verseText}
          </p>
        )}
        {pct != null && (
          <div className="similarity-bar" title={`Similarity ${pct}%`}>
            <div
              className="similarity-bar__fill"
              style={{ width: `${pct}%` }}
            />
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      className={`msg ${message.role === "user" ? "msg--user" : "msg--assistant"} ${
        isEmergency ? "msg--emergency" : ""
      }`}
    >
      <div className="msg__bubble">
        {isTyped && message.summary && message.summary.title !== "" && (
          <div className="msg__summary chat-reveal" style={{ animationDelay: "0ms" }}>
            <div className="msg__summary-title">{message.summary.title}</div>
            {message.summary.takeaways.length > 0 && (
              <ul className="msg__summary-takeaways">
                {message.summary.takeaways.map((t, i) => (
                  <li key={i}>{t}</li>
                ))}
              </ul>
            )}
            {message.summary.doctor_check.length > 0 && (
              <div className="msg__summary-doc">
                <IconShield width={13} height={13} />
                {message.summary.doctor_check.map((d, i) => (
                  <span key={i}>{d}</span>
                ))}
              </div>
            )}
          </div>
        )}
        <div className="md-body">
          <ReactMarkdown
            components={{
              a: (props) => (
                <CiteLink href={props.href} onCite={handleCite}>
                  {props.children}
                </CiteLink>
              ),
            }}
          >
            {inlineCitations(visibleContent)}
          </ReactMarkdown>
          {(isTyping || streaming) && <span className="chat-cursor">|</span>}
        </div>
      </div>

      {streaming && stages.length > 0 && (
        <div className="chat-stages chat-reveal">
          {stages.map((s, i) => (
            <span
              key={i}
              className={`chat-stage ${
                i === stages.length - 1 && streaming
                  ? "chat-stage--live"
                  : "chat-stage--done"
              }`}
            >
              <span className="chat-stage__dot" />
              {s.label}
              {s.ms > 0 && <span className="chat-stage__ms">{s.ms}ms</span>}
            </span>
          ))}
        </div>
      )}

      {message.role === "assistant" && (isTyping || streaming) && (
        <div className="chat-generating">
          <span className="chat-generating__dot" />
          <span className="chat-generating__dot" />
          <span className="chat-generating__dot" />
          <span>{streaming ? "Retrieving & generating…" : "Generating…"}</span>
        </div>
      )}

      {message.role === "assistant" && isTyped && (
        <>
          {message.isClarification && (
            <div className="msg__meta chat-reveal" style={{ animationDelay: "0ms" }}>
              <span className="badge badge--ai">
                <IconInfo width={14} height={14} />
                Need a bit more detail
              </span>
            </div>
          )}
          {(message.dosha || message.confidence || message.chapter || gPct != null || latency) && (
            <div className="msg__meta chat-reveal" style={{ animationDelay: "0ms" }}>
              {message.dosha && (
                <span className="badge chip-dosha">
                  <IconLeaf width={13} height={13} />
                  {message.dosha} pattern
                </span>
              )}
              {message.confidence && (
                <span className="badge chip-confidence" title={`Similarity ${gPct ?? "n/a"}%`}>
                  <span>Confidence</span>
                  <span className="confidence-gauge">
                    <span
                      className="confidence-gauge__fill"
                      style={{ width: `${confidenceWidth(message)}%` }}
                    />
                  </span>
                  <span>{message.confidence}</span>
                </span>
              )}
              {gPct != null && (
                <span className="badge chip-grounding" title={g?.notes.join(" · ")}>
                  {gPct >= 66 ? "Grounded" : gPct >= 33 ? "Partially grounded" : "Weakly grounded"}
                  · {gPct}%
                </span>
              )}
              {message.chapter && (
                <span className="badge chip-confidence">{chapterLabel(message.chapter)}</span>
              )}
              {latency != null && (
                <span className="badge chip-latency">{latency}ms</span>
              )}
            </div>
          )}

          {isEmergency && (
            <div className="msg__meta chat-reveal" style={{ animationDelay: "0ms" }}>
              <span className="badge badge--ai">
                <IconShield width={13} height={13} />
                Emergency redirect
              </span>
              {message.categoryTag && (
                <span className="badge chip-confidence">{categoryLabel(message.categoryTag)}</span>
              )}
            </div>
          )}

          {!isEmergency && message.safetyFlags && message.safetyFlags.length > 0 && (
            <div className="safety-note chat-reveal" style={{ animationDelay: "60ms" }}>
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

          {!isEmergency &&
            (message.confidence === "low" ||
              (gPct != null && gPct < 33) ||
              (message.reasoning?.source_disagreements ?? []).length > 0) && (
              <div className="safety-band chat-reveal" style={{ animationDelay: "90ms" }}>
                <IconShield width={15} height={15} />
                <div>
                  <strong>Keep this in mind:</strong> the classical match here is
                  uncertain — treat it as general wellness information and see a
                  doctor if symptoms persist or worsen.
                  {(message.reasoning?.source_disagreements ?? []).length > 0 && (
                    <>
                      <br />
                      Sources flag cautions for herbs mentioned in this reply — check
                      the reasoning trace.
                    </>
                  )}
                </div>
              </div>
            )}

          {!isEmergency && (
            <div className="msg__sources chat-reveal" style={{ animationDelay: "120ms" }}>
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
                {sourcesOpen && (
                  <div className="sources-row__body" ref={sourcesBodyRef}>
                    {citations.length === 0 ? (
                      <div className="source-item">
                        <div className="source-item__meta">
                          No verse-level sources available for this reply.
                        </div>
                      </div>
                    ) : (
                      citations.map(renderSourceItem)
                    )}
                  </div>
                )}
              </div>
            </div>
          )}

          {!isEmergency && message.showReasoning && (
            <div className="inline-reason chat-reveal" style={{ animationDelay: "0ms" }}>
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
            <div className="msg__actions chat-reveal" style={{ animationDelay: "180ms" }}>
              <button
                className={`icon-btn ${message.feedback === "up" ? "icon-btn--active" : ""}`}
                onClick={() => onFeedback(message.id, "up")}
                title="Helpful"
                aria-label="Mark helpful"
              >
                <IconThumbUp width={16} height={16} />
              </button>
              <button
                className={`icon-btn ${message.feedback === "down" ? "icon-btn--active" : ""}`}
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

              <button
                className={`icon-btn ${copied ? "icon-btn--active" : ""}`}
                onClick={() => void handleCopy()}
                title={copied ? "Copied!" : "Copy answer"}
                aria-label="Copy answer"
              >
                {copied ? (
                  <IconCheck width={16} height={16} />
                ) : (
                  <IconCopy width={16} height={16} />
                )}
              </button>

              <button
                className="icon-btn"
                onClick={() => onRegenerate?.(message.query ?? "")}
                title="Regenerate answer"
                aria-label="Regenerate answer"
                disabled={!message.query}
              >
                <IconRefresh width={16} height={16} />
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

          {!isEmergency &&
            message.suggestions &&
            message.suggestions.length > 0 &&
            onSuggestion && (
              <div
                className="msg__suggestions chat-reveal"
                style={{ animationDelay: "300ms" }}
              >
                <span className="msg__suggestions-label">You could ask next</span>
                <div className="msg__suggestions-list">
                  {message.suggestions.map((s, i) => (
                    <button
                      key={i}
                      className="pill pill--suggestion"
                      onClick={() => onSuggestion(s)}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
        </>
      )}
    </div>
  );
}