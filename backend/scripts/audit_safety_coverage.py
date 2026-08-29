"""Coverage audit: herbs.json canonical names + aliases vs herb_safety.json keys.

Usage: python scripts/audit_safety_coverage.py
Exits non-zero if any safety key is orphaned (not reachable from any herb).
"""
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

with open(BACKEND / "reference" / "herbs.json", encoding="utf-8") as f:
    herbs = json.load(f)["herbs"]

with open(BACKEND / "reference" / "herb_safety.json", encoding="utf-8") as f:
    safety = json.load(f)

safety_keys = {e["herb"] for e in safety}


def resolve(herb_name, aliases):
    if herb_name in safety_keys:
        return herb_name
    for alias in aliases:
        if alias in safety_keys:
            return alias
    return None


covered = {
    h["name"]: resolve(h["name"], h["aliases"])
    for h in herbs
    if resolve(h["name"], h["aliases"]) is not None
}
uncovered = [h["name"] for h in herbs if h["name"] not in covered]

all_aliases = {a for h in herbs for a in h["aliases"]}
orphans = sorted(k for k in safety_keys if k not in all_aliases and k not in {h["name"] for h in herbs})

print(f"herbs (canonical):  {len(herbs)}")
print(f"safety entries:     {len(safety_keys)}")
print(f"covered:            {len(covered)}/{len(herbs)}")
print(f"uncovered:          {len(uncovered)}")
print(f"orphan safety keys: {len(orphans)}")
if uncovered:
    print("unknown/uncovered herbs:", ", ".join(uncovered))
if orphans:
    print("ORPHANS:", ", ".join(orphans))

if orphans:
    sys.exit(1)