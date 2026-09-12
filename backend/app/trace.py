import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

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
) -> str:
    run_id = uuid.uuid4().hex[:12]
    record = {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "query": query[:300],
        "nodes": [
            {"node": node, "ms": ms, "tokens": tokens}
            for node, ms, tokens in node_times
        ],
        "tokens": token_count,
        "latency_ms": latency_ms,
        "cache_hit": cache_hit,
        "dosha": dosha,
        "resolved_chapter": resolved_chapter,
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    with _path_lock:
        with (run_dir / "traces.jsonl").open("a", encoding="utf-8") as f:
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