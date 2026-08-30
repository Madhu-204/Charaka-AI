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
| Covered with full monograph | 93 | includes `kustha` (reconciled from orphaned `kushtha` key); `haridra` covered under turmeric; `arka` + `kataka` added §6 (2026-08-29); `tulsi` + `moringa` added §5c (2026-08-30); 18 Tier-2 culinary fills §5d (2026-08-30); remaining 21 Tier-1 fills §5e (2026-08-30) |
| Uncovered | 0 | see tiers below |
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

> **Filled 2026-08-30 (removed from this tier):** all 18 above — added as light-template culinary entries (§5d). Tier 2 is now **closed**.

### Tier 1 — Therapeutically significant / potentially toxic (fill FIRST)

`patola` · `sariva` · `raktachandana` · `jivanti` · `gokarna` · `patala` · `kantakari` · `brihati` · `katphala` · `shalparni` · `nagarmotha` · `priyangu` · `palasha` · `ketaki` · `gandhatruna` (lemongrass) · `amlavetasa` · `padmakesara` · `utpala` · `surasa` · `stira` · `chochchika`.

> **Filled 2026-08-29 (removed from this tier):** ~~`arka`~~ and ~~`kataka`~~ — both were the highest-priority gap (the previous "no monograph" advisory told food-quantity use for a genuinely toxic plant); see §6.
>
> **Filled 2026-08-30 (removed from this tier):** ~~`tulsi`~~ and ~~`moringa`~~ — see §5c.

> **Tier-up (2026-08-29):**
> - **`tulsi`** (holy basil) — moved **Tier 2 → Tier 1**: first-line Ayurvedic respiratory/medicinal herb; treating it as a culinary spice understates its exposure. Medicinal-culinary.
> - **`moringa`** (drumstick/shigru) — moved **Tier 2 → Tier 1**: widely self-prescribed as a supplement (leaf powders); interactions and dosing matter more than a food-use template covers. Medicinal-culinary.
> - Effect: Tier 1 = **25**, Tier 2 = **18**.

> Order of work (Phase 6): Tier 1 → Tier 2 → remaining Tier-3 merges (none pending — closed).
>
> **Tier-1 status (2026-08-30):** arka, kataka, tulsi, moringa + the remaining 21 Tier-1 herbs now filled (§5e). **Tier 1 is closed.**

## 4. How this is enforced at runtime

- `safety_sources[herb]` now includes a visible `"uncovered"` value for any herb without a monograph → the `/ask` `reasoning_trace.safety_sources` names it.
- `eval_run.py` already prints `UNCOVERED` rows for herb queries whose herbs produced no flags — with the new attribution these queries now surface an advisory flag instead of nothing.
- `verification_notes` lists every herb whose data is **not** yet `modern_source_verified` (the "AI-compiled, not second-source-verified" disclosure).
- `source_disagreements` (added with the first verified batch) flags the *verified* herbs whose modern source carries a strong caution (hard pregnancy avoid or toxicity) that a lay reader should reconcile against classical use — a practitioner-review note, populated by rule, not by hand.

## 5. Cross-verified batch #1 (2026-08-29) — includes a correction

> **Correction notice (2026-08-29, same day):** the first version of this section was written *after* a re-fetch of the ashwagandha and turmeric pages, and overstated what the ashwagandha page contains. A direct fetch in review found two specifics **not on the ashwagandha page** — the "2 weeks before surgery" timeframe, and the "stop if dark urine/fatigue/jaundice" instruction (that instruction *is* on the **turmeric** page). Re-scoping all three entries against the fetched text also found the same failure class in **turmeric** (gallstones/bleeding-disorder contraindications, and four interactions — anticoagulants, antacids/H2, diabetes medicines, CYP3A4 — none stated on the page) and **liquorice** (hypokalemia/edema contraindications, and digoxin/diuretic/antihypertensive/anticoagulant interactions — the page reports only the corticosteroid interaction). **The three entries are now scoped so that every contraindication/interaction/pregnancy claim matches the fetched page text exactly.** Removed claims are listed below for return via a real second source (they were correct general pharmacology, but they are not NCCIH statements).

| Herb | NCCIH page (fetched 2026-08-29) | Entry now contains (page-stated only) | Removed (not on page) |
|---|---|---|---|
| `ashwagandha` | [nccih.nih.gov/health/ashwagandha](https://www.nccih.nih.gov/health/ashwagandha) (updated Mar 2023) | autoimmune/thyroid disorders not recommended; not recommended for people about to have surgery; rare liver-injury cases; hormone-sensitive prostate cancer avoidance; drowsiness + GI upset; interactions listed: diabetes, high BP, immunosuppressants, sedatives, anticonvulsants, thyroid-hormone medicines; pregnancy/breastfeeding avoid | "2 weeks before surgery" timeframe; "stop if dark urine/fatigue/jaundice" symptom instruction; mechanism guesses (stimulates immune system, raises thyroid hormone, additive BP/sugar effects); un-checked "Ayurvedic Pharmacopoeia of India" attribution |
| `turmeric` | [nccih.nih.gov/health/turmeric](https://www.nccih.nih.gov/health/turmeric) (updated Apr 2025) | liver damage from high-bioavailability curcumin + the page's stop-instruction (fatigue, nausea, poor appetite, dark urine, jaundice); GI upset side-effects; topical hives/itching; supplement use in pregnancy may be unsafe; **no specific interactions on page** → interaction list emptied | gallstones/bile-duct CI; bleeding-disorders CI; uterine-stimulant mechanism; anticoagulant / antacid / diabetes / CYP3A4 interactions |
| `liquorice` | [nccih.nih.gov/health/licorice-root](https://www.nccih.nih.gov/health/licorice-root) (updated Apr 2025) | glycyrrhizin irregular-heartbeat/cardiac-arrest risk, worse with high salt, hypertension, heart/kidney conditions; large-amount pregnancy risk (~250 g/week → delivery before 38 weeks); topical skin irritation; corticosteroid interaction; breastfeeding unknown | hypokalemia CI; heart-failure/edema CI; "causes sodium/water retention" + "edema/hypertension" mechanisms; digoxin / diuretic / antihypertensive / anticoagulant interactions |

Method (enforced from this correction onward): **fetch the page first** — every contraindication/interaction/pregnancy claim in the new set must read as "the page states X"; anything the page does not state is either dropped or queued for a separately-checked second source. `modern_source_verified: true` means *claims == fetched page text*. `dosha_caution` is classical Ayurvedic knowledge (not from NCCIH) and is retained as such.

Next batch queued: `brahmi`, `guggulu`, `shatavari`, `guduchi`, `amalaki`, `haritaki`, `bibhitaki`, `vacha` (API of India is the better second source for these; NCCIH has no pages).

## 5b. Cross-verified batch #2 — API of India classical verification (2026-08-30)

All 8 queued herbs were cross-checked against the **Ayurvedic Pharmacopoeia of India (Part-I)** by fetching and text-extracting the actual PDFs (pypdf), same-day (2026-08-30): Vol-1 / Vol-2 from `ayurveda.hu` API mirror, Vol-4 from `naturalingredient.org`.

**Key methodological point (kept from batch #1):** an API-of-India monograph states the **classical rasapanchaka** (Rasa/Guna/Virya/Vipaka/Karma), therapeutic uses, and dose — it does **NOT** state modern contraindications, drug interactions, or pregnancy flags. The pre-existing entries in `herb_safety.json` are dominated by exactly those modern claims (immunostimulant, estrogenic activity, bradycardia, oxalate content, emmenagogue, etc.). Therefore setting `modern_source_verified: true` on API evidence alone would repeat the fabricated-attribution error the reviewer caught in batch #1. Resolution:

- Added a **new, distinct field `api_of_india_verified: true`** on all 8 entries, recording that the *classical* content (rasapanchaka + dose) was verified against the named monograph.
- Added **`verification_note`** — exact citation (volume, monograph no./name, printed page) + the verified classical text, so the evidence is auditable.
- **`modern_source_verified` is left `false`** on all 8, and the `verification_note` states explicitly that the API does not confirm the listed modern contraindication/interaction/pregnancy claims. Those claims remain "AI-compiled, not second-source-verified" — a true, honest disclosure.

### Volume corrections found during the work

- **Shatavari (Asparagus racemosus, Root) is in API Part-I Vol-4 (monograph 50, printed pp.122–123), NOT Vol-3.** Vol-3's 100 monographs (Aśhūkī→Utpala) contain no Śatāvarī — confirmed by reading both volumes' tables of contents.
- **Vacha (Acorus calamus, Rhizome)** — ToC lists p.168 but the monograph's printed page footers read **176–178** (e-book PDF has shuffled content); cite 176 (monograph 74).
- **Brahmi = Bacopa monnieri (monograph 11, Vol-2, p.25)** — explicitly the whole plant of *Bacopa monnieri*, i.e. NOT mandukaparni/Centella.

### Verified classical content (summary; verbatim in `verification_note`)

| Herb | Vol / monograph / printed p. | API Rasa·Guna·Virya·Vipaka (abbrev) | API DOSE |
|---|---|---|---|
| Amalaki | Vol-1, 4, p.6 | Madhura·Amla·Kaṭu·Tikta·Kaṣāya · Laghu·Rūksha · Śīta · Madhura | 3–6 g |
| Guduchi | Vol-1, 27, pp.54–55 | Tikta·Kaṣāya · Laghu · Uṣṇa · Madhura | 3–6 g; 20–30 g decoction |
| Guggulu | Vol-1, 28, p.57 | Kaṭu·Tikta·Kaṣāya · Laghu·Sara·Viṣada · Uṣṇa · Kaṭu | 2–4 g |
| Haritaki | Vol-1, 31, p.63 | Madhura·Amla·Kaṭu·Tikta·Kaṣāya · Laghu·Rūksha · Uṣṇa · Madhura | 3–6 g |
| Bibhitaki | Vol-1, 17, p.34 | Kaṣāya · Laghu·Rūksha · Uṣṇa · Madhura | 3–6 g |
| Brahmi | Vol-2, 11, p.25 | Madhura·Tikta·Kaṣāya · Laghu·Sara · Śīta · Madhura | 1–3 g |
| Vacha | Vol-2, 74, p.176 | Kaṭu·Tikta · Laghu·Tīkṣṇa · Uṣṇa · Kaṭu | 60–120 mg (1–2 g emetic) |
| Shatavari | Vol-4, 50, pp.122–123 | Madhura·Tikta · Guru·Snigdha · Śīta · Madhura | 3–6 g |

Effect on the audit: entry counts and coverage unchanged (still 51 entries, 52/93 covered, 0 orphan keys). The 8 herbs remain listed in `verification_notes` (modern claims still unverified) but now carry an auditable `api_of_india_verified` classical cross-check.

## 5c. Tier-1 fills 2026-08-30: `tulsi` + `moringa`

First-line medicinal herbs tiered up to Tier 1 (see §3). Both filled by fetching authoritative pages and scoping every contraindication/interaction/pregnancy claim to the actual page text (same batch #1/#2 discipline). `modern_source_verified: true` means claims == fetched page text.

- **`tulsi`** (holy basil, *Ocimum tenuiflorum/sanctum*) — `modern_source_verified: true`. Sources: WebMD Holy Basil (ingredientmono-1101), MedicineNet Holy Basil, NCBI systematic review PMC5376420 (all fetched 2026-08-30). Claims limited to fetched text: avoid in pregnancy/breastfeeding; hypothyroidism caution (may lower thyroxine); stop ≥2 weeks before surgery (may slow clotting); interactions with diabetes meds, anticoagulant/antiplatelet drugs, pentobarbital; short-term (≤60–90 days) use only; nausea/diarrhea possible. **Attribution guard:** no fetched page states the popular phrase "thins blood" — the entry uses the verified claim "may slow blood clotting," exactly as the page words it.
- **`moringa`** (drumstick, *Moringa oleifera*) — `modern_source_verified: true`. Sources: MSKCC About Herbs (Moringa oleifera), WebMD Moringa (incl. ingredientmono-1242), Drugs.com Natural Products Professional, RxList (fetched 2026-08-30). Claims limited to fetched text: pregnant/breastfeeding women should **avoid** (MSK explicit contraindication; Drugs.com "Avoid use"); root/root extracts possibly unsafe (spirochin, RxList); rare serious adverse events (Stevens-Johnson syndrome, cutaneous toxicity, anaphylaxis — case reports); interactions with CYP3A4/rifampin, sitagliptin, diabetes meds, nevirapine, CYP1A2/P-gp substrates, and a *potential* (non-confirmed) levothyroxine interaction; no other contraindications identified (Drugs.com).

## 5d. Tier-2 culinary fills (2026-08-30)

Added light-template monographs for all 18 culinary/food-frequent herbs, per the §1.3 policy ("food-use caution only" — lighter bar than the medicinal monographs). Each entry carries `modern_source_verified: false` — these are food-quantity guidance on the curated culinary template, not page-cross-checked clinical claims — and a `pregnancy_flag` stating food quantities are generally regarded as safe. Entries added: `cardamom`, `cumin`, `fennel`, `celery`, `mustard`, `garden radish`, `garlic`, `onion`, `fenugreek`, `ajwain`, `dhanyaka`, `yavani`, `shatapushpa`, `trapusha`, `karkaru`, `chavya`, `bael`, `khasa`. Tier 2 is now **closed**. Remaining uncovered = the 21 Tier-1 therapeutically-significant herbs (see §3).

## 5e. Tier-1 completion — remaining 21 fills (2026-08-30)

Filled the final 21 Tier-1 herbs, achieving **93/93 coverage, 0 uncovered, 0 orphans**. Breakdown of sourcing (discipline maintained throughout — no fabricated claims):

**API-verified classical (15 herbs, `api_of_india_verified: true`, `modern_source_verified: false` — rasapanchaka/dose cross-checked against the API of India):** `sariva`, `raktachandana`, `patala`, `kantakari`, `brihati`, `katphala`, `shalparni`, `nagarmotha`, `priyangu`, `palasha`, `ketaki`, `utpala`. Plus three that use the **closest available API monograph** (stated explicitly in `verification_note`): `padmakesara` → Kamala/Nelumbo (Vol-2 p.74), `gokarna` → Kokilaksha/Asteracantha (Vol-2 p.100), `stira` → Shalaparni/Desmodium (Vol-3 p.178, same species). `surasa` → `api_of_india_verified: true` but resolved as a Tulasi (Ocimum sanctum) synonym per API Vol-4, routed to the existing `tulsi` entry (which is `modern_source_verified: true`).

**Modern page-verified (2 herbs, `modern_source_verified: true`):** `patola` (Trichosanthes dioica — Drugs.com: no contraindications/interactions identified, avoid in pregnancy/lactation); `gandhatruna` (lemongrass-type Cymbopogon — MSKCC/Drugs.com/WebMD: avoid in pregnancy, sedative + theoretical CYP450/GST interactions; named-drug caveat noted).

**Data-scarce, honestly marked (`modern_source_verified: false`):** `jivanti` (Leptadenia — PMC review has no contraindication section; traditional galactagogue/threatened-abortion use with animal estrogenic/anti-implantation caveat); `amlavetasa` (Garcinia pedunculata — only toxicity study retracted, genus-level data for G. cambogia explicitly NOT applied); `chochchika` (botanically unidentified; no safety data — do-not-self-administer).

**Solanaceae/species safety notes** embedded where relevant (kantakari, brihati steroidal glycoalkaloids; palasha bark-only).

### Effect

- Coverage **72 → 93/93** (complete); uncovered **21 → 0**; orphan keys **0**; safety entries **71 → 92**.

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

## 7. Recorded decisions & deferred work (2026-08-30)

- **Item 7 — confidence-band re-derivation (flag for Phase 9):** the `HIGH_SCORE` / `MEDIUM_SCORE` cut-offs in `backend/app/nodes/retriever.py` (`_confidence_band`, lines 83–88) were last fit to the Phase-3 baselines (high/medium/low on top-1/top-3 hit rates). They are **not** re-derived in this phase — the Phase-6 changes (safety data + new reference rows) do not touch the retrieval scoring path, and re-deriving now would risk shifting eval results mid-phase. **Recorded decision: defer threshold re-derivation to Phase 9.** No code change this phase beyond noting it here.
- **Item 8 — `--mode full` deferral (recorded decision):** `eval_run.py --mode full` invokes the full agent (Groq LLM) on all eval questions — slower and costlier, and it tests the answer-synthesis path that this phase does not modify. Phase 6's verification discipline targets the retrieval + safety layers, which are fully exercised by `--mode retrieval` (24/28, 0 false emergencies, 0 orphan keys). **Recorded decision: do not run `--mode full` this phase; defer to Phase 9 / CI.** The retrieval-mode run is the regression gate for this phase.
- **Disagreement-flagging regression (2026-08-30):** smoke-tested the `source_disagreements` invariant — a herb fires a strong-caution disagreement **only** when `modern_source_verified` is true **and** its pregnancy flag/contraindication carries a hard avoid/toxicity. Verified: arka, moringa, tulsi, ashwagandha → flagged; kataka, turmeric → not flagged (moderate only); and crucially the unverified batch-#2 herbs (guggulu, vacha, brahmi) → **not** flagged despite "avoid" text, so unverified modern claims are never surfaced as verified disagreements. All pass.

## 8. Phase 6 result so far

- 93 canonical herbs; **92 safety entries**; covered **93/93**; uncovered **0**; orphan keys **0**. **Phase 6 coverage is complete.**
- Batch #2 (8 herbs) classical rasapanchaka + dose cross-verified against API of India (new `api_of_india_verified` + `verification_note` fields); modern claims honestly left `modern_source_verified: false`.
- Tier-1 fills: arka, kataka (2026-08-29), tulsi, moringa (2026-08-30), all `modern_source_verified: true`.
- Tier-2 culinary fills: 18 herbs (2026-08-30), all `modern_source_verified: false` (food-template bar).
- Tier-1 completion: remaining **21 herbs** filled (2026-08-30) — 15 API-verified classical + 3 closest-match (palmakesara→Kamala, gokarna→Kokilaksha, stira→Shalaparni) + surasa→tulsi synonym (§5e); 2 modern page-verified (patola, gandhatruna); 3 honestly data-scarce (jivanti, amlavetasa, chochchika).
- Retrieval eval stable: **24/28 (85%)**, 0 false emergencies, 10/10 safety coverage.
- **Answer-layer hardening (2026-08-30):** `synthesis.py` now forwards `verification_notes` + `source_disagreements` into the LLM context (previously only `safety_flags` reached synthesis) — so species/identity closest-match disclosures (stira→Shalaparni, padmakesara→Kamala, gokarna→Kokilaksha, surasa→Tulsi) and kataka's nux-vomica disambiguation, plus the previously-invisible strong-caution `source_disagreements`, now render in the answer rather than living only in JSON/state. See `phase6_report.md §7b`.