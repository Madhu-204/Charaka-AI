import json
import threading
from collections import defaultdict
from pathlib import Path


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


class FeedbackStats:
    def __init__(self, log_path: Path):
        self._path = log_path
        self._lock = threading.Lock()
        self._cache = None
        self._cache_eval = 0.0

    def snapshot(self, force: bool = False) -> dict:
        with self._lock:
            import os
            import time

            try:
                mtime = self._path.stat().st_mtime
            except OSError:
                mtime = 0.0
            if not force and self._cache and mtime == self._cache_eval:
                return self._cache
            self._cache = self._compute()
            self._cache_eval = mtime
            return self._cache

    def _compute(self) -> dict:
        records = _load(self._path)
        total = len(records)
        ups = sum(1 for r in records if r.get("rating") == "up")
        downs = total - ups

        by_category: dict[str, dict] = defaultdict(
            lambda: {"total": 0, "up": 0, "down": 0}
        )
        by_dosha: dict[str, dict] = defaultdict(
            lambda: {"total": 0, "up": 0, "down": 0}
        )
        for r in records:
            cat = r.get("category_tag") or "uncategorized"
            dosha = r.get("dosha") or "unassessed"
            by_category[cat]["total"] += 1
            if r.get("rating") == "up":
                by_category[cat]["up"] += 1
            else:
                by_category[cat]["down"] += 1
            by_dosha[dosha]["total"] += 1
            if r.get("rating") == "up":
                by_dosha[dosha]["up"] += 1
            else:
                by_dosha[dosha]["down"] += 1

        def _win_rate(bucket) -> float:
            if bucket["total"] == 0:
                return 0.0
            return round(bucket["up"] / bucket["total"], 3)

        return {
            "total": total,
            "up": ups,
            "down": downs,
            "win_rate": _win_rate({"total": total, "up": ups}),
            "by_category": {
                k: {
                    **v,
                    "win_rate": _win_rate(v),
                }
                for k, v in sorted(by_category.items(), key=lambda kv: -kv[1]["total"])
            },
            "by_dosha": {
                k: {
                    **v,
                    "win_rate": _win_rate(v),
                }
                for k, v in sorted(by_dosha.items(), key=lambda kv: -kv[1]["total"])
            },
            "recent": [
                {
                    "created_at": r.get("created_at"),
                    "query": r.get("query", "")[:120],
                    "rating": r.get("rating"),
                    "category_tag": r.get("category_tag"),
                    "dosha": r.get("dosha"),
                }
                for r in records[-10:]
            ][::-1],
        }