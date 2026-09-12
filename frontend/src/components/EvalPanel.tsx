import { useEffect, useRef, useState } from "react";
import { ApiError, fetchLastEval, runEvalStream } from "../api";
import type { EvalResult, EvalRow } from "../types";

type Progress = { index: number; total: number } | null;

export function EvalPanel() {
  const [result, setResult] = useState<EvalResult | null>(null);
  const [rows, setRows] = useState<EvalRow[]>([]);
  const [progress, setProgress] = useState<Progress>(null);
  const [running, setRunning] = useState(false);
  const [corner, setCorner] = useState(true);
  const [mode, setMode] = useState<"retrieval" | "full">("retrieval");
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchLastEval()
      .then((last) => {
        if (last) {
          setResult(last);
          setRows(last.rows);
        }
      })
      .catch(() => {
        /* no prior run yet */
      });
  }, []);

  async function handleRun() {
    if (running) return;
    setRunning(true);
    setError(null);
    setRows([]);
    setResult(null);
    setProgress({ index: 0, total: corner ? 40 : 28 });
    try {
      await runEvalStream(corner, mode, {
        onItem: (row) => {
          setProgress({ index: row.index, total: row.total });
          setRows((prev) => [...prev, row]);
          requestAnimationFrame(() => {
            listRef.current?.scrollTo({
              top: listRef.current.scrollHeight,
              behavior: "smooth",
            });
          });
        },
        onDone: (res) => {
          setResult(res);
          setRows(res.rows);
          setProgress(null);
        },
        onError: (e) => {
          setError(
            e instanceof ApiError && e.status === 408
              ? e.message
              : "Eval run failed — is the backend running on port 8000?",
          );
        },
      });
    } finally {
      setRunning(false);
      setProgress(null);
    }
  }

  const s = result?.summary;
  const pct = progress && progress.total ? (progress.index / progress.total) * 100 : 0;

  return (
    <section className="about-section">
      <h2>Regression Eval Runner</h2>
      <p className="eval-intro">
        Run the retrieval eval suite on demand — 28 core questions plus 12 corner
        cases (emergency phrasing, alias gaps, adversarial word-order). Retrieval
        mode is free; full mode also invokes the LLM and is slower.
      </p>

      <div className="eval-controls">
        <button className="pill pill--terracotta" onClick={() => void handleRun()} disabled={running}>
          {running ? "Running…" : "Run eval"}
        </button>
        <label className="eval-check">
          <input
            type="checkbox"
            checked={corner}
            onChange={(e) => setCorner(e.target.checked)}
            disabled={running}
          />
          Include corner cases
        </label>
        <label className="eval-check">
          Mode
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value as "retrieval" | "full")}
            disabled={running}
          >
            <option value="retrieval">retrieval (free)</option>
            <option value="full">full (LLM)</option>
          </select>
        </label>
      </div>

      {progress && (
        <div className="eval-progress">
          <div className="eval-progress__bar">
            <div className="eval-progress__fill" style={{ width: `${pct}%` }} />
          </div>
          <span className="eval-muted">
            {progress.index}/{progress.total}
          </span>
        </div>
      )}

      {error && <div className="chat-error">{error}</div>}

      {s && (
        <div className="eval-summary">
          <div className="eval-stat">
            <span className="eval-stat__value">{s.resolved_pct}%</span>
            <span className="eval-stat__label">
              Resolved ({s.resolved}/{s.total})
            </span>
          </div>
          <div className="eval-stat">
            <span className="eval-stat__value">{s.top_n_pct}%</span>
            <span className="eval-stat__label">
              Top-3 ({s.top_n}/{s.total})
            </span>
          </div>
          <div className="eval-stat">
            <span className="eval-stat__value">{s.core.resolved_pct}%</span>
            <span className="eval-stat__label">
              Core ({s.core.resolved}/{s.core.total})
            </span>
          </div>
          <div className="eval-stat">
            <span className="eval-stat__value">{s.corner.resolved_pct}%</span>
            <span className="eval-stat__label">
              Corner ({s.corner.resolved}/{s.corner.total})
            </span>
          </div>
          <div className="eval-stat">
            <span className="eval-stat__value">{s.emergency_false_positives}</span>
            <span className="eval-stat__label">False emergencies</span>
          </div>
          <div className="eval-stat">
            <span className="eval-stat__value">{s.known_gaps_admitted}</span>
            <span className="eval-stat__label">Known gaps</span>
          </div>
        </div>
      )}

      {rows.length > 0 && (
        <div className="eval-rows" ref={listRef}>
          {rows.map((r) => (
            <div
              className={`eval-row ${r.resolved_hit ? "eval-row--pass" : "eval-row--fail"}`}
              key={r.eval_id}
            >
              <span className="eval-row__mark">{r.resolved_hit ? "PASS" : "FAIL"}</span>
              <span className="eval-row__id">{r.eval_id}</span>
              <span className="eval-row__q" title={r.question}>
                {r.question}
              </span>
              <span className="eval-row__map">
                {r.expected} → {r.resolved}
              </span>
              {r.known_gap && <span className="badge chip-latency">known gap</span>}
              {r.corner && !r.known_gap && <span className="badge chip-confidence">corner</span>}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}