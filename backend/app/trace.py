import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app import guardrails

_path_lock = threading.Lock()


def _load(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def write_trace(
    run_dir: Path,
    query: str,
    node_times,
    token_count: int,
    latency_ms: float,
    cache_hit: bool = False,
    dosha: str | None = None,
    resolved_chapter: str | None = None,
    prompt_tokens: int = 0,
) -> str:
    run_id = uuid.uuid4().hex[:12]
    # Redact before the record is built, not after: the query is the only free-text
    # field here, and it is the one a user is most likely to paste an identifier
    # into ("my phone is 9876543210, what does Charaka say about..."). The audit
    # trail keeps its operational value - run_id, timings, node list, chapter - and
    # loses the identifier.
    record = {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "query": guardrails.redact_pii(query)[:300],
        "nodes": [
            {"node": node, "ms": ms, "tokens": tokens}
            for node, ms, tokens in node_times
        ],
        # Completion tokens only, which is what `tokens` has always meant here.
        # `prompt_tokens` is recorded separately because Groq's free tier meters
        # the combined total against a shared TPM window, so the prompt side is
        # what actually decides whether a request fits.
        "tokens": token_count,
        "prompt_tokens": prompt_tokens,
        "latency_ms": latency_ms,
        "cache_hit": cache_hit,
        "dosha": dosha,
        "resolved_chapter": resolved_chapter,
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "traces.jsonl"
    # Bounded growth. Health questions accumulate here forever otherwise, and a
    # retention policy nobody applies is not a retention policy.
    guardrails.rotate_jsonl(path)
    with _path_lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return run_id


def list_traces(run_dir: Path, limit: int = 50) -> list:
    records = _load(run_dir / "traces.jsonl")
    return [
        {
            "run_id": r["run_id"],
            "started_at": r["started_at"],
            "query": r["query"],
            "latency_ms": r["latency_ms"],
            "tokens": r.get("tokens", 0),
            "cache_hit": r.get("cache_hit", False),
            "nodes": [n["node"] for n in r.get("nodes", [])],
            "resolved_chapter": r.get("resolved_chapter"),
        }
        for r in records[-limit:]
    ][::-1]


def get_trace(run_dir: Path, run_id: str):
    for r in _load(run_dir / "traces.jsonl"):
        if r.get("run_id") == run_id:
            return r
    return None