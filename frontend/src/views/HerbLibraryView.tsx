import { useEffect, useMemo, useState } from "react";
import { fetchHerbs } from "../api";
import type { HerbSummary } from "../types";
import type { ReasoningContent } from "../components/ReasoningPanel";
import {
  IconChevronLeft,
  IconChevronRight,
  IconSearch,
} from "../components/Icons";

interface HerbLibraryViewProps {
  onReasoning: (content: ReasoningContent | null) => void;
}

const PAGE_SIZE = 9;

const ART_COLORS = ["#C1663D", "#5C6B47", "#8a9a63", "#b98a3e", "#7d5a4b", "#4e7b6c"];

function artColor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return ART_COLORS[h % ART_COLORS.length];
}

function HerbArt({ name }: { name: string }) {
  const color = artColor(name);
  return (
    <svg width="74" height="74" viewBox="0 0 74 74" fill="none" aria-hidden>
      <circle cx="37" cy="37" r="34" fill={color} opacity="0.08" />
      <circle cx="37" cy="37" r="34" stroke={color} strokeWidth="1.4" opacity="0.5" />
      <g stroke={color} strokeWidth="2" strokeLinecap="round" fill="none">
        <path d="M37 52c-12-8-16-22-6-32 12-8 24-3 24 12 0 10-7 16-18 20Z" fill={color} opacity="0.25" />
        <path d="M37 52V44" />
        <path d="M41 27c4-6 10-8 14-6" />
        <circle cx="24" cy="36" r="2.5" fill={color} opacity="0.6" />
        <circle cx="30" cy="24" r="2" fill={color} opacity="0.6" />
      </g>
    </svg>
  );
}

function verificationBadge(h: HerbSummary): { text: string; tone: "verified" | "api" | "ai" } {
  if (h.modern_source_verified) return { text: "Source verified", tone: "verified" };
  if (h.api_of_india_verified) return { text: "Classical API cross-checked", tone: "api" };
  return { text: "AI-compiled, unverified", tone: "ai" };
}

function reasoningFor(h: HerbSummary): ReasoningContent {
  const { text, tone } = verificationBadge(h);
  return {
    steps: [
      "How we verify herb data",
      ...(h.api_of_india_verified
        ? ["Classical rasapanchaka cross-checked against an API of India monograph"]
        : []),
      ...(h.modern_source_verified
        ? ["Modern contraindications matched to a fetched page text"]
        : ["Modern claims not independently verified"]),
      `Catalogue lookup for "${h.name}"`,
    ],
    citations: [
      {
        title: h.name,
        detail: h.botanical ? h.botanical : "Botanical name pending cataloguing",
        badge: tone,
        badgeText: text,
      },
      ...(h.classical_source
        ? [{ title: "Classical source", detail: h.classical_source, badge: "neutral" as const, badgeText: "Retrieved" }]
        : []),
      ...(h.dosha_caution
        ? [{ title: "Dosha caution", detail: h.dosha_caution, badge: "safety" as const, badgeText: "Caution" }]
        : []),
      ...h.contraindications.slice(0, 3).map((c) => ({
        title: "Contraindication",
        detail: c,
        badge: "safety" as const,
        badgeText: "Caution",
      })),
      ...(h.pregnancy_flag
        ? [{ title: "Pregnancy", detail: h.pregnancy_flag, badge: "safety" as const, badgeText: "Caution" }]
        : []),
      ...(h.modern_source
        ? [{ title: "Modern source", detail: h.modern_source.slice(0, 180), badge: "neutral" as const, badgeText: "Cited" }]
        : []),
      ...(h.verification_note
        ? [{ title: "Verification note", detail: h.verification_note.slice(0, 200), badge: "ai" as const, badgeText: "AI-compiled, unverified" }]
        : []),
    ],
    showSearch: true,
  };
}

export function HerbLibraryView({ onReasoning }: HerbLibraryViewProps) {
  const [herbs, setHerbs] = useState<HerbSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [doshaFilter, setDoshaFilter] = useState("all");
  const [verifyFilter, setVerifyFilter] = useState("all");
  const [selected, setSelected] = useState<HerbSummary | null>(null);
  const [page, setPage] = useState(0);

  useEffect(() => {
    fetchHerbs()
      .then(setHerbs)
      .catch(() => {
        /* backend offline — empty state handles it */
      })
      .finally(() => setLoading(false));
  }, []);

  const doshaOptions = useMemo(() => {
    const set = new Set<string>();
    herbs.forEach((h) => h.dosha_tags.forEach((t) => set.add(t)));
    return ["all", ...Array.from(set).sort()];
  }, [herbs]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return herbs.filter((h) => {
      if (q) {
        const hay = `${h.name} ${h.botanical ?? ""} ${h.aliases.join(" ")}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (doshaFilter !== "all" && !h.dosha_tags.includes(doshaFilter)) return false;
      if (verifyFilter === "sv" && !h.modern_source_verified) return false;
      if (verifyFilter === "api" && !h.api_of_india_verified) return false;
      if (verifyFilter === "ai" && (h.modern_source_verified || h.api_of_india_verified)) return false;
      return true;
    });
  }, [herbs, search, doshaFilter, verifyFilter]);

  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pages - 1);
  const visible = filtered.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE);

  function clearSelection() {
    setSelected(null);
    onReasoning(null);
  }

  function toggleSelect(h: HerbSummary) {
    if (selected?.name === h.name) {
      clearSelection();
    } else {
      setSelected(h);
      onReasoning(reasoningFor(h));
    }
  }

  return (
    <div className="view-scroll">
      <div className="herb-toolbar">
        <div className="search-field">
          <IconSearch width={17} height={17} />
          <input
            placeholder="Search for an herb..."
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(0);
            }}
          />
        </div>
        <select
          className="filter-drop"
          value={doshaFilter}
          onChange={(e) => {
            setDoshaFilter(e.target.value);
            setPage(0);
          }}
          aria-label="Filter by dosha"
        >
          <option value="all">Dosha: All</option>
          {doshaOptions
            .filter((d) => d !== "all")
            .map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
        </select>
        <select
          className="filter-drop"
          value={verifyFilter}
          onChange={(e) => {
            setVerifyFilter(e.target.value);
            setPage(0);
          }}
          aria-label="Filter by verification status"
        >
          <option value="all">Verification: All</option>
          <option value="sv">Source verified</option>
          <option value="api">Classical API cross-checked</option>
          <option value="ai">AI-compiled, unverified</option>
        </select>
      </div>

      {loading && <div className="empty-state">Loading herb catalogue…</div>}

      {!loading && herbs.length === 0 && (
        <div className="empty-state">
          Herb catalogue unavailable — is the backend running on port 8000?
        </div>
      )}

      {!loading && herbs.length > 0 && (
        <>
          <div className="count-label">
            Showing {visible.length} of {filtered.length} herbs
          </div>
          <div className="herb-grid">
            {visible.map((h) => {
              const v = verificationBadge(h);
              const isSel = selected?.name === h.name;
              return (
                <div className={`herb-card ${isSel ? "herb-card--selected" : ""}`} key={h.name}>
                  <div className="herb-card__art">
                    <HerbArt name={h.name} />
                  </div>
                  <div className="herb-card__name">{h.name}</div>
                  <div className="herb-card__botanical">
                    {h.botanical ?? "Botanical name pending"}
                  </div>
                  <div className="herb-card__tags">
                    {h.dosha_tags.map((t) => (
                      <span className="tag" key={t}>
                        {t}
                      </span>
                    ))}
                    <span
                      className={v.tone === "verified" ? "tag tag--verified" : v.tone === "ai" ? "tag tag--ai" : "tag tag--api"}
                    >
                      {v.text}
                    </span>
                  </div>
                  <div className="herb-card__actions">
                    <button className="btn" onClick={() => toggleSelect(h)}>
                      {isSel ? "Collapse" : "Learn More"}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>

          {selected && (
            <div className="herb-detail">
              <h3>{selected.name}</h3>
              <div className="herb-detail__sub">
                {selected.botanical ?? "Botanical name pending cataloguing"}
              </div>
              {selected.aliases.length > 0 && (
                <div className="herb-card__tags" style={{ marginBottom: 12 }}>
                  {selected.aliases.slice(0, 6).map((a) => (
                    <span className="tag" key={a}>
                      {a}
                    </span>
                  ))}
                </div>
              )}
              <div className="herb-detail__grid">
                <div className="herb-detail__block">
                  <h4>Dosha caution</h4>
                  <p style={{ fontSize: 13.5 }}>
                    {selected.dosha_caution || "No specific dosha caution recorded."}
                  </p>
                </div>
                <div className="herb-detail__block">
                  <h4>Pregnancy flag</h4>
                  <p style={{ fontSize: 13.5 }}>
                    {selected.pregnancy_flag || "No specific pregnancy data on file."}
                  </p>
                </div>
                {selected.contraindications.length > 0 && (
                  <div className="herb-detail__block">
                    <h4>Contraindications</h4>
                    <ul>
                      {selected.contraindications.slice(0, 5).map((c, i) => (
                        <li key={i}>{c}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {selected.interactions.length > 0 && (
                  <div className="herb-detail__block">
                    <h4>Interactions</h4>
                    <ul>
                      {selected.interactions.slice(0, 5).map((c, i) => (
                        <li key={i}>{c}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {selected.classical_source && (
                  <div className="herb-detail__block">
                    <h4>Classical source</h4>
                    <p style={{ fontSize: 13.5 }}>{selected.classical_source}</p>
                  </div>
                )}
                {selected.verification_note && (
                  <div className="herb-detail__block">
                    <h4>Verification note</h4>
                    <p style={{ fontSize: 13.5 }}>{selected.verification_note}</p>
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="pagination">
            <button
              disabled={safePage === 0}
              onClick={() => setPage(safePage - 1)}
              aria-label="Previous page"
            >
              <IconChevronLeft width={16} height={16} />
            </button>
            <div className="pagination__dots">
              {Array.from({ length: Math.min(pages, 7) }).map((_, i) => (
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
        </>
      )}
    </div>
  );
}