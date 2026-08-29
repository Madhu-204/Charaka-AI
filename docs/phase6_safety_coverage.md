# Phase 6 — Safety-Data Coverage Decision

> Status: decision recorded 2026-08-29 (part of the Phase 5 close-out / Phase 6 kick-off); corrected 2026-08-29 (tier fixes + alias merges + arka/kataka fills)
> Reference: `backend/reference/herb_safety.json` (51 entries) vs `backend/reference/herbs.json` (96 → 93 herbs after alias merges)

## 1. Policy (recorded decision)

1. **Every herb the retrieval layer can surface for medicinal guidance needs a safety monograph.** If a user can get a herb advice answer, that herb must have safety data or an explicit, *visible* "no monograph" advisory — never a silent gap.
2. To make the gap visible rather than silent, `check_safety` now tags unsupported herbs as `source="uncovered"` and emits the advisory flag: *"no safety monograph on file — use only in food quantities, or confirm with a practitioner before medicinal use."* (safety.py, `_call_mcp_tool` fall-through).
3. **Culinary/food-frequent herbs** may stay on a lighter template (food-use caution only), but they still get an entry so the monolayer is uniform.
4. Any herb flagged `toxic`/`strychnine`-adjacent gets **highest** fill priority.
5. Data provenance discipline (from Phase 1 plan) stays: every entry carries `classical_source` + `modern_source`, and `modern_source_verified` is flipped **only after** a real second-source cross-check — never assumed.

## 2. Current inventory

| Bucket | Count | Meaning |
|---|---|---|
| Covered with full monograph | 52 | includes `kustha` (reconciled from orphaned `kushtha` key); `haridra` covered under turmeric; `arka` + `kataka` added §6 (2026-08-29) |
| Uncovered | 41 | see tiers below |
| Orphan safety keys | 0 | audited — every safety key resolves to a herb name/alias |

## 3. The 41 uncovered herbs, by tier (corrected 2026-08-29)

### Tier 3 — Dedup / alias reconciliation (closed 2026-08-29)

These were duplicate alias rows with **zero of their own verse mentions** (verified against `processed/herb_mentions.json`); their texts already detected to the canonical herb. Removed the empty rows and folded their unique aliases into the canonical:

- ~~`haridra`~~ → removed (0 own mentions); `turmeric` gained alias `curcuma`. Now fully covered under turmeric.
- ~~`bilva`~~ → removed (0 own mentions); `bael` gained alias `bengal quince`. List hygiene — **bael itself is STILL uncovered** and needs a real monograph (see Tiers 1–2).
- ~~`ushira`~~ → removed (0 own mentions); `khasa` gained alias `ushira`. List hygiene — **khasa itself is STILL uncovered**.

Net effect: 96 → **93 herbs**, coverage gap 46 → **43**. Note (correction of the original draft): `bael`/`bilva` and `khasa`/`ushira` were **never** resolvable to a covered safety entry — merging them only fixed the herb-list duplicates, not the coverage gap. Only `haridra→turmeric` was a genuine coverage close. Then §6 fills closed two more (arka, kataka): uncovered **41**.

### Tier 2 — Culinary/food-frequent (light template, lower urgency)

Spices and kitchen staples where "no monograph" is low-risk for normal food use; any medicinal guidance still needs a row:

`cardamom` · `cumin` · `fennel` · `celery` · `mustard` · `garden radish` · `garlic` · `onion` · `fenugreek` · `ajwain` · `dhanyaka` (coriander) · `yavani` · `shatapushpa` (dill/anise) · `trapusha` (cucumber) · `karkaru` (bottle gourd) · `chavya` · `bael` · `khasa`.

### Tier 1 — Therapeutically significant / potentially toxic (fill FIRST)

`patola` · `sariva` · `raktachandana` · `jivanti` · `gokarna` · `patala` · `kantakari` · `brihati` · `katphala` · `shalparni` · `nagarmotha` · `priyangu` · `palasha` · `ketaki` · `gandhatruna` (lemongrass) · `amlavetasa` · `padmakesara` · `utpala` · `surasa` · `stira` · `chochchika`.

> **Filled 2026-08-29 (removed from this tier):** ~~`arka`~~ and ~~`kataka`~~ — both were the highest-priority gap (the previous "no monograph" advisory told food-quantity use for a genuinely toxic plant); see §6.

> **Tier-up (2026-08-29):**
> - **`tulsi`** (holy basil) — moved **Tier 2 → Tier 1**: first-line Ayurvedic respiratory/medicinal herb; treating it as a culinary spice understates its exposure. Medicinal-culinary.
> - **`moringa`** (drumstick/shigru) — moved **Tier 2 → Tier 1**: widely self-prescribed as a supplement (leaf powders); interactions and dosing matter more than a food-use template covers. Medicinal-culinary.
> - Effect: Tier 1 = **25**, Tier 2 = **18**.

> Order of work (Phase 6): Tier 1 → Tier 2 → remaining Tier-3 merges (none pending — closed).

## 4. How this is enforced at runtime

- `safety_sources[herb]` now includes a visible `"uncovered"` value for any herb without a monograph → the `/ask` `reasoning_trace.safety_sources` names it.
- `eval_run.py` already prints `UNCOVERED` rows for herb queries whose herbs produced no flags — with the new attribution these queries now surface an advisory flag instead of nothing.
- `verification_notes` lists every herb whose data is **not** yet `modern_source_verified` (the "AI-compiled, not second-source-verified" disclosure).
- `source_disagreements` (added with the first verified batch) flags the *verified* herbs whose modern source carries a strong caution (hard pregnancy avoid or toxicity) that a lay reader should reconcile against classical use — a practitioner-review note, populated by rule, not by hand.

## 5. Cross-verified batch #1 (2026-08-29)

`modern_source_verified: true` after a genuine second-source cross-check against NCCIH fact sheets:

| Herb | Second source (NCCIH) | What was added/corrected |
|---|---|---|
| `ashwagandha` | [nccih.nih.gov/health/ashwagandha](https://www.nccih.nih.gov/health/ashwagandha) (updated Mar 2023) | added: rare liver-injury caution (stop if dark urine/fatigue/jaundice); hormone-sensitive prostate cancer; GI upset; diabetes + anticonvulsant interactions; breastfeeding now in the avoid flag |
| `turmeric` | [nccih.nih.gov/health/turmeric](https://www.nccih.nih.gov/health/turmeric) (updated Apr 2025) | added: high-bioavailability curcumin liver-injury reports; GI upset side-effects row; pregnancy flag sharpened to "food ok / supplement may be unsafe" |
| `liquorice` | [nccih.nih.gov/health/licorice-root](https://www.nccih.nih.gov/health/licorice-root) (updated Apr 2025) | added: glycyrrhizin cardiac-arrest risk + high-salt caveat; DGL (deglycyrrhizinated) as safer form; pregnancy note strengthened (≥38-week preterm link) |

Method (repeatable): fetch the NCCIH fact sheet, compare against the existing entry, **add** whatever the second source confirms that the entry under-covers, never weaken an existing caveat, then flip `modern_source_verified` and stamp the source + cross-check date in `modern_source`.

Next batch queued: `brahmi`, `guggulu`, `shatavari`, `guduchi`, `amalaki`, `haritaki`, `bibhitaki`, `vacha` (API of India is the better second source for these; NCCIH has no pages).

## 6. Highest-priority fills: `arka` + `kataka` (2026-08-29)

Both were the Tier-1 critical gap: the uncovered advisory (*"use only in food quantities…"*) was actively misleading for a toxic plant.

### `arka` — genuinely toxic, hard-avoid monograph

- **Species:** *Calotropis gigantea / procera* (swallow-wort, mudar).
- **Found (fetched primary source):** Hong Kong Hospital Authority Atlas of Poisonous Plants — whole plant poisonous via cardiac glycosides (calotropin, calatoxin, uscharin): digitalis-like toxicity (vomiting, burning GI pain, arrhythmia, heart block); latex is a skin/mucous-membrane irritant and can cause corneal/conjunctival injury (permanent corneal endothelial damage); traditional abortifacient use. Corroborated by IVIS toxic-plant guide + PMC7586564 (cardiac-toxicity case report).
- **Entry added:** `modern_source_verified: true`; hard `pregnancy_flag` (strictly avoid) + digitalis interactions + *do-not-self-administer* dosha caution. Runtime flags now fire "pregnancy: Strictly avoid" + TOXIC warning (verified by smoke test).

### `kataka` — tier label corrected (NOT toxic)

- **Species correction:** Charaka's `kataka` = *Strychnos potatorum* (clearing nut, nirmali) — **not** the poisonous strychnine tree (*S. nux-vomica*, kupeelu). The Phase 6 draft's "strychnine tree — toxic, critical" label was wrong.
- **Found (fetched primary source):** PMC3931202 review — OECD-423 acute test **non-toxic up to 2000 mg/kg** (mice, no mortality); 90-day oral chronic safe. Caveat: the *injected* seed alkaloid fraction is neuroactive in animals (tremors/convulsions) — so the entry warns to keep to traditional small **oral** doses.
- **Entry added:** `modern_source_verified: true`; species-correction as a contraindication ("do not confuse with nux-vomica/kupeelu") + alkaloid-injection caution + pregnancy "no data" flag.
- **Detection consideration:** `herbs.json` still carries the misleading alias `strychnine tree` on `kataka` — kept intentionally so the entry (not a generic miss) answers that query, and the entry itself corrects the species.

### Effect

- Uncovered **43 → 41**; audit passes (51 entries, 52/93 covered, 0 orphans); retrieval eval unchanged (24/28, 0 false emergencies — arka/kataka were never eval queries, and added rows do not disturb the 10/10 mcp coverage).