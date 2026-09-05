import { useMemo, useState } from "react";
import type { SavedAnswer } from "../types";
import { categoryLabel, buildChatCitations, stepsFromTrace } from "../lib/format";
import { loadSaved, removeSaved } from "../lib/saved";
import type { ReasoningContent } from "../components/ReasoningPanel";
import {
  IconBookmark,
  IconChevronLeft,
  IconChevronRight,
  IconSearch,
} from "../components/Icons";

interface SavedAnswersViewProps {
  onReasoning: (content: ReasoningContent | null) => void;
}

const PAGE_SIZE = 4;

function reasoningFor(saved: SavedAnswer): ReasoningContent {
  return {
    steps: stepsFromTrace(saved.reasoning?.steps),
    citations: buildChatCitations({ reasoning: saved.reasoning }),
    showSearch: true,
  };
}

export function SavedAnswersView({ onReasoning }: SavedAnswersViewProps) {
  const [items, setItems] = useState<SavedAnswer[]>(() => loadSaved());
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [page, setPage] = useState(0);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (s) =>
        s.title.toLowerCase().includes(q) ||
        s.answer.toLowerCase().includes(q) ||
        (s.dosha ?? "").toLowerCase().includes(q)
    );
  }, [items, query]);

  const groups = useMemo(() => {
    const map = new Map<string, SavedAnswer[]>();
    for (const s of filtered) {
      const key = categoryLabel(s.category_tag);
      const arr = map.get(key);
      if (arr) arr.push(s);
      else map.set(key, [s]);
    }
    return Array.from(map.entries());
  }, [filtered]);

  const pages = Math.max(1, Math.ceil(groups.length / PAGE_SIZE));
  const safePage = Math.min(page, pages - 1);
  const visibleGroups = groups.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE);

  function handleRemove(id: string) {
    setItems(removeSaved(id));
    if (expanded === id) {
      setExpanded(null);
      onReasoning(null);
    }
  }

  function toggleExpand(s: SavedAnswer) {
    if (expanded === s.id) {
      setExpanded(null);
      onReasoning(null);
    } else {
      setExpanded(s.id);
      onReasoning(reasoningFor(s));
    }
  }

  return (
    <div className="view-scroll">
      <div className="herb-toolbar">
        <div className="search-field">
          <IconSearch width={17} height={17} />
          <input
            placeholder="Search saved answers..."
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(0);
            }}
          />
        </div>
        <span className="count-label" style={{ marginBottom: 0 }}>
          {filtered.length} saved
        </span>
      </div>

      {filtered.length === 0 && (
        <div className="saved-empty">
          <IconBookmark width={34} height={34} style={{ opacity: 0.5 }} />
          <p>
            {query
              ? "No saved answers match your search."
              : "Nothing saved yet — hit the bookmark on any chat answer to keep it here."}
          </p>
        </div>
      )}

      <div className="saved-sections">
        {visibleGroups.map(([label, entries]) => (
          <section key={label}>
            <div className="saved-section__header">
              <span>Category: {label}</span>
            </div>
            <div className="saved-grid">
              {entries.map((s) => {
                const isOpen = expanded === s.id;
                return (
                  <div className="saved-card" key={s.id}>
                    <div className="saved-card__title">
                      {label}
                      {s.dosha && <span className="badge chip-dosha">{s.dosha}</span>}
                    </div>
                    <div className="saved-card__snippet">{s.snippet}</div>
                    {isOpen && (
                      <div
                        className="inline-reason"
                        style={{ marginTop: 2 }}
                      >
                        <div className="inline-reason__title">Sources ({buildChatCitations({ reasoning: s.reasoning }).length})</div>
                        {buildChatCitations({ reasoning: s.reasoning })
                          .slice(0, 4)
                          .map((c, i) => (
                            <div className="source-item" key={i}>
                              <div className="source-item__title">{c.title}</div>
                              <div className="source-item__meta">{c.detail}</div>
                            </div>
                          ))}
                      </div>
                    )}
                    <div className="saved-card__actions">
                      <button className="btn" onClick={() => toggleExpand(s)}>
                        {isOpen ? "Collapse" : "Learn More"}
                      </button>
                      <button
                        className="btn btn--terracotta"
                        onClick={() => handleRemove(s.id)}
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        ))}
      </div>

      {pages > 1 && (
        <div className="pagination">
          <button
            disabled={safePage === 0}
            onClick={() => setPage(safePage - 1)}
            aria-label="Previous page"
          >
            <IconChevronLeft width={16} height={16} />
          </button>
          <div className="pagination__dots">
            {Array.from({ length: pages }).map((_, i) => (
              <span key={i} className={i === safePage ? "active" : ""} />
            ))}
          </div>
          <button
            disabled={safePage >= pages - 1}
            onClick={() => setPage(safePage + 1)}
            aria-label="Next page"
          >
            <IconChevronRight width={16} height={16} />
          </button>
        </div>
      )}
    </div>
  );
}