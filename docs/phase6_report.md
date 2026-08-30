# Phase 6 Report — Safety-Data Coverage & Verification

> Complete report of everything done in Phase 6 ("Safety & Trust Layer"), covering all commits from `aac78d6` (2026-08-29) through `90540dc` (2026-08-30).
> Companion detail doc: `docs/phase6_safety_coverage.md` (decision log + per-batch notes).
> Status: **coverage complete** — 93/93 herbs covered, 0 uncovered, 0 orphan keys, eval stable.

---

## 1. Goal

Every herb the retrieval layer can serve for medicinal guidance must have a safety monograph — or an explicit, *visible* "no monograph" advisory. The phase's intent was to close the data-completeness gap (the largest open item from the Phase 5 close-out) while holding the strictest possible standard about **data provenance**: never presenting AI-compiled claims as "verified" unless they were actually page-cross-checked.

---

## 2. What "covered" means (the definitions we locked in)

- **Canonical herb** = a name in `backend/reference/herbs.json` (93 after alias/de-dup merges).
- **Safety entry** = one record in `backend/reference/herb_safety.json` addressable by the canonical herb or one of its aliases.
- **Covered** = the canonical herb resolves (itself or via alias) to a safety entry.
- **Orphan** = a safety key reachable from no herb — a data-integrity defect. Target: 0.

| Governing rule | Value |
|---|---|
| `modern_source_verified` | `true` **only** when claims == fetched page text (same-day fetch; cite actual page). |
| `api_of_india_verified` | `true` when the *classical* rasapanchaka + dose were cross-checked against a named API-of-India monograph. The API states classical rasa/guna/virya/vipaka/karma + uses + dose, but **not** modern contraindications/interactions/pregnancy flags — so a `true` here does **not** flip `modern_source_verified`. |
| Culinary herbs | lighter bar (food-use caution only) but still get an entry so the monolayer is uniform. |
| Runtime transparency | an uncovered herb surfaces a visible advisory ("no safety monograph on file — use only in food quantities…") — **never a silent gap**. |

---

## 3. Coverage progression (the numbers that moved)

| Point in time | Safety entries | Covered | Uncovered | Orphans |
|---|---|---|---|---|
| Phase 5 close-out (start) | 51 | 52/93 | 41 | 0 |
| `aac78d6` (transient, pre-arka/kataka) | 51 | 52/93 | 43 | 0 |
| `aac78d6` (end) — arka/kataka filled | 51 | 52/93 | 41 | 0 |
| `49304ce` — batch #2 + tulsi/moringa + 18 culinary | 71 | 72/93 | 21 | 0 |
| `90540dc` — final 21 Tier-1 fills | **92** | **93/93** | **0** | **0** |

> Reconciliation note: uncovered briefly reads **43** immediately after the Tier-3 alias merges (96→93 herbs, gap 46→43) and drops to **41** once `arka`/`kataka` are filled within `aac78d6`. The end-of-commit value (41) is what the §4 prose and validation report; 52 covered + 41 uncovered = 93 canonical herbs, so the numbers are consistent throughout.

Final breakdown of the 92 entries by verification status:
- `api_of_india_verified: true` → **24**
- `modern_source_verified: true` → **9**
- All 24 API-verified entries are `modern_source_verified: false` (honest separation of classical vs modern evidence).

---

## 4. The work, commit by commit

### 4.1 `aac78d6` — Tier-3 merges, top-priority toxic fills, audit tool, MCP child hygiene (2026-08-29)

**Tier-3 dedup / alias reconciliation (closed).** Three herbs had zero own verse mentions (verified against `processed/herb_mentions.json`); removed the empty rows and folded unique aliases into the canonical:
- `haridra` → rm; `turmeric` ↔ alias `curcuma` (**genuine coverage close**).
- `bilva` → rm; `bael` ↔ alias `bengal quince` (list hygiene only — bael itself stayed uncovered).
- `ushira` → rm; `khasa` ↔ alias `ushira` (list hygiene only).
Net: 96 → **93 herbs**, gap 46 → 43.

**Highest-priority toxic fills — `arka` + `kataka`.**
- `arka` (*Calotropis gigantea/procera*) — genuinely toxic (cardiac glycosides: calotropin, calatoxin, uscharin; digitalis-like toxicity; latex is skin/corneal irritant; traditional abortifacient). Fetched primary source (Hong Kong Hospital Authority Atlas of Poisonous Plants + IVIS + PMC7586564 case report). Filled as `modern_source_verified: true` with a hard **"strictly avoid"** pregnancy flag + digitalis interactions + do-not-self-administer caution.
- `kataka` — **species correction.** Charaka's kataka = *Strychnos potatorum* (clearing nut), **not** the poisonous strychnine tree (*S. nux-vomica*). PMC3931202: OECD-423 acute test **non-toxic up to 2000 mg/kg**; the injected seed-alkaloid fraction is neuroactive, so the entry keeps to classical small oral doses. The misleading `strychnine tree` alias was deliberately kept so the entry (not a miss) answers that query and corrects the species.

**Code: `backend/scripts/audit_safety_coverage.py`** — the coverage gate. Exits non-zero on any orphan key; prints covered/uncovered/orphan counts. `retriever.py` metric-consistency fix. `safety.py` grew the `uncovered` attribution path. `herbs.json` alias changes. Phase-6 doc + Phase-5 report updated.

### 4.2 `ea27ef6` — MCP child-kill fix (2026-08-29)

Fixed a missing f-string prefix in the subprocess child-kill query (`_kill_mcp_children`) and quieted subprocess request logging. This is the process-hygiene item from the Phase-5 review: lingering `mcp_server.py` subprocesses were being selected/killed incorrectly.

### 4.3 `49304ce` — Batch #2 API verification + Tier-1/2 fills + MCP BFS rewrite (2026-08-30)

**Batch #2 — classical cross-verification against the API of India (8 herbs).** brahmi, guggulu, shatavari, guduchi, amalaki, haritaki, bibhitaki, vacha. Fetched and text-extracted (pypdf) the actual API PDFs same-day (Vol-1/2 via `ayurveda.hu` mirror; Vol-4 via `naturalingredient.org`). Added two new JSON fields on all 8:
- `api_of_india_verified: true` — classical rasapanchaka + dose verified against the named monograph.
- `verification_note` — volume + monograph no./name + printed page + the verified classical text (auditable evidence).
**`modern_source_verified` left `false`** and the note explicitly says the API does not confirm the listed modern claims — this is the integrity guard learned from the batch-#1 correction (never flip `modern_source_verified` from API evidence, since the API states no modern contraindications/interactions/pregnancy flags).

**Volume corrections found during the work:**
- `shatavari` is API **Vol-4** (monograph 50, pp.122–123), **not** Vol-3.
- `vacha` ToC says p.168 but printed footers read **176–178** (shuffled e-book PDF).
- `brahmi` = **Bacopa monnieri** (Vol-2, monograph 11, p.25) — not mandukaparni/Centella.

**Tier-1 fills — `tulsi` + `moringa`** (both `modern_source_verified: true`, scoped to fetched page text):
- `tulsi` (holy basil): WebMD + MedicineNet + NCBI systematic review PMC5376420 — avoid in pregnancy/breastfeeding; hypothyroid caution; stop ≥2 weeks before surgery; interactions (diabetes meds, anticoagulants/antiplatelets, pentobarbital); ≤60–90 day use; nausea/diarrhea. **Attribution guard:** no fetched page says "thins blood" — the entry uses "may slow blood clotting" exactly as the page words it.
- `moringa`: MSKCC + WebMD + Drugs.com + RxList — pregnant/breastfeeding **avoid**; root/root extracts possibly unsafe (spirochin); rare serious AEs (Stevens-Johnson, cutaneous toxicity, anaphylaxis case reports); interactions (CYP3A4/rifampin, sitagliptin, diabetes meds, nevirapine, CYP1A2/P-gp, potential levothyroxine).

**Tier-2 culinary fills (18, closed).** Light-template monographs (`modern_source_verified: false`, food-quantity bar): cardamom, cumin, fennel, celery, mustard, garden radish, garlic, onion, fenugreek, ajwain, dhanyaka, yavani, shatapushpa, trapusha, karkaru, chavya, bael, khasa.

**Code:** `safety.py` — `verification_notes` now appends "(classical rasapanchaka/dose cross-checked against the API of India monograph…)" when `api_of_india_verified`; and the `_kill_mcp_children()` BFS descendant-tree rewrite (item 5 from the Phase-5 review).

Coverage: 53 → **71** entries; **72/93** covered; uncovered **21**; 0 orphans; eval stable.

### 4.4 `90540dc` — final 21 Tier-1 fills → coverage complete (2026-08-30)

Extended the API-verification workflow to the remaining 21 therapeutically-significant herbs. Breakdown of sourcing (every claim traceable, none fabricated):

**15 API-verified classical** (`api_of_india_verified: true`, `modern_source_verified: false`): sariva, raktachandana, patala, kantakari, brihati, katphala, shalparni, nagarmotha, priyangu, palasha, ketaki, utpala — plus three that use the **closest available API monograph** (stated in `verification_note`):
- `padmakesara` → Kamala/Nelumbo (Vol-2, p.74)
- `gokarna` → Kokilaksha/Asteracantha (Vol-2, p.100)
- `stira` → Shalaparni/Desmodium (Vol-3, p.178 — same species as shalparni)
- `surasa` → `api_of_india_verified: true`, resolved as a **Tulasi (Ocimum sanctum) synonym** per API Vol-4, routed to the existing `tulsi` entry.

**2 modern page-verified** (`modern_source_verified: true`):
- `patola` (Trichosanthes dioica) — Drugs.com: no contraindications/interactions identified; avoid in pregnancy/lactation.
- `gandhatruna` (lemongrass-type Cymbopogon) — MSKCC/Drugs.com/WebMD: avoid in pregnancy, sedative + theoretical CYP450/GST interactions; named-drug caveat recorded.

**3 data-scarce, honestly marked** (`modern_source_verified: false`):
- `jivanti` (Leptadenia reticulata) — PMC review has no contraindication section; traditional galactagogue/threatened-abortion use with animal estrogenic/anti-implantation caveat.
- `amlavetasa` (Garcinia pedunculata) — the only species-specific toxicity study is **retracted**; genus-level G. cambogia data explicitly NOT applied.
- `chochchika` — botanically **unidentified**; no safety data; do-not-self-administer.

**Embedded species/safety notes:** Solanaceae steroidal glycoalkaloids (kantakari, brihati), palasha bark-only security.

**Effect:** coverage **72 → 93/93 (complete)**; uncovered **21 → 0**; orphans **0**; entries **71 → 92**.

---

## 5. How verification discipline was enforced (the methodology)

1. **Fetch before flip.** Every `modern_source_verified: true` was produced only after fetching the actual page (same-day) and scoping every contraindication/interaction/pregnancy claim to the fetched text.
2. **Batch-#1 lesson.** A reviewer caught that some early NCCIH "verified" claims (ashwagandha "2 weeks before surgery", turmeric gallstones, liquorice hypokalemia, etc.) were **not on the cited pages**. All three entries were re-scoped so claims == page text; removed claims were logged for return via a real second source. This is why `modern_source_verified` is defined precisely as *claims == fetched page text*.
3. **API vs modern separation.** `api_of_india_verified` records the *classical* cross-check; it never flips `modern_source_verified`, because the API does not state modern contraindication/interaction/pregnancy claims.
4. **Honest data-scarce flags.** Where no reliable second source exists (jivanti, amlavetasa, chochchika), the entry says so rather than inventing claims.
5. **Runtime transparency** (`safety.py`): `safety_sources` includes a visible `"uncovered"` value; `verification_notes` discloses every not-yet-verified entry; `source_disagreements` (rule-driven, not hand-written) flags only *verified* entries whose modern source carries a hard avoid/toxicity.

---

## 6. Regression & validation results

- **Audit gate** (`audit_safety_coverage.py`): **93/93 covered, 0 uncovered, 0 orphans** ✅.
- **Retrieval eval** (`eval_run.py --mode retrieval`): **24/28 (85%)** top-1, 25/28 (89%) top-3, **0 false emergency positives**, **10/10 safety coverage**. Identical to the pre-fill baseline — no regression. (The 4 misses are pre-existing retrieval-resolution cases, unrelated to safety data.)
- **`--mode full` deferred** (recorded decision): the LLM synthesis path this phase doesn't modify; retrieval mode is the regression gate.
- **Disagreement-flagging invariant** (smoke-tested): fires **only** when `modern_source_verified` is true **and** pregnancy/contraindication carries hard avoid/toxicity.
  - Flagged: arka, ashwagandha, tulsi, moringa, patola, gandhatruna, liquorice.
  - Not flagged: kataka, turmeric (moderate only); all unverified API/data-scarce herbs (guggulu, vacha, brahmi, jivanti, amlavetasa, chochchika) — unverified modern claims are never surfaced as verified disagreements.

---

## 7. Recorded decisions / deferred work (Phase 6 → Phase 9)

- **Item 7 — confidence-band re-derivation deferred.** `HIGH_SCORE`/`MEDIUM_SCORE` cut-offs in `retriever.py` were last fit to Phase-3 baselines; re-deriving mid-phase risks shifting eval. Deferred to Phase 9. No code change this phase.
- **Item 8 — `--mode full` deferred** to Phase 9 / CI (tests a path this phase doesn't modify).
- **Deferred fresh cross-verification** of the remaining modern claims in older entries — disclosed per-entry via `verification_notes`; queued for separately-checked second sources.

---

## 7b. Answer-layer hardening — disclosures now reach the rendered answer (2026-08-30, post-review fix)

A design review flagged two trust-layer risks that lived only in the internal JSON/`verification_note`, not in the answer a user actually reads (`synthesis.py` forwarded only `safety_flags`, never `verification_notes` or `source_disagreements`):

1. **Kataka species disambiguation.** The correction (*Charaka's kataka = Strychnos potatorum*, NOT the toxic *S. nux-vomica*) sits in `contraindications[0]` → reaches `safety_flags` → rendered. Verified surfaced, but as one item in a flags list against a deliberately-kept `strychnine tree` alias — a potential misread.
2. **Closest-match substitutions (padmakesara→Kamala, gokarna→Kokilaksha, stira→Shalaparni, surasa→Tulsi).** For `stira` the stand-in disclosure lived only in `verification_note` and did **not** reach the user. (**Third gap found:** `source_disagreements` — the strong-caution practitioner notes for arka/moringa/tulsi/ashwagandha — were computed and stored in state but never forwarded to the LLM.)

**Fix (`synthesis.py`):** the assembled LLM context now includes two explicit sections when present — `SPECIES/IDENTITY DISCLOSURES & VERIFICATION NOTES` (from `state['verification_notes']`) and `SOURCE DISAGREEMENTS` (from `state['source_disagreements']`), both of which `check_safety` already writes into state. The system prompt now instructs the model to state species/identity disclosures **prominently and before** remedy/safety detail, and to render source disagreements verbatim as practitioner-review cautions.

**Live-generation check (2026-08-30) — a targeted `--mode full`-style run of the exact fixed cases, not just a context check:**
- **kataka** — generated answer states the disclosure prominently *before* any remedy detail: "Species/Identity Disclosure: Charaka's 'kataka' refers to *Strychnos potatorum* … It must **not** be confused with the poisonous *Strychnos nux-vomica* (the true strychnine tree)." ✅
- **arka** — `source_disagreements` is populated and the generated answer's safety section renders the strong caution (Strictly avoid; abortifacient; cardiac-glycoside toxicity; latex risk; do-not-self-administer). ✅
- **padmakesara** — generated answer states: "The safety profile is based on the closest-match species *Kamala* (lotus flower); there is no separate monograph for padmakesara (lotus stamens)." ✅

So for reachable herbs the mechanism is genuinely wired end-to-end (generation confirms rendering, not just prompt construction).

**Reachability finding (also surfaced by the live run):** the disclosures can only render for herbs the retrieval layer can actually surface. 22 of the 92 safety entries have **zero rows in `processed/herb_mentions.json`**, so `check_safety` can never fire them. The earlier draft's claim that "stira's disclosure now renders" was therefore premature. **This is a retrieval/herb-detection gap, distinct from the safety-data fill (which is 100% in the file).**

**Alias-gap vs corpus-gap diagnostic (2026-08-30) — a raw-text search of all 2,490 ingested verses (English + Sanskrit) classified the 22 decisively:**

**ALIAS-GAP (10 — the herb IS in the corpus under a different name; fix = add the alias/merge):**
- `eranda` ← **castor** (25×), `nagarmotha` ← **musta** (6×), `trikatu` ← **three spices** (37×), `rasna` ← **vanda** ("vanda orchid", 4×), `ketaki` ← **screw pine** (3×), `katphala` ← **box myrtle** (3×), `raktachandana` ← **red sandal** (2×), `surasa` ← **holy basil** (14×), `fenugreek` ← **methi** (2×), `atibala` ← **country mallow** (1×).
- ⚠️ Several are near-duplicates of existing canonical herbs (e.g. eranda↔castor, surasa↔tulsi/holy basil); a safe fix is a Tier-3-style merge like haridra→turmeric, and must be wired through `check_safety` and verified end-to-end — deferred to a focused follow-up, not rushed into this pass.

**CORPUS-GAP (12 — genuinely absent from the ingested 20-chapter subset; the plant exists in the full Samhita but outside the subset):** `jivanti`, `chochchika`, `priyangu`, `nagakesara`, `shalparni`, `stira`, `gokarna`, `brihati`, `bibhitaki`, `daruharidra`, `ajwain`, `yavani`. **Not a bug — a corpus-scope limitation.** The honest fix is expanding the corpus, which is **explicitly Phase 11 work** ("expand corpus... after core system validated"). Verified zero occurrences across canonical names, all `herbs.json` aliases, and a broad set of plausible English/Sanskrit renderings.

**Audit-script extension (2026-08-30):** `audit_safety_coverage.py` now runs a third check — **runtime reachability** — in addition to covered/orphan. It reports `runtime-reachable: 70/92` and lists the 22 unreachable entries (advisory, with alias-vs-corpus guidance), so the next herb-filling batch surfaces the gap automatically instead of requiring a manual live-run spot-check. README's safety/coverage claims updated so the reported number matches user-reachable reality, not just file completeness.

## 8. Files touched this phase

| File | Change |
|---|---|
| `backend/reference/herb_safety.json` | 51 → **92 entries**; new fields `api_of_india_verified`, `verification_note`; all 41 originally-uncovered herbs filled |
| `backend/reference/herbs.json` | Tier-3 dedup/alias merges (haridra, bilva, ushira); kept `strychnine tree` alias on kataka deliberately |
| `backend/app/nodes/safety.py` | `uncovered` attribution; `verification_notes` API cross-check note; `source_disagreements` rule; `_kill_mcp_children()` BFS rewrite + f-string fix |
| `backend/app/nodes/synthesis.py` | forward `verification_notes` + `source_disagreements` into the LLM context so species/identity disclosures and practitioner-review cautions reach the answer (§7b) |
| `backend/app/nodes/retriever.py` | metric-consistency fix |
| `backend/app/mcp_server.py` | quieter subprocess request logging |
| `backend/scripts/audit_safety_coverage.py` | **new** — coverage/orphan gate |
| `docs/phase6_safety_coverage.md` | decision log, per-batch notes, result |
| `docs/phase5_report.md` | close-out cross-references updated |

Commits: `aac78d6` → `ea27ef6` → `49304ce` → `90540dc` (all on `main`, pushed).
