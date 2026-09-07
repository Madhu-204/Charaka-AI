import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";
import { fetchHerbs } from "../api";
import type { HerbSummary } from "../types";
import type { ReasoningContent } from "../components/ReasoningPanel";
import { herbImageUrl } from "../lib/herbImages";
import {
  IconChevronLeft,
  IconChevronRight,
  IconInfo,
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
    <svg width="120" height="120" viewBox="0 0 120 120" fill="none" aria-hidden>
      <circle cx="60" cy="60" r="52" fill={color} opacity="0.07" />
      <circle cx="60" cy="60" r="52" stroke={color} strokeWidth="1.3" opacity="0.45" strokeDasharray="3 5" />
      <g stroke={color} strokeWidth="2.2" strokeLinecap="round">
        <path d="M60 98 V42" />
        <path d="M60 78 C 40 74 30 60 34 46 C 48 42 58 52 60 62 Z" fill={color} opacity="0.18" />
        <path d="M60 78 C 80 74 90 60 86 46 C 72 42 62 52 60 62 Z" fill={color} opacity="0.18" />
        <path d="M60 60 C 44 56 38 46 42 34 C 56 32 60 42 60 50 Z" fill={color} opacity="0.26" />
        <path d="M60 60 C 76 56 82 46 78 34 C 64 32 60 42 60 50 Z" fill={color} opacity="0.26" />
      </g>
      <g fill={color}>
        <circle cx="60" cy="30" r="5" />
        <circle cx="49" cy="33" r="3.6" />
        <circle cx="71" cy="33" r="3.6" />
        <circle cx="51" cy="42" r="3.2" />
        <circle cx="69" cy="42" r="3.2" />
      </g>
    </svg>
  );
}

function HerbImage({
  name,
  className = "herb-card__img",
  artClassName = "herb-card__img-art",
  style,
}: {
  name: string;
  className?: string;
  artClassName?: string;
  style?: CSSProperties;
}) {
  const [failed, setFailed] = useState(false);
  const url = useMemo(() => herbImageUrl(name), [name]);
  if (url && !failed) {
    return (
      <img
        className={className}
        src={url}
        alt={name}
        loading="lazy"
        style={style}
        onError={() => setFailed(true)}
      />
    );
  }
  return (
    <div className={artClassName} style={style}>
      <HerbArt name={name} />
      <span className="herb-card__img-art-label">Image unavailable</span>
    </div>
  );
}

function hasSevereFlag(h: HerbSummary): boolean {
  const f = (h.pregnancy_flag ?? "").toLowerCase();
  return /strictly avoid|avoid|not recommended|contraindicated|unsafe/.test(f);
}

function verificationBadge(h: HerbSummary): { text: string; tone: "verified" | "api" | "ref" } {
  if (h.modern_source_verified) return { text: "Source verified", tone: "verified" };
  if (h.api_of_india_verified) return { text: "Classical cross-checked", tone: "api" };
  return { text: "Reference only", tone: "ref" };
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
        : h.api_of_india_verified
          ? ["Modern claims are reference-level and not independently cross-checked"]
          : ["Summary for study; consult a practitioner before use"]),
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
        ? [{ title: "Verification note", detail: h.verification_note.slice(0, 200), badge: "ref" as const, badgeText: "Reference only" }]
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
  const [showHowTo, setShowHowTo] = useState(false);
  const [zoom, setZoom] = useState(1);

  const clearSelection = useCallback(() => {
    setSelected(null);
    onReasoning(null);
    setZoom(1);
  }, [onReasoning]);

  useEffect(() => {
    if (selected) setZoom(1);
  }, [selected?.name]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setShowHowTo(false);
        clearSelection();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [clearSelection]);

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
    const weight = (h: HerbSummary) =>
      h.modern_source_verified ? 0 : h.api_of_india_verified ? 1 : 2;
    return herbs
      .filter((h) => {
        if (q) {
          const hay = `${h.name} ${h.botanical ?? ""} ${h.aliases.join(" ")}`.toLowerCase();
          if (!hay.includes(q)) return false;
        }
        if (doshaFilter !== "all" && !h.dosha_tags.includes(doshaFilter)) return false;
        if (verifyFilter === "sv" && !h.modern_source_verified) return false;
        if (verifyFilter === "api" && !h.api_of_india_verified) return false;
        if (verifyFilter === "ai" && (h.modern_source_verified || h.api_of_india_verified)) return false;
        return true;
      })
      .sort((a, b) => weight(a) - weight(b) || a.name.localeCompare(b.name));
  }, [herbs, search, doshaFilter, verifyFilter]);

  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pages - 1);
  const visible = filtered.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE);

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
          <option value="api">Classical cross-checked</option>
          <option value="ai">Reference only</option>
        </select>
        <button
          className={`howto-toggle ${showHowTo ? "howto-toggle--open" : ""}`}
          onClick={() => setShowHowTo((o) => !o)}
          aria-expanded={showHowTo}
          aria-label="How to read these herbs"
        >
          <IconInfo width={16} height={16} />
          How to read these herbs
        </button>
      </div>

      {showHowTo && (
        <div className="verify-popup" role="tooltip">
          <strong>How to read these herbs</strong>
          <div className="verify-popup__row">
            <span className="tag tag--verified">Source verified</span>
            <span>modern safety claims checked against a fetched reference page</span>
          </div>
          <div className="verify-popup__row">
            <span className="tag tag--api">Classical cross-checked</span>
            <span>classical properties matched to an API of India monograph</span>
          </div>
          <div className="verify-popup__row">
            <span className="tag tag--ref">Reference only</span>
            <span>informative summary for study</span>
          </div>
          <p className="verify-popup__disclaimer">
            This is educational material, not medical advice.
          </p>
          <button
            className="verify-popup__close"
            onClick={() => setShowHowTo(false)}
            aria-label="Close"
          >
            ✕
          </button>
        </div>
      )}

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
                  <div className="herb-card__media">
                    <HerbImage name={h.name} />
                  </div>
                  <div className="herb-card__body">
                    <div className="herb-card__name">{h.name}</div>
                    <div className="herb-card__botanical">
                      {h.botanical ?? "Botanical name pending"}
                    </div>
                    <div className="herb-card__alias">
                      {h.aliases.find((a) => a.toLowerCase() !== h.name.toLowerCase()) ?? ""}
                    </div>
                    <div className="herb-card__tags">
                      {h.dosha_tags.slice(0, 3).map((t) => (
                        <span className={`tag tag--dosha tag--dosha-${t.toLowerCase()}`} key={t}>
                          {t}
                        </span>
                      ))}
                      {hasSevereFlag(h) && (
                        <span className="tag tag--danger">Pregnancy caution</span>
                      )}
                      <span
                        className={
                          v.tone === "verified"
                            ? "tag tag--verified"
                            : v.tone === "ref"
                              ? "tag tag--ref"
                              : "tag tag--api"
                        }
                      >
                        {v.text}
                      </span>
                    </div>
                    <div className="herb-card__actions">
                      <button className="btn" onClick={() => toggleSelect(h)}>
                        Learn More
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {selected && (
            <div className="modal-backdrop" onClick={clearSelection} role="presentation">
              <div
                className="herb-modal"
                role="dialog"
                aria-modal="true"
                aria-label={selected.name}
                onClick={(e) => e.stopPropagation()}
              >
                <button
                  className="herb-modal__close"
                  onClick={clearSelection}
                  aria-label="Close"
                >
                  ✕
                </button>
                <div className="herb-modal__content">
                  {selected && (
                    <div className="herb-modal__gallery">
                      <div className="herb-modal__stage">
                        <HerbImage
                          name={selected.name}
                          className="herb-modal__img"
                          artClassName="herb-modal__img-art herb-card__img-art"
                          style={{ transform: `scale(${zoom})` }}
                        />
                      </div>
                      <div className="herb-modal__zoom">
                        <button
                          className="herb-modal__zoom-btn"
                          onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))}
                          disabled={zoom <= 0.5}
                          aria-label="Zoom out"
                        >
                          −
                        </button>
                        <span className="herb-modal__zoom-label">{Math.round(zoom * 100)}%</span>
                        <button
                          className="herb-modal__zoom-btn"
                          onClick={() => setZoom((z) => Math.min(4, z + 0.25))}
                          disabled={zoom >= 4}
                          aria-label="Zoom in"
                        >
                          +
                        </button>
                      </div>
                    </div>
                  )}
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
                  <p className="herb-modal__disclaimer">
                    This is educational material, not medical advice.
                  </p>
                </div>
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