# Agents — Implementation Reference

For the agent roster's design intent (roles, I/O types, model tiers, capabilities), see `PRD.md`
§4 — that stays the source of truth for *intent*. This file is implementation-level detail once
an agent actually exists. Full design rationale for each agent also lives in its own
`.agents/plans/phase-N-*.md` file — this doc is the durable summary, the plan is the point-in-time
design record.

## Financial Statements Analyst (Phase 1)

**Module**: `src/agentic_fundamental_analyst/agents/financial_statements.py`
**Model**: `anthropic:claude-sonnet-5` (constant in `agents/models.py`, per the "model tier lives in
one shared place" convention). Confirmed working end-to-end against a real ticker (Phase 2 live
validation).
**Capabilities**: none (single-shot, no tools) — matches the PRD roster exactly.

**Input**: `RatioTrendBundle`, not raw `FinancialStatementBundle` or `FiscalPeriod`. The agent
never sees unaggregated XBRL data — only deterministically-computed ratios (annual/10-K periods
only, oldest first), each either a real value or a `RatioResult(value=None, reason=...)`. This is
a deliberate narrowing beyond the PRD roster's literal "Input type: FinancialStatementBundle" —
see the Problem/Solution section of `.agents/plans/phase-1-financial-statements-analyst.md` for
why: it keeps the agent's job pure interpretation (no arithmetic it could get wrong) and keeps
grounding cheap to check.

**Output contract, and why it's split in two**:
- `FinancialAnalystAgentOutput` (the agent's actual `output_type`): `summary: str` +
  `flag_candidates: list[FlagCandidate]`. A `FlagCandidate` names a `(metric, fiscal_year,
  fiscal_period)` triple, a `Severity`, and a `description` — **it has no numeric `value` field**.
  The model is never trusted to restate a number as ground truth.
- `FinancialAnalystOutput` (what the pipeline stage actually returns): built by
  `run_financial_statements_analyst()` after a deterministic grounding pass. `_ground_candidates()`
  looks up the real `RatioResult.value` for each candidate's metric/period in the `RatioTrendBundle`
  and constructs the final `Flag.source: SourcedFigure` from code; any candidate whose metric/period
  doesn't resolve to a real value is dropped into `dropped_candidates` (a diagnostic list, not part
  of the memo) rather than silently kept or silently discarded.

This means grounding for `Flag.source.value` is true **by construction** — there is no failure
mode where the model states a flag against a number it invented, because the model never states
the number at all. The remaining gap this doesn't close is *prose* grounding (numbers appearing in
`summary`/`description` text) — see `evals.md` for how that's checked.

**Coverage gaps**: `FinancialAnalystOutput.coverage_gaps` is the union of `bundle.coverage_gaps`
(data-layer gaps, e.g. unresolved XBRL tag) and `_ratio_unavailable_gaps()` — a `CoverageGap` for
every `RatioResult` with `value is None` in the trend bundle (e.g. Beneish unavailable because
there's no prior period). Fully deterministic; the agent has no input into this list at all.

**Instructions**: see the `_INSTRUCTIONS` constant in the module. Key points worth knowing if
revising the prompt: (1) explicitly tells the model it has no filing text, so a capex spike can
only ever be a *candidate* flag, never resolved — that's the Investigator's job later; (2) states
the seven checklist thresholds as starting points for judgment, not mechanical triggers; (3)
explicitly permits raising zero flags, to counter the model's instinct to always find something.

**Deviation from the PRD's `SourcedFigure` sketch**: PRD §3 illustrates
`source: "EDGAR:CIK...:us-gaap:Revenues:CY2024Q4"` (XBRL-tag-level). This agent's `source` is
coarser: `"ratios.{metric}:{ticker}:{fiscal_year}{fiscal_period}"`, because `FiscalPeriod` (Phase 0)
doesn't retain which XBRL tag resolved each field. Flagged as an open item to revisit before the
memo's Appendix section (Phase 5) needs filing-level citations.

## Grounding for prose input (Filings, Transcript — Phase 2)

Phase 1's trick (the agent names a `(metric, period)` triple into a closed table) needs a closed,
enumerable table to point at. Filing/transcript text has none, so these two agents use a different
mechanism: **verbatim quoted-evidence grounding**. Both candidate types (`FilingFlagCandidate`,
`TranscriptFlagCandidate`) carry `quoted_evidence: str` — the exact span of source text backing the
claim — instead of a numeric value. `agents/grounding.py::quote_is_grounded()` (shared by both)
checks that span is a real, whitespace-normalized substring of the exact source field the candidate
names, before promoting it to a `Flag` with `source: SourcedQuote` (a new sibling to `SourcedFigure`
in `contracts/sourcing.py` — `Flag.source` is now `SourcedFigure | SourcedQuote`, since a prose claim
has no natural numeric value and forcing one would be hollow typing). A candidate whose quote doesn't
verify verbatim is dropped into `dropped_candidates`, same "drop, don't trust" idiom as Phase 1.

This is intentionally strict on content, lenient only on whitespace: a paraphrased "quote" is
dropped, not fuzzy-matched. Full rationale (including two alternatives considered and rejected) in
`.agents/plans/phase-2-filings-transcript-consolidator.md`'s Problem/Solution section.

## Filings Analyst (Phase 2)

**Module**: `src/agentic_fundamental_analyst/agents/filings.py`
**Model**: `anthropic:claude-sonnet-5`. **Capabilities**: none.
**Input**: `FilingSections` (extended this phase — see `data-layer.md`). **Output**: split the same
way as Phase 1 — `FilingsAnalystAgentOutput` (agent's own type, `flag_candidates:
list[FilingFlagCandidate]`, no numeric value) vs. `FilingsAnalystOutput` (post-grounding, real `Flag`s).

Covers checklist items #8, 9, 11, 12, 13, 14, 15 (memo-writing skill §2) — **#9 and #14 are only
partially covered**: #9 (recurring one-time items) can only see a single 10-K's own narrative, not a
real multi-year trend; #14 (going-concern) is only caught if the language appears in Item 7/1A — the
formal audit opinion (Item 8) is not parsed. Stated explicitly in the agent's own instructions, not
just this doc, so the model doesn't overclaim either.

`run_filings_analyst(ticker: str, sections: FilingSections)` takes `ticker` as a separate argument
(unlike the other three agents' "the input type carries its own identity" pattern) because
`FilingSections` has no ticker field — it's keyed by `accession_number`, which is filer- not
ticker-scoped.

**Live cost note**: real-GOOGL calls have run $0.13–$0.28 (65K-132K input tokens) — a large 10-K's
Item 1/1A/7/9A plus merged 8-K bodies is Phase 1's first real jump in per-call token volume. No
truncation built yet; watch this in Logfire once Phase 5 wires the full pipeline.

## Transcript Analyst (Phase 2)

**Module**: `src/agentic_fundamental_analyst/agents/transcript.py`
**Model**: `anthropic:claude-sonnet-5`. **Capabilities**: none.
**Input**: `TranscriptInput | None`. **The model is never invoked at all when the input is `None`** —
`run_transcript_analyst()` short-circuits deterministically to a `CoverageGap`-only output before
any `Agent.run()` call. This is stronger than instructing the model to say "unavailable": it's
structurally impossible to fabricate commentary, because there's no call to fabricate it in. Verified
live: a `transcript_analyst_stage` span exists in Logfire only when a transcript was actually found.

Covers exactly one checklist-style signal, `management_tone_or_guidance_concern` (hedged/evasive
non-answers to direct questions, guidance walked back without explanation) — **this is this phase's
one piece of invented product scope**, not present in the memo-writing skill's 17-item checklist
(which explicitly treats transcripts as unavailable / out of scope for the general checklist; PRD §7
only carves out the narrow "opportunistic 8-K exhibit" case). Framed as a single, narrow, soft
corroborating signal on purpose — see the Phase 2 plan's Problem 5 for the full reasoning and how to
change it (a one-`Literal`-value edit to `TranscriptFlagMetric`) if the scope call looks wrong.

## Flag Consolidator (Phase 2)

**Module**: `src/agentic_fundamental_analyst/agents/flag_consolidator.py`
**Model**: `anthropic:claude-haiku-4-5-20251001` — the cheapest tier (PRD §4 roster), confirmed
working live. Runs *after* a deterministic exact-dedup pass (`flags.py::deduplicate_exact_flags`,
same `(metric, fiscal_year, fiscal_period)` key as Phase 1's own dedup logic would need), per PRD §4's
pipeline diagram: exact-dedup catches literal duplicate flags; the Consolidator agent's job is
*semantic* merges of genuinely different flags describing the same real-world issue.

Grounding here is index-based, not quote- or table-based, and maps to Phase 1's original trick more
directly than either analyst above: the input `list[Flag]` (post-dedup) really is a closed,
enumerable set, so the agent's own output type (`FlagGroupCandidate.flag_indices: list[int]`) never
restates a flag's content — only 0-based positions into the array it was given. `_resolve_groups()`
verifies every output group's indices are real, unused positions in the input list before
constructing a `ConsolidatedFlag`; any flag the model doesn't reference at all still survives as a
singleton group — a flag can never silently disappear during consolidation. Live-verified: correctly
grouped a real multi-year `capex_to_depreciation_ratio` flag sequence from GOOGL's real financials
into one `ConsolidatedFlag` with a "sustained multi-year escalation" summary.

## Investigator (Phase 3)

**Module**: `src/agentic_fundamental_analyst/agents/investigator.py`. **Model**:
`anthropic:claude-opus-5` (PRD §4 roster tier) — the system's **one and only agentic loop** (CLAUDE.md
hard constraint), and the only agent with `WebSearch`/`WebFetch` capabilities. Takes one
`ConsolidatedFlag` plus lightweight `SiblingFlagSummary` context for every *other* flag raised this
run (metric/period/description only — no extra tool calls, no sibling verdicts), and returns an
`InvestigationVerdict`: benign/concerning/unresolved, a hypothesis, cited evidence, and a confidence
score. `run_investigations(flags, max_investigations=5)` fans out `run_investigator` in parallel
(`asyncio.gather`, PRD §4) across up to `max_investigations` flags selected by severity; every flag
not selected surfaces as an explicit `CoverageGap` rather than being silently dropped.

**Grounding — the third mechanism in this codebase**, after Phase 1's closed-ratio-table lookup and
Phase 2's verbatim-quote check: **URL provenance**. Native `web_search`/`web_fetch` are
provider-executed, so pydantic-ai represents them as `NativeToolCallPart`/`NativeToolReturnPart`
message parts, not OTel tool-call spans (confirmed against installed `pydantic-evals` 2.32.0's
`_is_tool_call_span`, which only recognizes locally-executed tools — a real gap from the PRD's literal
"use `HasMatchingSpan` to assert it searched"). `agents/provenance.py::extract_trajectory()` walks the
run's own message history to reconstruct the closed set — every URL the provider actually returned
this run — and `ground_evidence()` drops any model-cited URL not in that set into `dropped_evidence`,
same "drop, don't trust" idiom as `_resolve_groups`/`_ground_candidates`.

**No one-to-one flag-to-source mapping (a hard design constraint, not a nice-to-have)**: the prompt
instructs hypothesis-first, multi-angle search and explicitly forbids cherry-picking a source that
confirms a pre-formed conclusion. This is enforced deterministically, not just by prompt: a resolved
(benign/concerning) verdict is downgraded to `unresolved` in code
(`_apply_multi_angle_rule`) unless the model's *cited, grounded* evidence spans ≥2 distinct
registrable domains — **critically keyed on `{registrable_domain(e.url) for e in evidence}`, never on
`trajectory.distinct_domains`** (every domain any raw search call *returned*, including irrelevant
noise — a single search typically returns 5-10 different domains regardless of investigation quality).
This exact bug was caught live during eval validation (a fictional-company case returned 32 raw noise
domains while citing 0-2 real sources) — see `.agents/plans/phase-3-investigator.md` Execution
Deviations. Confidence is calibrated the same way: <2 evidence domains caps it at 0.5, conflicting
evidence stances cap it at 0.7.

**Cost governance, three layers**: `WebSearch(max_uses=6)`/`WebFetch(max_uses=4)` (provider-enforced),
`UsageLimits(request_limit=12, cost_limit=Decimal("0.75"))` (client-enforced — this closes
`pydantic-ai-v2.md`'s former open question #1: a per-run USD cap needs no `pydantic-ai-harness`
dependency, it's in core `pydantic-ai`), and `max_investigations=5` at the stage level. A budget
overrun (`UsageLimitExceeded`) is caught and degrades to an `unresolved` verdict with a `CoverageGap`
explaining why — never propagated, since one over-budget flag must not crash the other investigations
running concurrently in the same `asyncio.gather`. Real observed cost: **$0.36–$1.14 per flag**
(4 live runs), averaging ~$0.45-0.60 — above the plan's original $0.30-0.55 estimate on the high end
for genuinely complex multi-source investigations. The `$0.75` cap is left as originally planned
rather than raised — PRD §10/§12 already assign spend-limit tuning to Phase 6, and this real
distribution is the input that phase should tune against.

**Live-verified (GOOGL, 2026-08-19)**: resolved the same multi-year `capex_to_depreciation_ratio`
escalation flag seen in Phase 2's live run (2.40x→4.33x, 2021-2025) as `benign`, confidence 0.70, 11
grounded evidence items across 6 queries, 0 dropped. The hypothesis correctly separated two distinct
causes rather than taking the ratio at face value: a disclosed AI/data-center capex program, and a
January 2023 accounting-estimate change (extended server useful life) that mechanically suppresses
the ratio's denominator independent of any change in real spending.

**Correlated-flag signal, not resolution**: `correlated_sibling_indices` lets the Investigator note a
suspected shared root cause with another flag from this run, by index only (never restating its
content — the closed-set-by-index idiom, same as the Flag Consolidator). *Weighing* correlated flags
as one story rather than stacking them as independent negatives is explicitly deferred to the Phase 5
Synthesizer/Red-Team — see the plan's Notes → "Carried forward to Phase 5".

## Sector Analyst, Macro Sensitivity Analyst, Valuation Interpreter (Phase 4)

**Modules**: `agents/sector.py`, `agents/macro.py`, `agents/valuation_interpreter.py`. **Model**:
`anthropic:claude-sonnet-5` for all three (PRD §4 roster tier), one constant per agent in
`agents/models.py`. **Capabilities**: none — pure narration, no tools, not agentic loops, same
profile as the Phase 1-2 analysts. Full design rationale in
`.agents/plans/phase-4-sector-macro-valuation.md`.

**What's structurally different from every prior agent**: none of the three produce `Flag`s. Their
`output_type` narrates a small, already-fully-typed, already-computed deterministic bundle (peer
multiples, macro series values, DCF scenario output) directly into free text — there is no
candidate-then-promotion step, because there is no closed table or verbatim quote to promote
against. Each agent's own `output_type` (`SectorAnalystAgentOutput` etc.) is narrower than the
stage's return type (`SectorAnalystOutput` etc.) for a different reason than Phases 1-2's split,
though: not to gate a promotion, but because the model was never trusted with metadata
(`ticker`/`coverage_gaps`) the stage function rebuilds from the real input regardless — asking the
model to produce it was pure surface area for a value that's always discarded.

**Grounding — the fourth mechanism in this codebase**, after closed-table lookup (Phase 1),
verbatim-quote checking (Phase 2), and URL provenance (Phase 3): `agents/numeric_grounding.py`.
Every number appearing in a `summary` must be traceable, within tolerance, to a real number in the
typed input, or a simple derived transform (percent difference or ratio) between two such numbers
— the natural vocabulary of a *comparative* narrative ("trades at a 22% discount to peer median
P/E"). Promoted from Phase 1's informational-only `_summary_numeric_grounding_ratio` prototype to
a real, hard runtime gate: each `run_X()` function calls `summary_is_grounded()` after the agent
call and, on failure, replaces the *whole* summary with a fixed fallback string plus a
`CoverageGap(reason="numeric_grounding_check_failed")` — never ships unverified prose. This is a
coarser failure mode than Phases 1-2's per-candidate drop (one bad number loses the whole
narrative, not just the offending claim), an accepted tradeoff given there's no candidate structure
to fall back to.

**The numeric-extraction regex required real live-model validation to get right** — six distinct
false-positive categories (Treasury-maturity labels like "10Y"/"10-year", comma-thousands
separators, ISO dates, bare-hyphen ranges like "3.99%-4.02%", asymmetric percent-difference signs,
and legitimate verbatim citations of non-quantity input fields like a SIC code) were each invisible
to hand-written unit tests and only surfaced once the eval datasets ran against a real model — see
the Phase 4 plan's Execution Deviations §3 for the full account and the fixes, all now permanent
regression tests in `test_numeric_grounding.py`.

**Sector Analyst** (`agents/sector.py`) narrates `SectorPeerData` — peer/segment positioning
relative to a deterministically-discovered peer set (see `data-layer.md`'s Phase 4 section for the
EDGAR SIC-based discovery pipeline). Explicitly *not* a general business-overview agent — memo §3
(Business Overview) still needs the Phase 5 Synthesizer to read `FilingSections.item_1_business`
directly; Sector Analyst's job is comparative multiples positioning only.

**Macro Sensitivity Analyst** (`agents/macro.py`) narrates a `MacroAnalystInput` (a typed wrapper —
`list[MacroSeriesBundle]` + `CompanyMacroProfile`, since every inter-stage boundary must be one
typed model, never two positional arguments). `CompanyMacroProfile` is deliberately small, built
from fields Phases 0-1 already fetch — no new data-layer fetching for this agent at all.

**Valuation Interpreter** (`agents/valuation_interpreter.py`) narrates a `ValuationResult` — a
trailing DCF (see `valuation.py`'s Phase 4 section) plus the *same* `PeerCompsResult` object Sector
Analyst consumes (peer discovery runs once, deterministically, and feeds both agents — never
duplicated). Its prompt explicitly requires the discount rate and terminal growth to be stated as
disclosed assumptions, never as fact, per the investment-memo-writing skill's Section 6
requirement — this is the one section of the memo the skill doc marks INCLUDED, not deferred, so
getting this framing right in the prompt (and verified by the eval's LLMJudge rubric) mattered more
here than in any prior agent.

**Live-verified (GOOGL, 2026-08-19)**: all three agents produced grounded narratives on the first
attempt in an end-to-end manual run — see the Phase 4 plan's Execution Deviations for the full
account, including a real peer-discovery bug (feed page size vs. returned-candidate cap conflated)
caught only by this live run, not by unit tests or the eval datasets' first pass.

## Synthesizer (draft + resolve), Red-Team, `pipeline.py` (Phase 5)

**Modules**: `agents/synthesizer_draft.py`, `agents/red_team.py`, `agents/synthesizer_resolve.py`,
`pipeline.py`. **Model**: `anthropic:claude-sonnet-5` for all three (PRD §10, revised this
session from an original Opus starting point given these calls' token-cost profile — a starting
tier, not a final decision; see PRD §10's note on what would justify a bump back to Opus).
**Capabilities**: none — reasoning-heavy but not agentic, same profile as every non-Investigator
agent in this codebase. All three needed an explicit `model_settings=ModelSettings(max_tokens=…)`
(8192 for draft/red-team, 10000 for resolve) — pydantic-ai's 4096 default silently truncated a
full 10-section memo's output before `sections` was ever emitted; see the Phase 5 plan's
Execution Deviations §1 for the exact failure and how it was found.

**Grounding — the fifth mechanism in this codebase**, after closed-table lookup (Phase 1),
verbatim-quote checking (Phase 2), URL provenance (Phase 3), and numeric-tolerance matching
(Phase 4). `agents/memo_grounding.py` extends Phase 4's `numeric_grounding.py` wholesale — no
new regex — adding only (a) a much larger known-numbers universe harvested from *every* upstream
typed field a `MemoSynthesisInput` carries, including raw filing prose (no earlier phase needed
to harvest numbers from free text this way), and (b) a **per-section** gate instead of Phase 4's
per-agent-output gate: one ungrounded section replaces only that section's content, never the
whole memo. Unlike Phase 4's agents, the model IS trusted with citation metadata here
(`MemoSectionAgentOutput.cited_figures`) — Section 10 (Appendix/Sourcing)'s "literal traceability
table" only exists if the model states what it's citing — so the gate checks two things per
section: every number in `content` grounds, AND every `cited_figures` value grounds
independently (closes the gap a content-only check would miss: a fabricated `SourcedFigure` with
an invented value and a plausible fake source string). `memo_grounding.py` keeps its own bounded
pairwise-expansion (`_expand_known_numbers`, capped to same-magnitude pairs) rather than reusing
`numeric_grounding.py::expand_known_numbers`'s unrestricted version — the latter's unrestricted
cross-product broke down over Phase 5's much larger, heterogeneous known-number sets (a real
revenue figure divided by an unrelated small ratio produced a spurious value that wrongly
grounded a fabricated citation); see the Phase 5 plan's Execution Deviations §2. This left Phase
4's own already-passing agents untouched.

**Synthesizer draft pass** (`agents/synthesizer_draft.py`) reads the full `MemoSynthesisInput`
(raw financials/filing text/macro/valuation plus the three Phase 4 agents' narrated summaries and
the Investigator's verdicts) and writes all 10 of PRD §3's sections, in the fixed order enforced
by the closed `MemoSectionTitle` Literal (`contracts/memo.py::MEMO_SECTION_ORDER`) — a missing
section gets a code-synthesized placeholder plus a `CoverageGap`, never a crash. Instructions are
drawn directly from `.claude/skills/investment-memo-writing/SKILL.md` §1, not reinvented.

**Red-Team** (`agents/red_team.py`) attacks the draft for exactly two failure modes (skill §4
Pass 2): `untraceable_claim` and `boilerplate` (including a real checklist-eligible red flag the
draft's Earnings Quality section omitted entirely). Grounding here is verbatim-quote verification
— reused directly from `agents/grounding.py::quote_is_grounded`, the same mechanism Phase 2's
Filings/Transcript Analysts use — an attack's `quoted_claim` must be a real substring of the
section it names, or it's dropped into `dropped_candidates`, never trusted.

**Synthesizer resolve pass** (`agents/synthesizer_resolve.py`) answers or downgrades every
attack and produces the `Memo` that ships — a full rewrite of all 10 sections (not a patch),
matching PRD §4's literal `MemoDraft + RedTeamAttack -> Memo` roster I/O. Directly targets PRD
§14's named risk ("sycophantic resolve-pass") with a structural check, not just a prompt
instruction: every attack index must have exactly one `AttackResolution` record
(`_fill_missing_resolutions` synthesizes a `model_addressed=False` fallback for any attack the
model didn't address, so the structural invariant always holds even when the model's own
resolution is incomplete), and the per-section grounding gate reapplies here too, since a
rewrite could reintroduce a fabricated number while "fixing" something else.

**Live eval findings**: the grounding gate's fallback fired on a real sample in both the draft
and resolve datasets — investigated directly (not assumed benign) and confirmed to be the safety
net catching a genuine one-off ungrounded claim, not a defect; see the Phase 5 plan's Execution
Deviations §3 for the full account, including a plausible root cause specific to
`appendix_and_sourcing` (a section whose job is describing the memo's own sourcing apparatus,
which can tempt a self-referential, structurally-ungroundable count).

**`pipeline.py::run_memo_pipeline(ticker)`** is the orchestrator PRD §4's diagram describes,
wiring every phase (0-5) into the fixed sequence: `fetch_all()` → the three Stage-2 analysts
(parallel) → exact-dedup + Flag Consolidator → Investigator × N (parallel) → peer discovery +
deterministic valuation math → Sector/Macro/Valuation Interpreter (parallel) → draft → red-team →
resolve. Closes a real, previously-deferred gap: `ratios.py::build_company_macro_profile()`
(new — latest annual revenue/total_debt, revenue CAGR, both independently None-guarded) replaces
the hardcoded `None` placeholders CLAUDE.md's own Phase 4 manual-run example carried. Raises a
new `ValuationAssumptionsUnavailable` if `build_valuation_assumptions()` returns `None` (a full
FRED DGS10 outage) — mirrors `data/peer_discovery.py::PeerDiscoveryError`'s precedent (a genuine
system problem, not a routine coverage gap) rather than threading a phantom
`ValuationAssumptions | None` through three more downstream contracts that don't support it
today; noted as a real, if rare, edge case surfaced only by wiring the full pipeline for the
first time, not by any Phase 0-4 unit test.

**Not live-verified end-to-end**: a real `run_memo_pipeline("GOOGL")` run was attempted three
times and consistently 429'd on `synthesizer_draft`'s own request — a real GOOGL 10-K's full
filing text (already measured at 65K-132K tokens for just the Filings Analyst's narrower slice)
plus the rest of `MemoSynthesisInput` plausibly approaches a meaningful fraction of this
account's 500K-input-tokens/minute cap on its own. Every other validation level (unit tests, all
three new eval datasets, lint/type-check) completed successfully against real API calls. See the
Phase 5 plan's Execution Deviations §5 — a real, unresolved operational constraint (account
rate-limit tier, or a filing-text truncation strategy), Phase 6-shaped, not a Phase 5 correctness
defect. `run_memo_pipeline()` and `render.py::render_memo_to_pdf()` are both implemented and
plumbing-tested; re-run Level 4 once this is resolved.

**Rendering** (`render.py`, added mid-plan at the user's request — not part of PRD §3's literal
"Final Artifact Specification", which is the typed `Memo` object): `render_memo_to_markdown()` /
`render_memo_to_pdf()` are pure deterministic formatting, deliberately never called from
`pipeline.py` or any agent module, so a PDF-layout bug can never affect whether `Memo` itself is
correct or grounded. Uses `markdown` + `xhtml2pdf` (pure-Python, no Cairo/Pango system
dependency, unlike `weasyprint`). The Appendix section's sourcing table is mechanically
regenerated from every section's real `cited_figures`/`cited_quotes` — Section 10's "literal
traceability table" made real from typed data, not trusted from the model's own prose alone.
