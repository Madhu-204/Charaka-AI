import { useMemo, useState } from "react";
import type { Citation, TraceCheck, TraceCheckKind } from "../types";
import { IconAlert, IconCheck, IconScroll, IconSearch, IconShield } from "./Icons";

export interface ReasoningContent {
  steps: string[];
  citations: Citation[];
  showSearch?: boolean;
  checks?: TraceCheck[];
  primarySource?: Citation | null;
  herbs?: Citation[];
}

interface ReasoningPanelProps {
  content: ReasoningContent | null;
  onClose: () => void;
}

const CHECK_LABEL: Record<TraceCheckKind, string> = {
  emergency: "Emergency",
  pattern: "Pattern",
  source: "Source",
  safety: "Safety",
};

function CheckIcon({ kind }: { kind: TraceCheckKind }) {
  const props = { width: 13, height: 13 };
  switch (kind) {
    case "emergency":
      return <IconShield {...props} />;
    case "pattern":
      return <IconCheck {...props} />;
    case "source":
      return <IconScroll {...props} />;
    case "safety":
      return <IconAlert {...props} />;
  }
}

function badgeClass(badge?: Citation["badge"]): string {
  switch (badge) {
    case "verified":
      return "badge--verified";
    case "api":
      return "badge--api";
    case "ref":
      return "badge--ref";
    case "ai":
      return "badge--ai";
    case "safety":
      return "badge--ai";
    default:
      return "badge--neutral";
  }
}

function stagger(i: number, base = 80): React.CSSProperties {
  return { animationDelay: `${i * base}ms` } as React.CSSProperties;
}

export function ReasoningPanel({ content, onClose }: ReasoningPanelProps) {
  const [query, setQuery] = useState("");

  const citations = useMemo(() => {
    if (!content) return [];
    if (!query.trim()) return content.citations;
    const q = query.toLowerCase();
    return content.citations.filter(
      (c) =>
        c.title.toLowerCase().includes(q) ||
        c.detail.toLowerCase().includes(q) ||
        (c.badgeText ?? "").toLowerCase().includes(q)
    );
  }, [content, query]);

  function badgeSpan(badge?: Citation["badge"], badgeText?: string) {
    if (!badge || !badgeText) return null;
    return <span className={`badge ${badgeClass(badge)}`}>{badgeText}</span>;
  }

  const panelKey = content?.steps?.join("||") ?? "empty";
  const checks = content?.checks;
  const checksLen = checks?.length ?? 0;

  return (
    <aside className="reasoning-panel">
      <h2>
        <span>Sources &amp; Reasoning</span>
        <button className="icon-btn" onClick={onClose} title="Close panel" aria-label="Close panel">
          ✕
        </button>
      </h2>

      {content ? (
        checks ? (
          <div key={`checks-${panelKey}`} className="stagger-group">
            <div className="reason-trace">
              {checks.length > 0 ? (
                checks.map((c, i) => (
                  <div className="reason-step chat-reveal" key={c.kind} style={stagger(i)}>
                    <span className="reason-step__icon">
                      <CheckIcon kind={c.kind} />
                    </span>
                    <div className="reason-step__body">
                      <div className="reason-step__label">{CHECK_LABEL[c.kind]}</div>
                      <div className="reason-step__status">{c.status}</div>
                    </div>
                  </div>
                ))
              ) : (
                <div className="reason-step__status">Awaiting a query…</div>
              )}
            </div>

            {(content.primarySource || (content.herbs && content.herbs.length > 0)) && (
              <div className="reason-boxes">
                <div className="reason-box chat-reveal" style={stagger(checksLen)}>
                  <div className="reason-box__label">Received: sourced from</div>
                  {content.primarySource ? (
                    <div className="source-item">
                      <div className="source-item__title">
                        {content.primarySource.title}
                        {badgeSpan(content.primarySource.badge, content.primarySource.badgeText)}
                      </div>
                      <div className="source-item__meta">{content.primarySource.detail}</div>
                    </div>
                  ) : (
                    <div className="reason-box__empty">No source returned for this reply.</div>
                  )}
                </div>

                <div className="reason-box chat-reveal" style={stagger(checksLen + 1)}>
                  <div className="reason-box__label">Herb found &amp; safety</div>
                  {content.herbs && content.herbs.length > 0 ? (
                    <>
                      {content.herbs.slice(0, 5).map((h, i) => (
                        <div className="source-item chat-reveal" key={i} style={stagger(checksLen + 2 + i, 60)}>
                          <div className="source-item__title">
                            {h.title}
                            {badgeSpan(h.badge, h.badgeText)}
                          </div>
                          <div className="source-item__meta">{h.detail}</div>
                        </div>
                      ))}
                      {content.herbs.length > 5 && (
                        <div className="reason-box__more">
                          + {content.herbs.length - 5} more herb(s) in detailed list
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="reason-box__empty">No herbs detected in this query.</div>
                  )}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div key={`trace-${panelKey}`} className="stagger-group">
            <label className="reasoning-search-wrap">
              <IconSearch width={15} height={15} />
              <input
                className="reasoning-search"
                placeholder="Search Classical Texts..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>

            <div className="inline-reason">
              <div className="inline-reason__title">Reasoning trace</div>
              {content.steps.length > 0 ? (
                content.steps.map((step, i) => (
                  <div className="timeline__step chat-reveal" key={i} style={stagger(i, 60)}>
                    <span>{step}</span>
                  </div>
                ))
              ) : (
                <div className="timeline__step">Awaiting a query…</div>
              )}
            </div>

            <div className="citations">
              <div className="citations__header">
                Detailed sources {citations.length > 0 && `(${citations.length})`}
              </div>
              {citations.length === 0 && <div className="empty-state">No matching sources.</div>}
              {citations.map((c, i) => (
                <div className="citation-card chat-reveal" key={i} style={stagger(content.steps.length + i, 60)}>
                  <div className="citation-card__top">
                    <span className="citation-card__title">{c.title}</span>
                    {badgeSpan(c.badge, c.badgeText)}
                  </div>
                  <div className="citation-card__detail">{c.detail}</div>
                </div>
              ))}
            </div>
          </div>
        )
      ) : (
        <div className="empty-state">
          <span style={{ display: "block", marginBottom: 6 }}>
            <IconShield />
          </span>
          Ask a question in Chat and the retrieval, dosha and safety steps will appear here.
        </div>
      )}
    </aside>
  );
}
