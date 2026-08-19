---
name: investment-memo-writing
description: Use when drafting, structuring, or reviewing sections of the investment memo, building memo prompt templates for the synthesizer/red-team/synthesizer pipeline, or checking a memo section for earnings-quality red flags.
---

# Investment Memo Writing

Actionable guidance for constructing prompts and templates for this system's memo pipeline: **draft synthesizer -> red-team attacker -> resolving synthesizer** (the resolving pass's output is the memo actually delivered). This skill governs section structure, what separates a real section from filler, the earnings-quality checklist to build into red-team and drafting prompts, and — critically — which sections this free-data-only MVP can actually ground vs. must defer.

**Non-negotiable rule underlying everything below**: every quantitative claim in the memo must trace to a typed input field (an EDGAR accession/XBRL tag, a FRED series ID, a priced date from the price feed). If a section or sub-claim cannot be traced that way with the MVP's data sources, it does not go in the memo as a fact — it goes in as an explicitly flagged assumption/estimate, or the sub-claim is cut. This is the filter behind every INCLUDED/DEFERRED call below.

**MVP data sources (the only ones any section may cite):**
1. **SEC EDGAR** — 10-K, 10-Q, 8-K (all items, incl. 4.01 auditor changes, 4.02 restatements, 5.02 officer departures), structured XBRL financials, DEF 14A proxy (related-party, comp), Forms 3/4/5 (insider transactions). Full-text search covers non-XBRL prose (MD&A, Item 1A risk factors, non-GAAP reconciliation tables in 8-K Ex-99.1 press releases).
2. **FRED** — macro series (rates, inflation, unemployment, sector-relevant series) for discount-rate inputs and macro risk framing.
3. **A free daily price source** (yfinance/Stooq-class) — daily OHLC, no intraday, no options data.

Explicitly **not** available: analyst/consensus estimates, sell-side price targets, earnings call transcripts, real-time short interest, management-tone commentary. Never let a drafting prompt imply these exist.

---

## 1. Section Structure, Purpose, and Good-vs-Boilerplate

Ten sections, in the order a reader expects them. For each: what it's for, what separates a real version from filler, and its MVP status.

### 1. Executive Summary & Recommendation
**Purpose**: One paragraph that gives the rating, the one-sentence thesis, and the 2-3 numbers that matter, before any scene-setting.
**Good vs. boilerplate**: Good — leads with the recommendation and the sharpest number (e.g., "trading at 40% below a DCF grounded in FY23-25 filed cash flows discounted at the FRED 10Y + equity risk premium"). Boilerplate — "Company X is a leading provider of..." followed by the rating buried three paragraphs down. If you could paste this paragraph onto a different ticker in the same sector and it would still read true, it's boilerplate.
**MVP status**: **INCLUDED** — pure synthesis of the sections below.

### 2. Investment Thesis
**Purpose**: State what the market is getting wrong and why, in 2-3 falsifiable pillars, not an exhaustive list of nice-to-haves.
**Good vs. boilerplate**: Good — each pillar names a specific, checkable driver ("gross margin holds above 35% because X") with a stated break condition ("if segment margin drops below 35% for two consecutive quarters, this pillar is wrong"). A thesis that rests solely on multiple re-rating with flat/consensus earnings is low-quality — sell-side literature treats it as the single clearest boilerplate tell. Boilerplate — vague claims ("well positioned to benefit from industry tailwinds") with no numeric trigger and no way to know when the thesis has broken.
**MVP status**: **INCLUDED, with a required reframe.** Classic buy-side theses lean on "variant perception vs. sell-side consensus" — that comparison point does not exist here. Reframe variance against: (a) what the current price *implies* via a reverse-DCF using filed cash flows, (b) the company's own historical trend in filed fundamentals (margin, returns on capital, growth), or (c) FRED-derived macro backdrop. Never phrase a pillar as "vs. Street expectations" — there is no Street data behind it.

### 3. Business Overview
**Purpose**: Segment economics and revenue mix drivers, not a company description.
**Good vs. boilerplate**: Good — segment-level revenue/margin trends over multiple filed periods, customer/geographic concentration with real percentages, tied forward to why it matters for the thesis. Boilerplate — restating 10-K Item 1 prose verbatim ("the Company is a global leader in...").
**MVP status**: **INCLUDED** — 10-K Item 1 narrative plus XBRL segment-level `Revenues`/`SegmentReportingDisclosure` tags where tagged.

### 4. Financial Analysis
**Purpose**: Multi-year trend of the ratios that actually matter to this thesis — margins, returns on capital, leverage, cash conversion — not a data dump of every line item.
**Good vs. boilerplate**: Good — a trend table (3-5 fiscal years/quarters from filed XBRL) with called-out inflection points, each tied back to a thesis pillar or a red flag. Boilerplate — a wall of ratios with no interpretation of which ones move the thesis.
**MVP status**: **INCLUDED** — this is the strongest section given the data sources; XBRL gives clean, comparable, typed multi-period figures.

### 5. Earnings Quality & Red Flags
**Purpose**: Run the checklist in Section 2 below against the filed financials and flag what's checkable — this section exists specifically to catch what a naive read of GAAP earnings would miss.
**Good vs. boilerplate**: Good — each flag is a computed number against a stated threshold with the source tag cited ("AR grew 18% vs. revenue 9% over the trailing four quarters — DSO extended from 42 to 51 days; XBRL tags `AccountsReceivableNetCurrent`, `Revenues`"). A disclaimer-shaped risk list ("the Company faces competitive and regulatory risk") is not earnings-quality analysis — it's the thing this section exists to avoid.
**MVP status**: **INCLUDED** — nearly every signal in the standard checklist is computable from EDGAR/XBRL or derivable from specific 8-K item types. See Section 2.

### 6. Valuation
**Purpose**: At least two triangulated methods with disclosed assumptions and a scenario range, not a single point estimate.
**Good vs. boilerplate**: Good — DCF with discount rate explicitly sourced (e.g., FRED 10Y Treasury + an equity risk premium assumption, stated as an assumption not a fact) and bull/base/bear cases; cross-checked against a self-built peer multiple using filed trailing financials for a defined peer set. Boilerplate — a single DCF with unstated WACC pulled from nowhere, or a comp table with no stated peer-selection logic.
**MVP status**: **PARTIALLY INCLUDED.** Trailing/LTM DCF (price feed + filed cash flows + FRED risk-free rate) — **INCLUDED**. Self-constructed peer multiples using EDGAR-sourced peer financials (same SIC code) — **INCLUDED**. Forward multiples benchmarked to consensus/Street estimates, or any relative-valuation claim that implicitly assumes analyst forecasts — **DEFERRED**, no free consensus source exists.

### 7. Catalysts
**Purpose**: 2-3 dated, verifiable events in the next 6-12 months that would close the gap between price and thesis.
**Good vs. boilerplate**: Good — hard catalysts with real dates (next 10-Q filing deadline, disclosed debt maturity, disclosed contract/patent expiration, a FRED-tracked macro data release relevant to the sector). Boilerplate — "continued execution" or "margin expansion over time" with no date attached.
**MVP status**: **PARTIALLY INCLUDED.** Filing-calendar and disclosed-schedule catalysts (debt maturities, contract/patent expirations in footnotes, next filing due date) — **INCLUDED**. Catalysts that depend on management guidance tone, earnings-call commentary, or anticipated estimate revisions — **DEFERRED**, no transcript or consensus-revision data available.

### 8. Risks & Mitigants
**Purpose**: Company-specific, quantified downside scenarios — reverse the catalysts and ask what breaks the thesis.
**Good vs. boilerplate**: Good — "if X occurs, expect Y% downside because Z" with a stated probability/severity view, sourced from the same red flag checklist and Item 1A filtered down to what's actually specific to this company. Boilerplate — copying Item 1A's generic legal/macro risk list verbatim; every 10-K in the sector has the same one.
**MVP status**: **INCLUDED** — 10-K Item 1A as raw material (must be filtered, not copied), the red flag checklist, and FRED-derived macro risk framing. This section is exactly what the red-team pass in Section 3 below exists to stress-test.

### 9. Recommendation & Sizing
**Purpose**: Tie the rating and conviction level explicitly back to the thesis pillars and the valuation gap.
**Good vs. boilerplate**: Good — states conviction tier and exactly what would raise/lower it. Boilerplate — a rating with no stated link to the thesis pillars above it.
**MVP status**: **PARTIALLY INCLUDED.** Rating (Buy/Hold/Sell) and a qualitative conviction tier (High/Medium/Low, tied to thesis-pillar count and valuation margin of safety) — **INCLUDED**. Precise dollar/percent-of-portfolio position sizing (Kelly-style, risk-budget, correlation-adjusted) — **DEFERRED**: this is a single-ticker MVP with no portfolio-level state (existing holdings, risk budget, correlation data), so there is nothing to size against. Output a conviction tier, not a sizing number.

### 10. Appendix / Sourcing
**Purpose**: Every figure cited anywhere in the memo, with its typed source (accession number + XBRL tag, FRED series ID + vintage date, price feed date).
**Good vs. boilerplate**: Good — a literal traceability table. Boilerplate — "Source: Company filings" with no pointer to which filing or field.
**MVP status**: **INCLUDED** — this section is not optional. It is the mechanical enforcement of the grounding rule; the red-team pass should check it against every other section.

---

## 2. Earnings-Quality Red Flag Checklist (build into drafting + red-team prompts)

All of these are computable from EDGAR/XBRL or a specific 8-K item type — i.e., all **INCLUDED** in the MVP. Cite the exact source alongside every flag raised.

| # | Signal | Detection | MVP data source |
|---|--------|-----------|------------------|
| 1 | Receivables growing faster than revenue | Compare YoY % growth of AR vs. revenue; flag if the gap is persistent and wide (e.g., >2x revenue growth rate) | XBRL `AccountsReceivableNetCurrent`, `Revenues` |
| 2 | Rising Days Sales Outstanding (DSO) | DSO = AR / Revenue x 365; flag a multi-quarter uptrend | Same tags, trended |
| 3 | Inventory growing faster than revenue/COGS | Compare YoY inventory growth vs. revenue/COGS growth | XBRL `InventoryNet`, `CostOfGoodsAndServicesSold` |
| 4 | Accruals / cash-earnings divergence (Sloan accruals) | Accruals = (Net Income - CFO) / Total Assets; large positive and rising is a classic manipulation signal | XBRL `NetIncomeLoss`, `NetCashProvidedByUsedInOperatingActivities`, `Assets` |
| 5 | Weak cash conversion | Cash conversion ratio = CFO / Net Income; flag if persistently <0.8 or trending down | Same tags |
| 6 | Capex vs. D&A divergence | Capex / D&A ratio; mature non-capex-heavy businesses typically run ~1.0-1.5x — flag a ratio consistently >2x or sharply rising without a stated growth-capex reason | XBRL `PaymentsToAcquirePropertyPlantAndEquipment`, `DepreciationDepletionAndAmortization` |
| 7 | Beneish-style component ratios (DSRI, GMI, AQI, SGI, DEPI, SGAI, LVGI, TATA) | Computable year-over-year from two consecutive years of filed XBRL; an M-Score above roughly -1.78 is the conventional flag threshold | XBRL, multi-year |
| 8 | Widening GAAP vs. non-GAAP gap | Track (non-GAAP EPS - GAAP EPS) over consecutive quarters; flag if the gap is large, growing, and recurring (same exclusion category every quarter), especially if it flips a GAAP loss to a non-GAAP profit | 8-K Ex-99.1 press release reconciliation table (full-text extraction, not XBRL-tagged) |
| 9 | Recurring "one-time" items | Count occurrences of restructuring/impairment/"special charge" line items across consecutive 10-Q/10-K periods; if it recurs >2 years running, it isn't one-time | 10-K/10-Q MD&A + income statement line items |
| 10 | Related-party transactions | Material transactions with officers/directors/affiliates, especially new or growing ones | DEF 14A proxy, 10-K footnotes |
| 11 | Auditor change | Flag any change, especially unexplained or paired with a going-concern/restatement disclosure | 8-K Item 4.01 |
| 12 | CFO/Controller/CEO turnover | Flag unexpected departures, especially clustered near a miss or restatement | 8-K Item 5.02 |
| 13 | Material weakness in internal controls | Any disclosed material weakness is a direct, strong flag | 10-K/10-Q Item 9A |
| 14 | Going-concern language | Any auditor going-concern opinion | 10-K audit opinion |
| 15 | Restatement | Non-reliance on previously issued financials is one of the strongest single flags available | 8-K Item 4.02 |
| 16 | Insider transaction pattern | Cluster of CFO/CEO selling outside a stated 10b5-1 plan, or absence of insider buying into a large drawdown — softer, corroborating signal, not a standalone flag | Forms 3/4/5 |
| 17 | Lengthening cash conversion cycle | DSO + DIO - DPO trend; a lengthening cycle corroborates flags #1-#3 | Derived from tags above |

**How to use this in the pipeline**: the drafting synthesizer should run this table against the ticker's filed data and only include a flag in Section 5 (Earnings Quality) if it is above threshold and cited to a source; the red-team pass should independently re-run this table looking for flags the draft omitted or soft-pedaled, and check that every raised flag has a real number and source rather than a vague characterization.

---

## 3. MVP Section Availability — Summary Table

| Section | Status | Reason |
|---|---|---|
| Executive Summary & Recommendation | INCLUDED | Pure synthesis of grounded sections |
| Investment Thesis | INCLUDED (reframed) | No consensus data — compare against reverse-DCF / own-history / macro, never "vs. Street" |
| Business Overview | INCLUDED | 10-K Item 1 + XBRL segment data |
| Financial Analysis | INCLUDED | XBRL gives clean multi-period structured data — strongest section |
| Earnings Quality & Red Flags | INCLUDED | Nearly all standard signals are EDGAR/XBRL/8-K derivable |
| Valuation — trailing DCF & self-built peer comps | INCLUDED | Price feed + filed cash flows + FRED risk-free rate; peer set built from EDGAR SIC codes |
| Valuation — consensus/forward relative multiples | DEFERRED | No free analyst-estimate source |
| Catalysts — filing/disclosed-schedule events | INCLUDED | Filing deadlines, debt maturities, contract/patent expirations from footnotes |
| Catalysts — guidance/estimate-revision driven | DEFERRED | No transcript or consensus-revision data |
| Risks & Mitigants | INCLUDED | Item 1A (filtered) + red flag checklist + FRED macro framing |
| Recommendation (rating + conviction tier) | INCLUDED | Directly tied to thesis pillars and valuation gap |
| Position Sizing (dollar/% of portfolio) | DEFERRED | Single-ticker MVP has no portfolio-level state (holdings, risk budget, correlation) to size against |
| Appendix / Sourcing | INCLUDED | Mechanical enforcement of the traceability rule |

**DEFERRED items overall, and why**:
- **Analyst/consensus estimates and sell-side price targets** — no free source; do not reference "Street numbers," "consensus," or "beat/miss vs. estimates" anywhere in the memo.
- **Earnings call transcripts / management tone** — no free transcript source; do not fabricate management commentary or paraphrase "guidance" beyond what's numerically stated in an 8-K press release.
- **Forward/consensus-relative valuation multiples** — depends on analyst forecasts that don't exist in this MVP; only trailing/LTM multiples and DCF are groundable.
- **Institutional ownership/crowding and short interest** — 13F data on EDGAR is real but lagged ~45 days and thin as a standalone signal; free real-time short interest doesn't exist within the three allowed sources. Treat positioning as out of scope rather than approximating it.
- **Precise position sizing** — requires portfolio-level inputs (existing holdings, risk budget, correlation) this single-ticker MVP doesn't have. Output a conviction tier instead of a sizing number.

---

## 4. Using This Skill Across the Three Pipeline Passes

**Pass 1 — Draft synthesizer.** Build the prompt around the 10-section structure in Section 1, instruct it to run the Section 2 checklist against the ticker's filed data, and require every quantitative sentence to carry an inline source pointer (feeds the Appendix). Explicitly instruct it not to write DEFERRED content — no consensus comparisons, no transcript-derived claims, no dollar sizing.

**Pass 2 — Red-team attacker.** Point it at exactly two failure modes: (a) any claim in the draft that cannot be traced to a typed field (hallucinated numbers, invented "guidance," implied consensus/Street comparisons that don't exist), and (b) boilerplate masquerading as substance per the "good vs. boilerplate" criteria above (generic risk-factor copy-paste, a thesis with no falsifiable trigger, an earnings-quality section that lists concerns without computing them against the Section 2 checklist). Its attack should cite the specific section, the specific sentence, and — where applicable — which checklist item was skipped or which source pointer is missing.

**Pass 3 — Resolving synthesizer.** For every attack raised, the resolution must either (a) re-ground the claim in a real typed field and keep it, (b) explicitly downgrade it to a stated assumption/caveat rather than a fact, or (c) cut it. Silently deleting a challenged claim without one of these three resolutions is not acceptable — the final memo should read as if it already survived the attack, not as if the attack was ignored.
