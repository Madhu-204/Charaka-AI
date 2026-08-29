# Phase 6 — Safety-Data Coverage Decision

> Status: decision recorded 2026-08-29 (part of the Phase 5 close-out / Phase 6 kick-off)
> Reference: `backend/reference/herb_safety.json` (49 entries) vs `backend/reference/herbs.json` (96 herbs)

## 1. Policy (recorded decision)

1. **Every herb the retrieval layer can surface for medicinal guidance needs a safety monograph.** If a user can get a herb advice answer, that herb must have safety data or an explicit, *visible* "no monograph" advisory — never a silent gap.
2. To make the gap visible rather than silent, `check_safety` now tags unsupported herbs as `source="uncovered"` and emits the advisory flag: *"no safety monograph on file — use only in food quantities, or confirm with a practitioner before medicinal use."* (safety.py, `_call_mcp_tool` fall-through).
3. **Culinary/food-frequent herbs** may stay on a lighter template (food-use caution only), but they still get an entry so the monolayer is uniform.
4. Any herb flagged `toxic`/`strychnine`-adjacent gets **highest** fill priority.
5. Data provenance discipline (from Phase 1 plan) stays: every entry carries `classical_source` + `modern_source`, and `modern_source_verified` is flipped **only after** a real second-source cross-check — never assumed.

## 2. Current inventory

| Bucket | Count | Meaning |
|---|---|---|
| Covered with full monograph | 49 | includes `kustha` (reconciled from orphaned `kushtha` key) |
| Uncovered | 46 | see tiers below |
| Orphan safety keys | 0 | audited — every safety key resolves to a herb name/alias |

## 3. The 46 uncovered herbs, by tier

### Tier 3 — Dedup / alias reconciliation (no new data needed)

These are duplicate plant names or alias overlaps already resolvable to a covered herb:

- `haridra` (haldi/curcuma) = **turmeric** (covered) — same plant (Curcuma longa); merge or extend turmeric aliases.
- `bilva` (bengal quince) = **bael** (wood-apple, alias already includes `bilva`) — same plant (Aegle marmelos).
- `khasa` (alias `usira`) and `ushira` — same plant (vetiver, Chrysopogon zizanioides); merge.

### Tier 2 — Culinary/food-frequent (light template, lower urgency)

Spices and kitchen staples where "no monograph" is low-risk for normal food use; any medicinal guidance still needs a row:

`cardamom` · `cumin` · `fennel` · `celery` · `mustard` · `garden radish` · `garlic` · `onion` · `fenugreek` · `ajwain` · `dhanyaka` (coriander) · `yavani` · `shatapushpa` (dill/anise) · `trapusha` (cucumber) · `karkaru` (bottle gourd) · `chavya` · `tulsi` (also medicinal → treat as Tier 1-ish) · `moringa` (medicinal-culinary → Tier 1-ish).

### Tier 1 — Therapeutically significant / potentially toxic (fill FIRST)

`arka` (swallow-wort — **toxic**, critical) · `kataka` (strychnine tree — **toxic**, critical) · `patola` · `sariva` · `raktachandana` · `jivanti` · `gokarna` · `patala` · `kantakari` · `brihati` · `katphala` · `shalparni` · `nagarmotha` · `priyangu` · `palasha` · `ketaki` · `gandhatruna` (lemongrass) · `amlavetasa` · `padmakesara` · `utpala` · `surasa` · `stira` · `chochchika`.

> Order of work (Phase 6): Tier 1 → Tier 2 → Tier 3 merges. Tier 3 can be closed immediately by alias reconciliation.

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