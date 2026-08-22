# Evals — Implementation Reference

For the eval strategy's design intent, see `PRD.md` §8. This file covers what's actually built.

## Layout

One `Dataset` per agent in `evals/`: `financial_statements.py` (Phase 1), `filings.py`, `transcripts.py`,
`flag_consolidator.py` (Phase 2). `evals/grounding.py` holds a shared `flags_are_quote_grounded()`
helper used by the two prose-grounded datasets — the actual substring check is shared (via
`agents/grounding.py::quote_is_grounded`), but each dataset keeps its own concrete `Evaluator`
subclass, because "how do I find the source text a given flag should be grounded against" genuinely
differs per agent (Filings routes by section + 8-K item number; Transcript has exactly one source
text; Flag Consolidator isn't quote-grounded at all — see below).

Run any dataset with `ANTHROPIC_API_KEY=<key> uv run python -m evals.<name>` — real API spend, not a
CI gate (per CLAUDE.md Testing Strategy).

## Naming convention

Cases are named for the scenario they cover (`auditor_change_flagged`, `transcript_unavailable_gap`),
never the mechanism. Every dataset includes at least one clean/negative case (`*_no_flags`) — the
over-flagging guard.

## Evaluator preference order, applied at every dataset

1. **Deterministic** — a hard gate, 100% required, no exceptions:
   - `FinancialStatementsGroundingEvaluator` (Phase 1): every `Flag.source.value` traces exactly to
     the recomputed `RatioTrendBundle`.
   - `FilingsGroundingEvaluator` / `TranscriptGroundingEvaluator` (Phase 2): every `Flag.source` is a
     `SourcedQuote` whose `.text` verifies as a real (whitespace-normalized) substring of the exact
     source text the flag claims — independently re-derived from `flag.source.source`'s own citation
     string, not just trusting the agent module's grounding function was applied correctly.
   - `FlagConsolidatorGroundingEvaluator` (Phase 2): the multiset of all `Flag`s across every output
     `ConsolidatedFlag` equals exactly `deduplicate_exact_flags(case.inputs)` — no flag lost, none
     duplicated, none fabricated. Checked by Python object identity (`id()`), since `Flag` isn't
     hashable and consolidation must literally reuse the same input objects, never reconstruct them.
2. **Recall** — `ExpectedFlagsPresent`-style: a metadata-declared set of expected flag metrics must be
   a subset of the actual flags raised (or, for the clean case, actual must be empty). The Flag
   Consolidator's analog is `ExpectedGroupingPresent`: a metadata-declared pair of flag objects must
   land in the same `ConsolidatedFlag`.
3. **`LLMJudge`, sparingly** — summary-quality only, pinned to the agent's own `model=` (a real,
   fixed Phase 1 bug: `LLMJudge` defaults to an OpenAI model and crashes key-free otherwise).
   **Skipped entirely for the Flag Consolidator** — grouping correctness is fully checkable
   deterministically and by recall, so a judge would violate the "reach for a judge only when no
   deterministic/recall check can substitute" rule.

## Live-verified scores (Phase 2, real model, 2026-08-19)

| Dataset | Grounding (hard gate) | Recall | LLMJudge |
|---|---|---|---|
| `financial_statements` | 6/6 | 6/6 | 6/6 |
| `filings` | 6/6 | 6/6 | 6/6 |
| `transcripts` | 3/3 | 3/3 | 2/3 |
| `flag_consolidator` | 3/3 | 3/3 | N/A (no judge) |

**`transcripts`'s one `LLMJudge` miss** (`clean_transcript_no_flags`): inspected directly — the
generated summary cites real, specific figures from the transcript (140bps margin improvement to
42.3%, 8-10% guidance) and is not actually generic. This reads as single-sample `LLMJudge` noise on a
genuinely well-grounded summary, not a real defect — and this plan's original "at least 3/3" bar for
a 3-case dataset left no room for that kind of noise, unlike Phase 1's "5/6 of 6" allowance. Not
re-tuned or re-rolled to force a different sample, per CLAUDE.md's "never quietly patch an eval
result" — flagged here and in the Phase 2 plan's Execution Deviations instead. If this recurs on
future runs, it's worth widening the dataset (more cases) rather than loosening the rubric.

**`filings`'s first draft failed 2/6 on `LLMJudge`** before a fixture fix (not a rubric change): the
dataset's default `_sections()` placeholder text (business description, risk factors, MD&A) was
initially too generic/boilerplate for the model to write a genuinely specific summary about —
rewritten with a concrete fictional company (Meridian Audio Corporation), named product lines, and
real-looking numbers. Also fixed the `officer_turnover_flagged` case, which originally included the
standard "not the result of any disagreement" 8-K boilerplate without any other signal of an
*unexpected* departure — the model reasonably read that as routine and didn't flag it. Rewrote to
make the departure genuinely abrupt (effective immediately, no successor, tied to a guidance miss).
Reran clean: 6/6 across all three evaluators. This mirrors Phase 1's own precedent (iterating on the
Beneish M-Score fixture until it crossed its intended threshold) — fixing what a fixture's content
actually says, not loosening what the eval checks for.

## `investigator` (Phase 3, real model + real web search, 2026-08-19)

4 cases: both PRD §11 canonical capex cases (`capex_spike_ai_buildout_benign` = real GOOGL AI-buildout
narrative, `capex_spike_declining_core_concerning` = real Intel foundry-buildout-vs-declining-core-CPU
narrative — real, well-documented companies chosen deliberately so live web search has something real
to find, unlike a fictional company), plus `obscure_microcap_thin_evidence_unresolved` (deliberately
fictional company — the over-reach guard) and `routine_disclosure_benign` (Costco warehouse-capex
story — the clean/negative guard). 6 evaluators: `EvidenceProvenanceEvaluator`,
`MultiAngleInvestigation`, `ConfidenceCalibration` (all deterministic hard gates), `ExpectedVerdict`
(recall), `LLMJudge` (reasoning-weighs-both-sides rubric), `HasMatchingSpan` (stage span exists).

**Scores across live runs**: all 3 deterministic hard gates 100% on every case, every run. The two
canonical PRD cases each independently resolved correctly (`benign`/`concerning`) at least once, with
one run's `capex_spike_declining_core_concerning` hitting its `$0.75` cost cap on a genuinely complex
multi-source investigation and correctly degrading to `unresolved` + `CoverageGap` rather than
crashing — re-run in isolation, it resolved correctly (`concerning`, 0.62 confidence, $0.573).
`LLMJudge` and `HasMatchingSpan` passed on every case that reached a resolved/thin-evidence verdict.
Real cost: **$0.36-$1.14/case**. Full detail, including two real bugs caught only by running this
live (not by any unit test written up front): `.agents/plans/phase-3-investigator.md` Execution
Deviations.

## Trajectory evals

**Investigator-only** (PRD §8), and the one place this codebase's evaluator strategy deviates from
the PRD's literal spec. `pydantic-evals` 2.32.0 ships `ToolCorrectness`/`MaxToolCalls`/
`TrajectoryMatch`/`HasMatchingSpan`-on-tool-name — but all of them match only **locally-executed**
tool spans (`_is_tool_call_span` in `pydantic_evals/evaluators/agentic.py` requires a
`gen_ai.tool.name`-bearing span named `running tool`/`execute_tool …`). Anthropic's native
`web_search`/`web_fetch` are **provider-executed**: pydantic-ai represents them as
`NativeToolCallPart`/`NativeToolReturnPart` **message parts**, not spans — confirmed against the
installed source, not just docs. So PRD §8's literal "use `HasMatchingSpan` to assert it searched" is
not implementable as written. `evals/investigator.py`'s `MultiAngleInvestigation` is the trajectory
eval that actually matters here: it reads the typed `InvestigationVerdict.trajectory` field (built by
`agents/provenance.py::extract_trajectory()` from the run's own message history) and asserts on
search-query count and cited-evidence domain diversity directly, rather than on spans.
`HasMatchingSpan` is still used, narrowed to what it *can* see: that the `investigator_stage` span
exists.

## `synthesizer_draft`, `red_team`, `synthesizer_resolve` (Phase 5, real model, 2026-08-19)

Three datasets, `evals/synthesizer_draft.py` (3 cases), `evals/red_team.py` (4 cases),
`evals/synthesizer_resolve.py` (4 cases), all against one fictional company (Meridian Robotics
Inc. / MRBT) built with real, checkable numbers — same "concrete fictional company, not generic
placeholder text" precedent `evals.md` already documents for Phase 2's `filings` dataset.

**Evaluator preference order, same as every prior dataset**: `MemoGroundingEvaluator` (deterministic
hard gate — `is_grounded` independently re-derived from the delivered output via
`agents/memo_grounding.py`'s own functions, not trusted from the module under test;
`fallback_triggered` a soft quality *signal*, not a pass/fail bar) and `AllTenSectionsPresentInOrder`
(deterministic) on both memo-producing datasets; `AttackQuoteGroundedEvaluator` (deterministic,
`red_team`) and `AllAttacksAddressedEvaluator` (deterministic, `synthesizer_resolve`); recall checks
(`ExpectedCoverageGapPropagated`, `ExpectedAttackCategoryRaised`/`FewAttacksOnCleanDraft`,
`ExpectedResolutionPath`); `LLMJudge` last, pinned to each agent's own model, rubrics quoted
directly from `investment-memo-writing` skill §1/§4 rather than reinvented.

**Live-verified scores**: `synthesizer_draft` — `is_grounded` 100%/3, `AllTenSectionsPresentInOrder`
100%/3, `ExpectedCoverageGapPropagated` 100%/3, `LLMJudge` 3/3; `fallback_triggered` fired once
(1/3 cases) — investigated and confirmed to be the grounding gate correctly self-healing a
one-off ungrounded claim on a real sample, not a defect (re-running the same section in
isolation reproduced fully-grounded content). `red_team` — all 4 deterministic/recall evaluators
100%/4, `LLMJudge` 4/4. `synthesizer_resolve` — `AllAttacksAddressedEvaluator` 100%/4,
`is_grounded` 100%/4, `AllTenSectionsPresentInOrder` 100%/4, `ExpectedResolutionPath` 4/4,
`LLMJudge` 4/4; `fallback_triggered` fired on 2/4 cases, same self-healing pattern, both times on
`appendix_and_sourcing` specifically (plausible cause: this section describes the memo's own
sourcing apparatus, tempting a self-referential citation count that by definition can't ground
against upstream data). Full account, including the mid-run bugs these live runs caught (an
undersized default `max_tokens` that silently truncated output entirely below the schema's
`sections` field, and `expand_known_numbers`'s unrestricted pairwise expansion breaking down at
Phase 5's larger known-number-set scale): `.agents/plans/phase-5-synthesis-redteam-pipeline.md`
Execution Deviations §1-3.

**A real fixture bug, not a rubric change**: `evals/red_team.py`'s `clean_draft_few_or_no_attacks`
negative case wasn't actually clean — its executive-summary content claimed a "$120 million
capacity" figure that had been dropped from that file's own (shorter) `item_7_mdna` fixture text
when it was written, even though the same fact was present in the other two Phase 5 eval files'
richer fixtures. The model correctly attacked it as untraceable. Fixed by adding the fact back to
the fixture's filing text, mirroring the exact "fix what the fixture's content actually says, not
what the eval checks for" precedent already documented above for Phase 2's `filings` dataset.
Full account: the Phase 5 plan's Execution Deviations §4.

## Annotation → eval flywheel

First real instance beyond fixture fixes: this phase's own live eval runs surfaced two genuine
implementation bugs (Execution Deviations §1-2 above) and one fixture bug (§4) purely from
running the datasets, not from a production trace — `pipeline.py` now exists, but the Level 4
manual GOOGL run that would start the trace-based flywheel proper hasn't completed yet (see
`observability.md`'s Phase 5 section) — it hit a real, unresolved rate-limit wall three times in
a row rather than a code defect.
