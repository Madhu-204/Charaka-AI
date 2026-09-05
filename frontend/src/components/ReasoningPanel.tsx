import { useMemo, useState } from "react";
import type { Citation } from "../types";
import { IconSearch, IconShield } from "./Icons";

export interface ReasoningContent {
  steps: string[];
  citations: Citation[];
  showSearch?: boolean;
}

interface ReasoningPanelProps {
  content: ReasoningContent | null;
  onClose: () => void;
}

function badgeClass(badge?: Citation["badge"]): string {
  switch (badge) {
    case "verified":
      return "badge--verified";
    case "api":
      return "badge--api";
    case "ai":
      return "badge--ai";
    case "safety":
      return "badge--ai";
    default:
      return "badge--neutral";
  }
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

  return (
    <aside className="reasoning-panel">
      <h2>
        <span>Sources &amp; Reasoning</span>
        <button className="icon-btn" onClick={onClose} title="Close panel" aria-label="Close panel">
          ✕
        </button>
      </h2>

      <label className="reasoning-search-wrap">
        <IconSearch width={15} height={15} />
        <input
          className="reasoning-search"
          placeholder="Search Classical Texts..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>

      {content ? (
        <>
          <div className="timeline">
            <div className="timeline__header">Execution timeline</div>
            {content.steps.map((step, i) => (
              <div className="timeline__step" key={i}>
                <span>{step}</span>
              </div>
            ))}
            {content.steps.length === 0 && (
              <div className="timeline__step">Awaiting a query…</div>
            )}
          </div>

          <div className="citations">
            <div className="citations__header">
              Citations {citations.length > 0 && `(${citations.length})`}
            </div>
            {citations.length === 0 && (
              <div className="empty-state">No matching sources.</div>
            )}
            {citations.map((c, i) => (
              <div className="citation-card" key={i}>
                <div className="citation-card__top">
                  <span className="citation-card__title">{c.title}</span>
                  {c.badge && (
                    <span className={`badge ${badgeClass(c.badge)}`}>{c.badgeText}</span>
                  )}
                </div>
                <div className="citation-card__detail">{c.detail}</div>
              </div>
            ))}
          </div>
        </>
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