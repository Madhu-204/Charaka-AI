import json
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]

with open(BACKEND / "processed" / "herb_mentions.json", encoding="utf-8") as f:
    herb_rows = json.load(f)

herbs_by_verse = {}
for row in herb_rows:
    herbs_by_verse.setdefault(row["verse_id"], []).append(row["herb"])

CONTRAINDICATIONS = {
    "guggulu": "avoid during pregnancy",
    "trikatu": "use cautiously with active acid reflux",
}


def check_safety(state):
    verse_id = state["resolved_chapter"].get("verse_id")
    text = state["resolved_chapter"]["text"].lower()

    found = list(herbs_by_verse.get(verse_id, []))
    if not found:
        found = [row["herb"] for row in herb_rows if row["herb"] in text]

    found = sorted(set(found))
    flags = [
        f"{h}: {CONTRAINDICATIONS[h]}" for h in found if h in CONTRAINDICATIONS
    ]

    return {"herbs_found": found, "safety_flags": flags}