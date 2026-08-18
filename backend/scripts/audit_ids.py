import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "charaka_data"
REF = ROOT / "reference"
PROC = ROOT / "processed"

sys.path.insert(0, str(ROOT / "scripts"))
from transform import clean_text

LETTERS = "abcdefghijklmnopqrstuvwxyz"


def main():
    manifest = json.load(open(RAW / "manifest.json", encoding="utf-8"))
    processed = json.load(open(PROC / "charaka_structured.json", encoding="utf-8"))
    typo_fixes = json.load(open(REF / "typo_fixes.json", encoding="utf-8"))
    typo_map = typo_fixes["typos"]
    label_prefixes = typo_fixes["label_prefixes"]

    by_id = {}
    for rec in processed:
        by_id.setdefault(rec["verse_id"], []).append(rec)

    failures = []
    total = 0

    for entry in manifest:
        data = json.load(open(RAW / entry["file"], encoding="utf-8"))
        chapter_num = int(re.match(r"ch(\d+)", entry["chapter"]).group(1))
        short = entry["sthana"].split("_")[1]

        used = set()
        for idx, verse in enumerate(data, start=1):
            total += 1
            raw_id = verse.get("verse_id", "")
            seg = None
            if raw_id and "<a href" not in raw_id:
                m = re.match(r"^\s*(\d+)(?:\s*-\s*(\d+))?", raw_id)
                if m:
                    seg = m.group(1)
                    if m.group(2):
                        seg = f"{seg}-{m.group(2)}"
            if seg is None:
                seg = str(idx)
            candidate = seg
            n = 0
            while candidate in used:
                n += 1
                candidate = f"{seg}-{LETTERS[n - 1]}"
            used.add(candidate)

            verse_id = f"cs_{short}_{chapter_num}_{candidate}"
            matches = by_id.get(verse_id, [])
            if len(matches) != 1:
                failures.append(f"{verse_id}: expected 1 record, found {len(matches)}")
                continue
            expected_start = clean_text(verse.get("text", ""), typo_map, label_prefixes)[:60]
            actual_start = matches[0]["text_english"][:60]
            if expected_start != actual_start:
                failures.append(f"{verse_id}: text mismatch\n  src: {expected_start}\n  out: {actual_start}")

    print(f"Total source verses audited: {total}")
    print(f"Failures: {len(failures)}")
    for f in failures:
        print(" -", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())