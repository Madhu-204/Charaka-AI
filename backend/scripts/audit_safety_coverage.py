"""Coverage audit: herbs.json canonical names + aliases vs herb_safety.json keys.

Three checks:
  1. covered   : every canonical herb resolves (itself or via alias) to a safety entry
  2. orphans   : every safety key is reachable from at least one herb (no dead keys)
  3. reachable : every safety entry can actually be surfaced at runtime, i.e. it
                 appears as a verse-herb in herb_mentions.json (or a herb resolves to
                 it via a mention). A herb may be "covered" in the JSON file yet never
                 fire check_safety for any query -- that is a *runtime coverage* gap,
                 reported separately from key coverage so the next fill batch cannot
                 silently repeat it.

Usage: python scripts/audit_safety_coverage.py
Exit codes:
  0 = clean (no orphans; no reachable gaps that are classed as blocking)
  1 = orphan safety keys present
"""
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

with open(BACKEND / "reference" / "herbs.json", encoding="utf-8") as f:
    herbs = json.load(f)["herbs"]

with open(BACKEND / "reference" / "herb_safety.json", encoding="utf-8") as f:
    safety = json.load(f)

with open(BACKEND / "processed" / "herb_mentions.json", encoding="utf-8") as f:
    mentions = json.load(f)

safety_keys = {e["herb"] for e in safety}
mentioned_herbs = {row["herb"] for row in mentions}


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

# --- Check 3: runtime reachability -------------------------------------------
# A safety entry is *runtime-reachable* if its key itself appears as a mention,
# OR it is reachable from some herb whose canonical name/alias is a mention.
# (check_safety surfaces only herb names present in herb_mentions.json, either as
# a verse-herb or via the raw-text fallback; a key with no mention can never fire.)
safety_spec = {e["herb"] for e in safety}
reachable_keys = mentioned_herbs & safety_spec
for h in herbs:
    for alias in [h["name"]] + h["aliases"]:
        if alias in mentioned_herbs:
            reachable_keys.add(resolve(h["name"], h["aliases"]))
unreachable_safety = sorted(k for k in safety_keys if k not in reachable_keys)

print(f"runtime-reachable:  {len(safety_keys - set(unreachable_safety))}/{len(safety_keys)}")
print(f"unreachable entries: {len(unreachable_safety)}")
if unreachable_safety:
    print("UNREACHABLE (have monograph but no verse mention -> can never fire):")
    for k in unreachable_safety:
        print("   ", k)

# Reachability is advisory until the corpus-expansion phase (Phase 11) fills the
# genuinely-absent herbs; report it but do not exit non-zero on it alone.
print(
    "\nNote: an 'unreachable' entry is NOT an orphan -- it is a runtime-coverage gap: "
    "the herb's data is complete in herb_safety.json but no ingested verse mentions it, "
    "so check_safety cannot surface it for any query. Distinguish an alias gap (herb is "
    "in the corpus under another name -- add the alias) from a corpus-scope gap (herb "
    "absent from the ingested 20-chapter subset -- expand the corpus in Phase 11)."
)

if orphans:
    sys.exit(1)