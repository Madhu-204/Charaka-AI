import { useEffect } from "react";
import type { ReasoningContent } from "../components/ReasoningPanel";
import { IconCheck, IconDatabase, IconFlow, IconPeople, IconScroll, IconShield } from "../components/Icons";

interface AboutViewProps {
  onReasoning: (content: ReasoningContent | null) => void;
}

const CORPUS = [
  { text: "Sutra Sthana", scope: "General principles · daily & seasonal routine", verses: "984 verses · 10 chapters" },
  { text: "Vimana Sthana", scope: "Diagnosis & measurement", verses: "348 verses · 2 chapters" },
  { text: "Sharira Sthana", scope: "Body constitution", verses: "115 verses · 1 chapter" },
  { text: "Chikitsa Sthana", scope: "Therapeutics", verses: "1,043 verses · 7 chapters" },
];

const SOURCES = [
  {
    name: "NIIMH e-Samhita",
    detail: "Charaka Samhita digital edition — source of the 2,490 ingested verses.",
    badge: "Source verified",
    tone: "verified",
  },
  {
    name: "API of India monographs (Vols 1–4)",
    detail: "Classical rasapanchaka + dose cross-check for 24 herbs.",
    badge: "Classical API cross-checked",
    tone: "api",
  },
  {
    name: "NCCIH · MSKCC · Drugs.com · PubMed-PMC",
    detail: "Modern contraindications/interactions for 9 herbs, matched to fetched page text.",
    badge: "Source verified",
    tone: "verified",
  },
  {
    name: "herb_safety.json",
    detail: "92 safety monographs covering 93/93 canonical herbs (4 Tier categories, 0 orphans).",
    badge: "AI-compiled, human-curated",
    tone: "ai",
  },
];

function reasoningContent(): ReasoningContent {
  return {
    steps: [
      "How we verify herb data",
      "1: classical texts retrieved & ingested (Charaka Samhita)",
      "2: verses tagged by condition, description and category",
      "3: herbs cross-checked against API of India monographs",
      "4: modern contraindications matched to fetched pages",
      "5: human curators review and lock every entry",
    ],
    citations: SOURCES.map((s) => ({
      title: s.name,
      detail: s.detail,
      badge: s.tone as "verified" | "api" | "ai",
      badgeText: s.badge,
    })),
    showSearch: true,
  };
}

export function AboutView({ onReasoning }: AboutViewProps) {
  useEffect(() => {
    onReasoning(reasoningContent());
  }, [onReasoning]);

  return (
    <div className="view-scroll">
      <section className="about-section">
        <h2>Our Methodology</h2>
        <div className="method-grid">
          <div className="method-card">
            <span className="method-card__num">1</span>
            <div className="method-card__icon">
              <IconScroll width={26} height={26} />
            </div>
            <h3>Classical Text Retrieval</h3>
            <p>
              Wellness concepts are mapped to the Charaka Samhita, retrieved verse-by-verse
              against a 2,490-verse index embedded for semantic search.
            </p>
          </div>
          <div className="method-card">
            <span className="method-card__num">2</span>
            <div className="method-card__icon">
              <IconFlow width={26} height={26} />
            </div>
            <h3>Contextual Pattern Matching</h3>
            <p>
              Classical patterns are matched to your symptoms (e.g. Vata, Pitta, Kapha
              imbalances) by keyword scoring, then disambiguated by chapter metadata.
            </p>
          </div>
          <div className="method-card">
            <span className="method-card__num">3</span>
            <div className="method-card__icon">
              <IconPeople width={26} height={26} />
            </div>
            <h3>Human-AI Collaboration</h3>
            <p>
              Every safety entry and citation is curated by a human — classical data is
              cross-checked against API-of-India monographs and modern page texts before it
              ever reaches an answer.
            </p>
          </div>
        </div>
        <div className="method-note">
          <span className="badge badge--ai">
            <IconCheck width={13} height={13} />
            AI-compiled, human-curated
          </span>
        </div>
      </section>

      <section className="about-section">
        <h2>Data &amp; Provenance</h2>
        <div className="about-table-wrap">
          <table className="about-table">
            <thead>
              <tr>
                <th>Classical Text</th>
                <th>Status</th>
                <th>Corpus Scope</th>
              </tr>
            </thead>
            <tbody>
              {CORPUS.map((row) => (
                <tr key={row.text}>
                  <td>{row.text}</td>
                  <td>
                    <span className="badge badge--verified">
                      <IconCheck width={13} height={13} />
                      Verified
                    </span>
                  </td>
                  <td>{row.scope}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td>
                  <strong>Charaka AI corpus</strong>
                </td>
                <td colSpan={2}>
                  <em>4 Sthanas · 20 chapters · 2,490 verses (CS unique IDs)</em>
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      </section>

      <section className="about-columns">
        <div className="about-card">
          <h3>Limitations &amp; Disclaimers</h3>
          <p>
            Charaka AI is for <strong>educational and general-wellness purposes only</strong>. It
            is not a medical device and does not diagnose, treat, or prescribe.
          </p>
          <ul>
            <li>Emergencies are detected and always redirected to a doctor — the system cannot be talked around them.</li>
            <li>It does not handle chronic or diagnosed conditions, pregnancy, pediatrics, mental-health diagnoses, or anything surgical.</li>
            <li>Answers are classical-text descriptions, not clinical judgments — always see a qualified healthcare professional.</li>
            <li>Some herb profiles are AI-compiled from modern sources and remain unverified; these are disclosed, never hidden.</li>
          </ul>
        </div>

        <div className="about-card">
          <h3>Data Sources &amp; Verification</h3>
          <div style={{ marginBottom: 10 }}>
            <IconDatabase width={20} height={20} style={{ color: "var(--olive)" }} />
          </div>
          <ul>
            {SOURCES.map((s) => (
              <li key={s.name}>
                <strong>{s.name}</strong> — {s.detail}{" "}
                <span className={`badge ${s.tone === "verified" ? "badge--verified" : s.tone === "api" ? "badge--api" : "badge--ai"}`}>
                  {s.badge}
                </span>
              </li>
            ))}
            <li style={{ listStyle: "none", fontSize: 12.5, color: "var(--text-faint)" }}>
              <IconShield width={13} height={13} />
              Verification discipline: no claim is ever marked "verified" unless it matches a fetched page text (Phases 5–6).
            </li>
          </ul>
        </div>
      </section>
    </div>
  );
}