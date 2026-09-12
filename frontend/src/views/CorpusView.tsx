import { useCallback, useEffect, useState } from "react";
import {
  fetchChapterVerses,
  fetchCorpusSthanas,
  searchCorpus,
} from "../api";
import type {
  CorpusChapter,
  CorpusSearchResult,
  CorpusSthana,
  CorpusVerse,
} from "../types";
import {
  IconBook,
  IconChevronDown,
  IconScroll,
  IconSearch,
} from "../components/Icons";

export function CorpusView() {
  const [sthanas, setSthanas] = useState<CorpusSthana[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState<string | null>(null);
  const [selected, setSelected] = useState<{
    sthana: string;
    chapter: number;
    title: string;
  } | null>(null);
  const [verses, setVerses] = useState<CorpusVerse[]>([]);
  const [versesLoading, setVersesLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [results, setResults] = useState<CorpusSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchCorpusSthanas()
      .then((data) => {
        if (!cancelled) setSthanas(data);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load the corpus. Is the backend running?");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const openChapter = useCallback(
    (s: CorpusSthana, c: CorpusChapter) => {
      setSelected({
        sthana: s.sthana,
        chapter: c.chapter,
        title: s.title,
      });
      setVersesLoading(true);
      fetchChapterVerses(s.sthana, c.chapter)
        .then(setVerses)
        .catch(() => setVerses([]))
        .finally(() => setVersesLoading(false));
    },
    []
  );

  function handleSearch(raw: string) {
    const q = raw.trim();
    if (!q) {
      setResults([]);
      return;
    }
    setSearching(true);
    setError(null);
    searchCorpus(q, 10)
      .then(setResults)
      .catch(() => setError("Search failed. Is the backend running?"))
      .finally(() => setSearching(false));
  }

  return (
    <div className="chat-view">
      <div className="corpus-feed">
        <div className="corpus-hero">
          <div className="corpus-hero__title">
            <IconBook width={18} height={18} />
            Explore the Corpus
          </div>
          <p>
            Browse 2,490 verses of the Charaka Samhita by section and chapter, or
            full-text search the English translation.
          </p>
          <div className="corpus-search">
            <IconSearch width={16} height={16} />
            <input
              value={search}
              placeholder="Search all verses… e.g. seasonal routine for winter"
              onChange={(e) => {
                setSearch(e.target.value);
                if (!e.target.value.trim()) setResults([]);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSearch(search);
              }}
            />
            <button
              className="send-btn"
              onClick={() => handleSearch(search)}
              disabled={!search.trim() || searching}
              aria-label="Search corpus"
            >
              <IconScroll width={16} height={16} />
            </button>
          </div>
          {searching && <div className="corpus-muted">Searching…</div>}
        </div>

        {error && <div className="chat-error">{error}</div>}

        {results.length > 0 && (
          <div className="corpus-results">
            <div className="corpus-section-title">
              Search results for “{search.trim()}”
            </div>
            {results.map((r) => (
              <div className="source-item" key={r.verse_id}>
                <div className="source-item__top">
                  <span className="source-item__title">
                    {r.chapter}
                    {r.condition && <span> · {r.condition}</span>}
                  </span>
                  <span className="badge chip-latency">
                    {(r.score * 100).toFixed(0)}% match
                  </span>
                </div>
                <div className="source-item__meta">{r.text}</div>
              </div>
            ))}
          </div>
        )}

        {results.length === 0 && (
          <div className="corpus-tree">
            {loading ? (
              <div className="corpus-muted">Loading sections…</div>
            ) : (
              sthanas.map((s) => (
                <div className="corpus-sthana" key={s.sthana}>
                  <button
                    className="corpus-sthana__head"
                    aria-expanded={open === s.sthana}
                    onClick={() => setOpen(open === s.sthana ? null : s.sthana)}
                  >
                    <span className="corpus-sthana__name">
                      {s.sthana} — {s.title}
                    </span>
                    <span className="corpus-sthana__count">
                      {s.verse_count} verses
                    </span>
                    <IconChevronDown
                      className={open === s.sthana ? "chev chev--up" : "chev"}
                      width={15}
                      height={15}
                    />
                  </button>
                  {open === s.sthana && (
                    <div className="corpus-chapters">
                      {s.chapters.map((c) => (
                        <button
                          className="corpus-chapter"
                          key={c.chapter}
                          onClick={() => openChapter(s, c)}
                        >
                          <span>
                            Ch {c.chapter}
                            {c.condition ? ` · ${c.condition}` : ""}
                          </span>
                          <span className="corpus-muted">{c.verse_count} verses</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        )}

        {selected && !searching && results.length === 0 && (
          <div className="corpus-detail">
            <div className="corpus-section-title">
              {selected.sthana} · Chapter {selected.chapter} — {selected.title}
            </div>
            {versesLoading ? (
              <div className="corpus-muted">Loading verses…</div>
            ) : verses.length === 0 ? (
              <div className="corpus-muted">No verses found for this chapter.</div>
            ) : (
              verses.map((v) => (
                <div className="source-item" key={v.verse_id}>
                  <div className="source-item__top">
                    <span className="source-item__title">
                      {v.verse_id.replace(/_/g, " ")}
                      {v.condition && <span> · {v.condition}</span>}
                    </span>
                    {v.category && (
                      <span className="badge chip-confidence">{v.category}</span>
                    )}
                  </div>
                  <div className="source-item__meta">{v.text}</div>
                  {v.sanskrit && (
                    <div className="source-item__sanskrit">{v.sanskrit}</div>
                  )}
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}