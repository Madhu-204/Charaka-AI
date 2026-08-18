import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "charaka_data"
REF = ROOT / "reference"
OUT = ROOT / "processed"

STHANA_DISPLAY = {
    "sutrasthana": "Sutra Sthana",
    "vimanasthana": "Vimana Sthana",
    "sharirasthana": "Sharira Sthana",
    "chikitsasthana": "Chikitsa Sthana",
}


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def sthana_short(full_name):
    return full_name.replace("sthana", "")


def normalize_verse_id(raw_id, fallback_idx, used_ids):
    seg = None
    if raw_id and "<a href" not in raw_id:
        m = re.match(r"^\s*(\d+)(?:\s*-\s*(\d+))?", raw_id)
        if m:
            seg = m.group(1)
            if m.group(2):
                seg = f"{seg}-{m.group(2)}"
    if seg is None:
        seg = str(fallback_idx)
    candidate = seg
    n = 0
    while candidate in used_ids:
        n += 1
        candidate = f"{seg}-{chr(96 + n)}"
    used_ids.add(candidate)
    return candidate


def build_herb_matchers(herb_entries):
    matchers = []
    for entry in herb_entries:
        name = entry["name"]
        for alias in entry["aliases"]:
            pattern = r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])"
            matchers.append((name, re.compile(pattern, re.IGNORECASE)))
    return matchers


def extract_herbs(text, matchers):
    found = set()
    for name, rx in matchers:
        if rx.search(text):
            found.add(name)
    return sorted(found)


def build_herb_table(records):
    table = []
    for rec in records:
        for herb in rec["herbs_mentioned"]:
            table.append({
                "herb": herb,
                "verse_id": rec["verse_id"],
                "condition": rec["traditional_condition"],
                "category": rec["category_tag"],
                "context": rec["text_english"][:200],
            })
    return table


def clean_text(text, typo_map, label_prefixes):
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"<a href=[^>]*>", "", text)
    text = re.sub(r"html\">", "", text)
    for pattern in label_prefixes:
        text = re.sub(pattern, "", text)
    for typo, fix in typo_map.items():
        text = text.replace(typo, fix)
    return text


def main():
    manifest = load_json(RAW / "manifest.json")
    mappings = load_json(REF / "mappings.json")
    herbs = load_json(REF / "herbs.json")
    typo_fixes = load_json(REF / "typo_fixes.json")
    matchers = build_herb_matchers(herbs["herbs"])

    typo_map = typo_fixes["typos"]
    label_prefixes = typo_fixes["label_prefixes"]

    sthana_names = mappings["sthana_names"]
    chapter_meta = mappings["chapter_meta"]

    OUT.mkdir(exist_ok=True)

    records = []
    per_sthana = {}

    for entry in manifest:
        rel = entry["file"]
        src_path = RAW / rel
        data = load_json(src_path)

        folder_name = entry["sthana"]
        full_sthana = sthana_names[folder_name]
        short = sthana_short(full_sthana)
        chapter_num = int(re.match(r"ch(\d+)", entry["chapter"]).group(1))
        meta_key = f"{full_sthana}/{chapter_num}"
        if meta_key not in chapter_meta:
            print(f"WARNING: no mapping for {meta_key}, skipping")
            continue
        meta = chapter_meta[meta_key]
        condition = meta["condition"]
        category = meta["category"]

        display = f"{STHANA_DISPLAY[full_sthana]} ch.{chapter_num}"
        source = f"Charaka Samhita, {display} (Kaviratna trans. / gita/Datasets)"

        used_ids = set()
        chapter_records = []
        for idx, verse in enumerate(data, start=1):
            raw_text = verse.get("text", "")
            cleaned = clean_text(raw_text, typo_map, label_prefixes)
            verse_id = normalize_verse_id(verse.get("verse_id", ""), idx, used_ids)

            rec = {
                "verse_id": f"cs_{short}_{chapter_num}_{verse_id}",
                "sthana": full_sthana,
                "chapter": chapter_num,
                "traditional_condition": condition,
                "category_tag": category,
                "text_english": cleaned,
                "text_sanskrit": None,
                "herbs_mentioned": extract_herbs(cleaned, matchers),
                "verified": False,
                "source": source,
            }
            chapter_records.append(rec)
            records.append(rec)

        per_sthana.setdefault(full_sthana, []).extend(chapter_records)
        print(f"{rel}: {len(chapter_records)} verses")

    all_out = OUT / "charaka_structured.json"
    with open(all_out, "w", encoding="utf-8") as fh:
        json.dump(records, fh, ensure_ascii=False, indent=2)

    for sthana, recs in per_sthana.items():
        out = OUT / f"{sthana}.json"
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(recs, fh, ensure_ascii=False, indent=2)

    herb_out = OUT / "herb_mentions.json"
    with open(herb_out, "w", encoding="utf-8") as fh:
        json.dump(build_herb_table(records), fh, ensure_ascii=False, indent=2)

    print(f"\nTotal records: {len(records)}")
    print(f"Written: {all_out}")
    print(f"Written: {herb_out}")
    for sthana, recs in per_sthana.items():
        print(f"  {sthana}: {len(recs)}")


if __name__ == "__main__":
    sys.exit(main())
