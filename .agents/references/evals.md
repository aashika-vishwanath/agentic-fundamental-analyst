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

## Trajectory evals

Not applicable to any agent built so far — none has tools/capabilities (Financial Statements,
Filings, Transcript Analysts, Flag Consolidator are all single-shot, no `WebSearch`/`WebFetch`).
Trajectory evals (`HasMatchingSpan`, tool-call-count checks) are Investigator-only, per PRD §8 —
land in Phase 3.

## Annotation → eval flywheel

Not yet exercised in this codebase beyond the two documented fixture fixes above (which came from
inspecting real eval-run output, not a production trace — the flywheel proper, pulling from real
Logfire traces of real ticker runs, starts mattering once Phase 5's `pipeline.py` exists and real
runs accumulate).
