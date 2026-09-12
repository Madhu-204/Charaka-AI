"""Assemble a ready-to-push Hugging Face Space directory for Charaka AI.

Builds `deploy/charaka-ai-space/` containing everything the space needs
(the Dockerfile, backend app + corpus data, and the frontend sources the
image builds internally). Generated/runtime data is excluded.

Usage:
    python scripts/prepare_deploy.py
    # then, with the `hf` CLI (pip install -U "huggingface_hub[cli]"):
    #   hf space create <username>/charaka-ai --type docker
    #   hf upload <username>/charaka-ai deploy/charaka-ai-space --relative
    #   -> set GROQ_API_KEY (and optionally CHARAKA_API_KEY) as Space secrets.
"""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "deploy" / "charaka-ai-space"

COPY_TREES = [
    ("backend/app", "backend/app"),
    ("backend/scripts", "backend/scripts"),
    ("backend/reference", "backend/reference"),
    ("backend/processed", "backend/processed"),
    ("backend/chroma_db", "backend/chroma_db"),
    ("frontend", "frontend"),
]

IGNORE_IN_FRONTEND = shutil.ignore_patterns(
    "node_modules", "dist", "src", "public", "*.map"
)
IGNORE_ALWAYS = shutil.ignore_patterns(
    "__pycache__",
    "*.pyc",
    ".DS_Store",
    "traces",
    "eval_results.json",
    "user_chroma_db",
    "feedback_log.jsonl",
    "conversations.jsonl",
)

SPACE_README = """---
title: Charaka AI
emoji: 🌿
colorFrom: green
colorTo: terracotta
sdk: docker
app_port: 7860
pinned: false
---

# Charaka AI — Ayurvedic wellness assistant

Grounded in 2,490 verses of the Charaka Samhita. Free CPU-basic space; keep it
awake with the included GitHub Actions heartbeat.

## Secrets to set in the Space

- `GROQ_API_KEY` — required (free tier).
- `CHARAKA_API_KEY` — optional; if set, `/ask` needs an `X-API-Key` header.
- Rate limits: `CHARAKA_RATE_LIMIT=30`, `CHARAKA_RATE_BURST=60`.
"""


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    shutil.copy2(ROOT / "Dockerfile.deploy", OUT / "Dockerfile")
    shutil.copy2(ROOT / "backend" / "requirements.txt", OUT / "backend" / "requirements.txt")
    (OUT / "README.md").write_text(SPACE_README, encoding="utf-8")
    (OUT / ".dockerignore").write_text(
        "node_modules\ndist\n.venv\n.git\n__pycache__\n*.pyc\n.ds_store\n",
        encoding="utf-8",
    )

    for src_rel, dst_rel in COPY_TREES:
        src = ROOT / src_rel
        dst = OUT / dst_rel
        ignore = IGNORE_IN_FRONTEND if src_rel.startswith("frontend") else IGNORE_ALWAYS
        shutil.copytree(src, dst, ignore=ignore)

    # Carry the two committed derivable .json data files the app reads at boot.
    for name in ("herb_mentions.json", "charaka_structured.json"):
        p = ROOT / "backend" / "processed" / name
        if not p.exists():
            print(f"WARN: missing {p} — regenerate with scripts/transform.py")
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"Space staged at {OUT} ({size / 1e6:.1f} MB)")
    print("Next: `hf space create <user>/charaka-ai --type docker`")
    print("Then:  `hf upload <user>/charaka-ai deploy/charaka-ai-space --relative`")


if __name__ == "__main__":
    main()