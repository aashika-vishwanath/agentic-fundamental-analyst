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

## Not yet built (Phase 3+)

Investigator, Sector Analyst, Macro Sensitivity Analyst, Valuation Interpreter, Synthesizer (draft +
resolve), Red-Team — see PRD §4 roster and §12 phase plan.
