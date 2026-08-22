# Feature: Phase 5 — Synthesizer (draft + resolve), Red-Team, `pipeline.py`

Validate documentation, existing contracts, and codebase patterns before implementing.
Pay special attention to existing model/enum names — import, don't redefine.

## Feature Description

The final phase before the system has a working end-to-end product: three new agents
(Synthesizer draft pass, Red-Team, Synthesizer resolve pass) and one new deterministic
orchestrator (`pipeline.py::run_memo_pipeline(ticker)`) that wires every phase built so far
(0-4) into one call producing a `Memo`. This closes PRD §12's Phase 5 row and is the last
piece before Phase 6 hardening.

Per PRD §4's pipeline diagram, the three-pass shape is: **draft synthesizer** reads every
upstream typed output and writes a full 10-section `MemoDraft`; **red-team** attacks it for
untraceable claims and boilerplate; **resolving synthesizer** answers or downgrades every
attack and produces the `Memo` that ships. `pipeline.py` is what actually calls
`fetch_all()` and every prior phase's agents in the fixed sequence PRD §4 diagrams, with
`asyncio.gather` inside each parallel block — no new judgment, no orchestrator agent, just
wiring.

## User Story

As the builder, running this system as a personal research tool, I want
`run_memo_pipeline(ticker)` to produce one grounded, typed `Memo` for a real ticker, so that
I have the actual end-to-end product the four prior phases were built toward, not eight
disconnected agent calls I have to wire by hand every time.

## Problem / Solution Statement

**Problem**: Phases 1-4 built eight agents and a rich deterministic data layer, but nothing
turns their outputs into the one artifact PRD §3 actually promises — a `Memo` with a
rating, a conviction tier, and ten sourced sections. Two things stand between "eight agent
outputs" and "one memo": (1) synthesizing heterogeneous typed data (raw financials, filing
prose, macro series, DCF/comps, flags, investigation verdicts) into free-text sections
without losing the traceability every prior phase enforced, and (2) PRD §14's stated risk —
"sycophantic resolve-pass (caves to red-team without real re-grounding)" — needs a real
adversarial check, not just one drafting pass trusted at face value.

**Solution, and what was rejected**:

1. **Grounding mechanism — extend, don't reinvent.** Phase 4's numeric-tolerance grounding
   (`agents/numeric_grounding.py`) is reused wholesale, not reimplemented: this phase adds one
   new module, `agents/memo_grounding.py`, whose only new logic is (a) building a much larger
   "known numbers" universe from *every* upstream typed field the Synthesizer sees (financials,
   filing prose, macro series, valuation, flags, investigations), and (b) a **per-section**
   grounding gate instead of Phase 4's per-agent-output gate. Rejected: inventing a fifth
   grounding mechanism from scratch — there's no new *kind* of claim here (still numeric
   claims in free text), just a bigger known-numbers universe and a finer-grained fallback unit.
   Per-section (not whole-memo) fallback is a deliberate improvement over Phase 4's coarser
   precedent: losing one of ten sections to a bad number is a much smaller blast radius than
   losing an entire memo, and sections give a natural boundary Phase 4's flat summaries didn't
   have.
2. **The model must self-report citations, not just be checked against ambient data.** PRD §3's
   `MemoSection.cited_figures: list[SourcedFigure]` is taken literally (not narrowed away the
   way Phase 4 narrowed `SectorAnalystAgentOutput` to drop model-owned metadata) because Section
   10 (Appendix/Sourcing) requires "a literal traceability table" — that only exists if the
   model actually states what it's citing. The hard gate then checks **both** that every number
   in `content` grounds against the known-numbers universe **and** that every `cited_figures`
   value does too — closing the gap a citation-blind check would miss (a fabricated
   `SourcedFigure` with an invented value and a plausible-looking fake source string).
3. **Attack addressing is a closed, index-based set**, mirroring the Flag Consolidator's and
   Investigator's `correlated_sibling_indices` idiom exactly: red-team attacks are numbered
   0..N-1 against the draft it attacked, and the resolve pass's `AttackResolution.attack_index`
   is checked structurally — every index must have exactly one resolution record — rather than
   trusting the model said it addressed everything. Rejected: freeform prose "here's how I
   addressed your attacks" with no structural check, which is exactly the sycophancy failure
   mode PRD §14 flags — a model could claim to have addressed an attack while quietly leaving
   the original unsourced claim in place, and prose alone can't catch that.
4. **Full-rewrite resolve pass, not a patch/diff pass.** The resolve pass regenerates all ten
   sections from scratch (given the draft + attacks + full synthesis context), not a
   section-by-section patch. Matches the PRD roster's literal I/O (`MemoDraft + RedTeamAttack ->
   Memo`) and avoids diffing complexity; the cost tradeoff (three large calls stacking similar
   context) is discussed in Strategic Thinking / Notes below, and is exactly why this phase's
   model tier is Sonnet, not Opus (PRD §10, updated this session).
5. **`CompanyMacroProfile` construction was a real, previously-deferred gap.** CLAUDE.md's own
   Phase 4 manual-run example hardcodes `latest_revenue=None, latest_total_debt=None,
   revenue_cagr=None` with a `# fill from FinancialStatementBundle in a real run` comment — this
   was never built. `pipeline.py` cannot ship with that placeholder (it would report every real
   ticker as having no revenue/debt data, itself a fabricated coverage gap), so this phase adds
   `ratios.py::build_company_macro_profile()`, deterministic code, alongside the module's
   existing `compute_trend_bundle()`.

## Feature Metadata

**Type**: New Capability (end-to-end wiring) **Complexity**: High **Pipeline stage(s)**:
Stage 5 (Synthesizer draft), Stage 6 (Red-Team), Stage 7 (Synthesizer resolve), plus the
orchestrator itself (`pipeline.py`) wiring Stages 1-7 together for the first time.
**Dependencies**: Phases 0-4 complete (confirmed: 157 unit tests passing, all eight prior
agents live-verified).

## Agent-or-Code Decisions

| Component | Agent or Code | Why |
|---|---|---|
| Synthesizer draft pass | Agent | Interpreting/synthesizing heterogeneous typed data into prose is judgment, not computation |
| Red-Team | Agent | "Is this boilerplate / does this claim hold up" is a judgment call, not a deterministic check |
| Synthesizer resolve pass | Agent | Deciding *how* to resolve an attack (re-ground/downgrade/cut) is judgment |
| Per-section numeric grounding gate (`agents/memo_grounding.py`) | Code | Checkable by exact tolerance-matching against typed input — no judgment call, same reasoning as Phase 4's `numeric_grounding.py` |
| Attack quote-verification (`quoted_claim` against draft section text) | Code | Exact substring check — reuses `agents/grounding.py::quote_is_grounded` verbatim, same reasoning as Phase 2 |
| Attack-resolution structural completeness check | Code | "Does every attack index have exactly one resolution" is closed-set membership, not judgment |
| `build_company_macro_profile()` (revenue/debt/CAGR from `FinancialStatementBundle`) | Code | Pure arithmetic over typed fields — same category as every other `ratios.py` function |
| `run_memo_pipeline(ticker)` | Code | The orchestrator itself — CLAUDE.md hard constraint: "the pipeline is fixed... no orchestrator/router agent" |
| Coverage-gap aggregation across all stages | Code | Set/list union of typed `CoverageGap`s — no judgment |
| Memo → Markdown → PDF rendering | Code | Pure formatting/serialization of an already-finalized `Memo`'s typed fields — no interpretation, nothing left to decide once `Memo` exists. Added mid-plan at the user's explicit request (scope was originally "Memo object only, no rendering" — see Notes) |

## Data Contracts

### `contracts/memo.py` — new file

```python
from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel

from agentic_fundamental_analyst.contracts.financials import CoverageGap
from agentic_fundamental_analyst.contracts.investigation import InvestigationVerdict
from agentic_fundamental_analyst.contracts.sourcing import SourcedFigure, SourcedQuote


class Rating(str, Enum):
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"


class ConvictionTier(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# PRD §3's ten sections, in the fixed order §3's table specifies. Closed Literal
# (not `title: str` as PRD's illustrative sketch has it) so every downstream stage
# (grounding gate, red-team's `section` field, structural "all ten present, in
# order" check) can address a section by a stable key instead of free text —
# same "closed-set idiom" as FilingSection/FinancialFlagMetric elsewhere in this
# codebase. Deviation from the PRD sketch, same category as Phase 1's SourcedFigure
# source-string coarsening — noted here, not silently done.
MemoSectionTitle = Literal[
    "executive_summary_and_recommendation",
    "investment_thesis",
    "business_overview",
    "financial_analysis",
    "earnings_quality_and_red_flags",
    "valuation",
    "catalysts",
    "risks_and_mitigants",
    "recommendation_and_sizing",
    "appendix_and_sourcing",
]

MEMO_SECTION_ORDER: tuple[MemoSectionTitle, ...] = (
    "executive_summary_and_recommendation",
    "investment_thesis",
    "business_overview",
    "financial_analysis",
    "earnings_quality_and_red_flags",
    "valuation",
    "catalysts",
    "risks_and_mitigants",
    "recommendation_and_sizing",
    "appendix_and_sourcing",
)


class MemoSectionAgentOutput(BaseModel):
    """Shared by the draft and resolve passes' own output_type — see
    SectorAnalystAgentOutput's docstring precedent for why an agent's own
    output_type is sometimes narrower, but here it's the OPPOSITE: `cited_figures`
    IS asked of the model (see plan's Problem/Solution #2), because Section 10's
    traceability table requires the model to state what it's citing."""

    title: MemoSectionTitle
    content: str
    cited_figures: list[SourcedFigure]
    cited_quotes: list[SourcedQuote] = []


class MemoSection(BaseModel):
    """Post-grounding-gate — identical shape to MemoSectionAgentOutput; kept as a
    separate type (not a type alias) for the same reason FinancialAnalystOutput is
    separate from FinancialAnalystAgentOutput: this is what a pipeline stage
    actually returns, the other is what the model returns before code-owned
    handling (here: the per-section grounding fallback)."""

    title: MemoSectionTitle
    content: str
    cited_figures: list[SourcedFigure]
    cited_quotes: list[SourcedQuote] = []


class SynthesizerDraftAgentOutput(BaseModel):
    rating: Rating
    conviction: ConvictionTier
    sections: list[MemoSectionAgentOutput]


class MemoDraft(BaseModel):
    ticker: str
    rating: Rating
    conviction: ConvictionTier
    sections: list[MemoSection]
    coverage_gaps: list[CoverageGap]


class AttackCategory(str, Enum):
    UNTRACEABLE_CLAIM = "untraceable_claim"
    BOILERPLATE = "boilerplate"


class AttackCandidate(BaseModel):
    """Agent-authored, unverified — quoted_claim is NOT trusted until
    _resolve_attacks() verifies it's a real substring of the section it names,
    same 'candidate' idiom as FlagCandidate/EvidenceCandidate."""

    section: MemoSectionTitle
    category: AttackCategory
    quoted_claim: str
    critique: str
    checklist_item: str | None = (
        None  # memo-writing skill §2 item name, when category == boilerplate and a specific checklist item was skipped
    )


class RedTeamAgentOutput(BaseModel):
    attack_candidates: list[AttackCandidate]


class Attack(BaseModel):
    """Post quote-verification — quoted_claim is confirmed to be a real
    (whitespace-normalized) substring of the named section's content."""

    section: MemoSectionTitle
    category: AttackCategory
    quoted_claim: str
    critique: str
    checklist_item: str | None = None


class RedTeamAttack(BaseModel):
    attacks: list[Attack]
    dropped_candidates: list[
        str
    ]  # diagnostic only, same as *_analyst's dropped_candidates — never delivered in the memo


class ResolutionPath(str, Enum):
    RE_GROUNDED = "re_grounded"
    DOWNGRADED = "downgraded"
    CUT = "cut"


class AttackResolution(BaseModel):
    attack_index: int  # 0-based position into RedTeamAttack.attacks — closed-set-by-index idiom, same as Flag Consolidator / Investigator siblings
    resolution: ResolutionPath
    explanation: str
    model_addressed: bool = True  # False only for a code-synthesized fallback (see run_synthesizer_resolve) — distinguishes a real model resolution from the structural safety net


class SynthesizerResolveAgentOutput(BaseModel):
    resolutions: list[AttackResolution]
    rating: Rating
    conviction: ConvictionTier
    sections: list[MemoSectionAgentOutput]


class Memo(BaseModel):
    ticker: str
    rating: Rating
    conviction: ConvictionTier
    generated_at: datetime
    sections: list[MemoSection]
    coverage_gaps: list[
        CoverageGap
    ]  # list[CoverageGap], not PRD §3's illustrative list[str] — consistency with every other coverage_gaps field in this codebase; same "sketch is illustrative, not exhaustive" precedent as Phase 1's SourcedFigure deviation
    investigations: list[InvestigationVerdict]
    resolutions: list[
        AttackResolution
    ]  # added beyond PRD's sketch — the structural record PRD §14 requires ("checked structurally, not just accepted")
```

### `contracts/synthesis.py` — new file (the typed inter-stage boundaries; kept
separate from `memo.py` since these are plumbing wrappers, not the memo's own shape)

```python
from datetime import date

from pydantic import BaseModel

from agentic_fundamental_analyst.contracts.consolidation import ConsolidatedFlag
from agentic_fundamental_analyst.contracts.filings import FilingSections
from agentic_fundamental_analyst.contracts.financials import CoverageGap, FinancialStatementBundle
from agentic_fundamental_analyst.contracts.intake import TickerIntakeResult
from agentic_fundamental_analyst.contracts.investigation import InvestigationVerdict
from agentic_fundamental_analyst.contracts.macro import MacroSeriesBundle
from agentic_fundamental_analyst.contracts.memo import MemoDraft, RedTeamAttack
from agentic_fundamental_analyst.contracts.ratios import RatioTrendBundle
from agentic_fundamental_analyst.contracts.valuation import ValuationResult


class MemoSynthesisInput(BaseModel):
    """The one typed bundle both the draft pass and (wrapped further below) the
    red-team/resolve passes consume. Field order matters: stable, long-lived
    content first (filing text, financials) per CLAUDE.md's prompt-caching
    convention — narrated/derived content (flags, investigations, the three
    Phase 4 summaries) last. Deliberately carries SUMMARY STRINGS (not the full
    FinancialAnalystOutput/FilingsAnalystOutput/TranscriptAnalystOutput objects)
    for the three Stage-2 analysts, to avoid duplicating their `flags` — the
    canonical post-consolidation flag list is `consolidated_flags` below, and
    giving the model two overlapping pre/post-consolidation flag lists would be
    confusing, not just wasteful."""

    ticker: str
    intake: TickerIntakeResult
    filings: FilingSections
    ratio_trend: RatioTrendBundle
    financials: FinancialStatementBundle
    latest_price: float
    latest_price_date: date
    macro_bundles: list[MacroSeriesBundle]
    valuation_result: ValuationResult
    financial_analyst_summary: str
    filings_analyst_summary: str
    transcript_analyst_summary: str | None
    sector_summary: str
    macro_summary: str
    valuation_summary: str
    consolidated_flags: list[ConsolidatedFlag]
    investigations: list[InvestigationVerdict]
    coverage_gaps: list[
        CoverageGap
    ]  # pre-aggregated union of every upstream stage's gaps (code-built, never re-derived by the model)


class RedTeamInput(BaseModel):
    draft: MemoDraft
    synthesis_input: MemoSynthesisInput  # red-team independently re-checks checklist coverage against the same real data the draft saw — memo-writing skill §4 Pass 2


class SynthesizerResolveInput(BaseModel):
    draft: MemoDraft
    red_team: RedTeamAttack
    synthesis_input: MemoSynthesisInput
```

---

## CONTEXT REFERENCES

### Codebase files to READ before implementing

- `src/agentic_fundamental_analyst/agents/valuation_interpreter.py` — Why: the closest
  analog for a per-run numeric-grounding gate with a fallback; Phase 5 generalizes this to
  per-section instead of whole-output.
- `src/agentic_fundamental_analyst/agents/numeric_grounding.py` (all of it) — Why: reused
  wholesale (`extract_numbers`, `expand_known_numbers`, `is_grounded`, `summary_is_grounded`);
  read the six false-positive-fix comments before touching regex behavior — do not
  re-introduce a fixed bug.
- `src/agentic_fundamental_analyst/agents/grounding.py` — Why: `quote_is_grounded()` is
  reused verbatim for `Attack.quoted_claim` verification.
- `src/agentic_fundamental_analyst/agents/flag_consolidator.py` (lines 58-93,
  `_resolve_groups`) — Why: the closed-set-by-index idiom (`FlagGroupCandidate.flag_indices`
  → validated → `ConsolidatedFlag`) is the direct pattern for both `_resolve_attacks()`
  (red-team) and `_fill_missing_resolutions()` (resolve pass).
- `src/agentic_fundamental_analyst/agents/investigator.py` (all of it) — Why: closest analog
  for "deterministic enforcement of a rule the prompt also states" (`_apply_multi_angle_rule`)
  and for a stage function that must degrade gracefully under a budget/error condition
  (`_budget_exceeded_verdict`) — Phase 5's `_fill_missing_resolutions` is this same idiom.
- `src/agentic_fundamental_analyst/agents/financial_statements.py` — Why: the
  candidate/promotion split pattern (`FlagCandidate` → `_ground_candidates` → `Flag`), directly
  analogous to `AttackCandidate` → `_resolve_attacks` → `Attack`.
- `src/agentic_fundamental_analyst/data/fetch.py` — Why: `fetch_all()`'s exact return shape
  and the `TickerOutOfScope` short-circuit pattern `pipeline.py` must preserve.
- `src/agentic_fundamental_analyst/ratios.py` — Why: `compute_trend_bundle()`'s pattern is
  what `build_company_macro_profile()` should mirror (pure function over
  `FinancialStatementBundle`, no I/O).
- `src/agentic_fundamental_analyst/valuation.py` — Why: `build_valuation_assumptions()`,
  `trailing_free_cash_flows()`, `dcf()`, `peer_multiples()` — `pipeline.py` calls all four,
  exactly as CLAUDE.md's Phase 4 manual-run command already demonstrates.
- `src/agentic_fundamental_analyst/data/peer_discovery.py` — Why: `discover_sector_peers()`'s
  signature — `pipeline.py` calls it once, feeding both Sector Analyst and Valuation
  Interpreter (Phase 4's own established convention — never duplicated).
- `.claude/skills/investment-memo-writing/SKILL.md` (already read this session, re-read when
  writing the three agents' `_INSTRUCTIONS`) — Why: this is the literal source of truth for
  section structure, the 17-item checklist, and good-vs-boilerplate criteria; every
  `_INSTRUCTIONS` string in this phase should draw from it directly, not be reinvented.
- `evals/valuation_interpreter.py` and `evals/flag_consolidator.py` — Why: the two closest
  eval-dataset templates (numeric-tolerance grounding eval; closed-set-index structural eval)
  for this phase's three new datasets.
- `.agents/references/agents.md`, `evals.md`, `observability.md` — Why: each ends with a
  section this phase must fill in (`## Not yet built (Phase 5+)`, the trace-wide `ticker`
  baggage TODO, the annotation flywheel note) — update these, don't just append.

### New files to create

- `src/agentic_fundamental_analyst/contracts/memo.py` — Rating, ConvictionTier,
  MemoSectionTitle, MemoSection(+AgentOutput), MemoDraft, Attack(+Candidate),
  RedTeamAttack(+AgentOutput), AttackResolution, SynthesizerResolveAgentOutput, Memo.
- `src/agentic_fundamental_analyst/contracts/synthesis.py` — MemoSynthesisInput,
  RedTeamInput, SynthesizerResolveInput.
- `src/agentic_fundamental_analyst/agents/memo_grounding.py` — the per-section numeric
  grounding gate; `known_numbers_from_synthesis_input()`, `section_is_grounded()`,
  `apply_grounding_gate()`.
- `src/agentic_fundamental_analyst/agents/synthesizer_draft.py` — `synthesizer_draft` Agent,
  `run_synthesizer_draft(input: MemoSynthesisInput) -> MemoDraft`.
- `src/agentic_fundamental_analyst/agents/red_team.py` — `red_team` Agent,
  `run_red_team(input: RedTeamInput) -> RedTeamAttack`.
- `src/agentic_fundamental_analyst/agents/synthesizer_resolve.py` — `synthesizer_resolve`
  Agent, `run_synthesizer_resolve(input: SynthesizerResolveInput) -> Memo`.
- `src/agentic_fundamental_analyst/pipeline.py` — `run_memo_pipeline(ticker: str) -> Memo`.
- `src/agentic_fundamental_analyst/render.py` — `render_memo_to_markdown(memo: Memo) -> str`,
  `render_memo_to_pdf(memo: Memo, output_path: str | Path) -> None`. Deliberately NOT called
  from inside `run_memo_pipeline()` or any agent module — rendering is a separate, optional
  downstream concern (file I/O) from memo *generation*, and keeping them apart means the
  pipeline's own unit/eval tests never touch a filesystem or a PDF dependency.
- `tests/unit/test_memo_grounding.py`, `tests/unit/test_synthesizer_draft_agent.py`,
  `tests/unit/test_red_team_agent.py`, `tests/unit/test_synthesizer_resolve_agent.py`,
  `tests/unit/test_pipeline.py`, `tests/unit/test_render.py` (TestModel-scripted / pure
  formatting, no network).
- `evals/synthesizer_draft.py`, `evals/red_team.py`, `evals/synthesizer_resolve.py`.
- `evals/memo_pipeline_e2e.py` — optional, expensive, Level 5 only (see Testing Strategy).

### Documentation to READ before implementing

- Installed Pydantic AI skill (consult first, per plan-feature process) — confirm
  `output_type` handles a `list[MemoSectionAgentOutput]`-shaped nested model the same way
  `list[FlagCandidate]` already works in this codebase (it should — no new capability needed,
  just a bigger schema) and confirm there is no per-request context-length ceiling this
  phase's large `MemoSynthesisInput` payload could hit for Sonnet.
- Installed Logfire/pydantic-ai skill or `logfire` source — confirm the exact API for a
  trace-wide baggage attribute (PRD §9: "ticker attached as a baggage attribute so every span
  in the trace is filterable by it") before writing `pipeline.py`'s outer span —
  `observability.md` flags this as still-undone; do not guess the call syntax, verify it
  against source/docs the way `agents/models.py`'s own comment insists on doing for model IDs.

### Patterns to follow

**Candidate → verified-type resolution** (mirrors `financial_statements.py::_ground_candidates`,
applied to red-team attacks):

```python
def _resolve_attacks(
    draft: MemoDraft, candidates: list[AttackCandidate]
) -> tuple[list[Attack], list[str]]:
    content_by_section = {s.title: s.content for s in draft.sections}
    attacks: list[Attack] = []
    dropped: list[str] = []
    for c in candidates:
        if not quote_is_grounded(c.quoted_claim, content_by_section.get(c.section)):
            dropped.append(f"{c.section}: quoted_claim not found verbatim in draft section")
            continue
        attacks.append(Attack(**c.model_dump()))
    return attacks, dropped
```

**Per-section grounding gate with fallback** (generalizes
`valuation_interpreter.py::run_valuation_interpreter`'s whole-output gate to per-section):

```python
def apply_grounding_gate(
    sections: list[MemoSectionAgentOutput], known_raw: set[float]
) -> tuple[list[MemoSection], list[CoverageGap]]:
    expanded = expand_known_numbers(known_raw)
    grounded_sections: list[MemoSection] = []
    gaps: list[CoverageGap] = []
    for s in sections:
        content_numbers = extract_numbers(s.content)
        cited_values = [round(f.value, 4) for f in s.cited_figures]
        ok = all(is_grounded(x, expanded) for x in content_numbers) and all(
            is_grounded(v, expanded) for v in cited_values
        )
        if ok:
            grounded_sections.append(MemoSection(**s.model_dump()))
        else:
            grounded_sections.append(
                MemoSection(
                    title=s.title,
                    content=_FALLBACK.format(title=s.title),
                    cited_figures=[],
                    cited_quotes=[],
                )
            )
            gaps.append(
                CoverageGap(field=f"section:{s.title}", reason="numeric_grounding_check_failed")
            )
    return grounded_sections, gaps
```

**Closed-set structural completeness** (mirrors `investigator.py`'s degrade-gracefully idiom,
applied to attack resolutions):

```python
def _fill_missing_resolutions(
    attacks: list[Attack], resolutions: list[AttackResolution]
) -> list[AttackResolution]:
    by_index = {r.attack_index: r for r in resolutions if 0 <= r.attack_index < len(attacks)}
    return [
        by_index.get(i)
        or AttackResolution(
            attack_index=i,
            resolution=ResolutionPath.DOWNGRADED,
            explanation="not addressed by the resolve pass — auto-downgraded as a structural safety fallback",
            model_addressed=False,
        )
        for i in range(len(attacks))
    ]
```

**Stage span** (repeat the Phase 1-4 pattern exactly):

```python
with logfire.span("synthesizer_draft_stage", ticker=input.ticker) as span:
    ...
    span.set_attribute("section_fallback_count", len(gaps))
```

---

## IMPLEMENTATION PLAN

### Phase A: Contracts & deterministic helpers
- `contracts/memo.py`, `contracts/synthesis.py` (exact field lists above).
- `ratios.py::build_company_macro_profile(ticker, sic_description, bundle) ->
  CompanyMacroProfile` — latest annual period's revenue/total_debt (None if absent), CAGR
  across all annual periods with a non-null revenue (None if fewer than 2 usable points) —
  same null-propagation discipline as every other ratio function.
- `agents/memo_grounding.py` — `known_numbers_from_synthesis_input()`,
  `apply_grounding_gate()`, built on top of `agents/numeric_grounding.py`'s existing
  primitives (no regex reimplementation).

### Phase B: Core Implementation (the three agents)
- `agents/models.py` — add `SYNTHESIZER_DRAFT_MODEL`, `RED_TEAM_MODEL`,
  `SYNTHESIZER_RESOLVE_MODEL`, all `"anthropic:claude-sonnet-5"`, with a comment pointing at
  PRD §10's Phase 5 eval-gated-starting-tier note (updated this session).
- `agents/synthesizer_draft.py` — instructions built directly from the memo-writing skill's
  §1 (section-by-section good-vs-boilerplate), explicit "never write DEFERRED content" list
  (skill §3), explicit null/coverage-gap propagation instruction (never coerce a `None` field
  into a signal — same phrasing precedent as `macro.py`'s instructions).
- `agents/red_team.py` — instructions built from skill §4 Pass 2 verbatim (two failure modes:
  untraceable claims, boilerplate; must cite section + exact sentence + missing checklist item
  where applicable).
- `agents/synthesizer_resolve.py` — instructions built from skill §4 Pass 3 verbatim (every
  attack gets exactly one of three resolution paths; "reads as if it already survived the
  attack, not as if the attack was ignored").

### Phase C: Integration
- `pipeline.py::run_memo_pipeline(ticker)` — the fixed sequence:
  1. `fetch_all(ticker)` (propagates `TickerOutOfScope` unchanged).
  2. `asyncio.gather` — Financial Statements / Filings / Transcript analysts.
  3. `deduplicate_exact_flags` (inside `run_flag_consolidator`, unchanged) → Flag Consolidator.
  4. `run_investigations(consolidated)`.
  5. `discover_sector_peers` once; `build_valuation_assumptions` + `trailing_free_cash_flows`
     + `dcf` + `peer_multiples` → `ValuationResult`; `build_company_macro_profile`.
  6. `asyncio.gather` — Sector / Macro / Valuation Interpreter.
  7. Assemble `MemoSynthesisInput` (code-owned `coverage_gaps` union of every prior stage).
  8. `run_synthesizer_draft` → `run_red_team` → `run_synthesizer_resolve`.
  9. Return `Memo`.
- Outer `logfire.span`/baggage for trace-wide `ticker` filterability (verify exact API first —
  see Documentation to READ above).

### Phase D: Evals & Validation
See Testing Strategy below — built alongside, not deferred, per CLAUDE.md's hard constraint.

---

## STEP-BY-STEP TASKS

### CREATE `src/agentic_fundamental_analyst/contracts/memo.py`
- **IMPLEMENT**: exact model list from Data Contracts above.
- **PATTERN**: `contracts/consolidation.py` (candidate/resolved split), `contracts/investigation.py` (agent-output/final split)
- **VALIDATE**: `uv run python -c "from agentic_fundamental_analyst.contracts.memo import Memo, MemoDraft, RedTeamAttack, MEMO_SECTION_ORDER"`

### CREATE `src/agentic_fundamental_analyst/contracts/synthesis.py`
- **IMPLEMENT**: `MemoSynthesisInput`, `RedTeamInput`, `SynthesizerResolveInput` — exact field lists above.
- **IMPORTS**: reuses `FinancialStatementBundle`, `FilingSections`, `RatioTrendBundle`, `ValuationResult`, `MacroSeriesBundle`, `ConsolidatedFlag`, `InvestigationVerdict`, `TickerIntakeResult`, `CoverageGap` — no redefinition.
- **VALIDATE**: `uv run pyright src/agentic_fundamental_analyst/contracts/synthesis.py`

### ADD `build_company_macro_profile` to `src/agentic_fundamental_analyst/ratios.py`
- **IMPLEMENT**: pure function, `FinancialStatementBundle` → `CompanyMacroProfile`; latest
  annual (10-K) period only for revenue/total_debt; CAGR over all annual periods with
  non-null revenue, `None` if fewer than 2.
- **PATTERN**: `compute_trend_bundle` (same file) — annual-only filtering, null-safe.
- **GOTCHA**: `FiscalPeriod.total_debt` may be `None` even when `revenue` isn't — guard independently, don't let one `None` blank out both fields.
- **VALIDATE**: new cases in `tests/unit/test_ratios.py`; `uv run pytest tests/unit/test_ratios.py -q`

### CREATE `src/agentic_fundamental_analyst/agents/memo_grounding.py`
- **IMPLEMENT**: `known_numbers_from_synthesis_input()` (harvests numbers from filing prose
  via `extract_numbers`, from every numeric field across `ratio_trend`/`financials`/
  `valuation_result`/`macro_bundles`/`latest_price`, and from prose — flag descriptions,
  consolidated-flag summaries, investigation hypothesis/reasoning/evidence claims, the three
  Phase 4 summaries, coverage-gap reasons — via `extract_numbers`); `apply_grounding_gate()`
  (per-section, see Patterns to follow).
- **PATTERN**: `agents/numeric_grounding.py` (import `extract_numbers`, `expand_known_numbers`, `is_grounded` — do not reimplement)
- **GOTCHA**: expand the known-number set once per call (not once per section) — the per-pair `expand_known_numbers` combinatorics are cheap for hundreds of values but wasted if recomputed 10x per memo.
- **VALIDATE**: `uv run pytest tests/unit/test_memo_grounding.py -q`

### CREATE `tests/unit/test_memo_grounding.py`
- **IMPLEMENT**: cases mirroring `test_numeric_grounding.py`'s six false-positive regressions
  but exercised through `known_numbers_from_synthesis_input` (build a minimal
  `MemoSynthesisInput` fixture with a comma-thousands revenue figure, an ISO date in filing
  text, a `10-year` mention, etc.) plus: a section whose `content` cites a number appearing
  ONLY in `filings.item_7_mdna` prose (proves prose-harvested numbers ground correctly); a
  section with a fabricated `cited_figures` value (proves the citation-to-reality check, not
  just the content-to-citation check, actually fires).
- **VALIDATE**: `uv run pytest tests/unit/test_memo_grounding.py -q`

### UPDATE `src/agentic_fundamental_analyst/agents/models.py`
- **IMPLEMENT**: `SYNTHESIZER_DRAFT_MODEL = SYNTHESIZER_RESOLVE_MODEL = RED_TEAM_MODEL = "anthropic:claude-sonnet-5"` (one constant each, per this file's existing "split even when identical" convention), comment citing PRD §10.
- **VALIDATE**: `uv run python -c "from agentic_fundamental_analyst.agents.models import SYNTHESIZER_DRAFT_MODEL, RED_TEAM_MODEL, SYNTHESIZER_RESOLVE_MODEL"`

### CREATE `src/agentic_fundamental_analyst/agents/synthesizer_draft.py`
- **IMPLEMENT**: `synthesizer_draft` Agent (`output_type=SynthesizerDraftAgentOutput`), `_INSTRUCTIONS` from the memo-writing skill, `run_synthesizer_draft(input: MemoSynthesisInput) -> MemoDraft` applying `apply_grounding_gate` per section, unioning `input.coverage_gaps` with any new fallback gaps.
- **PATTERN**: `agents/valuation_interpreter.py` (span shape, gate-then-fallback flow)
- **GOTCHA**: the agent must be told explicitly to emit exactly the 10 `MemoSectionTitle` values in `MEMO_SECTION_ORDER` — validate this structurally too (see next task) rather than trusting the prompt alone, per this codebase's "never trust the model to self-police what code can check" convention.
- **VALIDATE**: `uv run pytest tests/unit/test_synthesizer_draft_agent.py -q`

### UPDATE `run_synthesizer_draft` — enforce all-ten-sections-present, in order
- **IMPLEMENT**: after grounding-gate, reorder/validate `sections` against `MEMO_SECTION_ORDER`; any missing title gets a code-synthesized placeholder `MemoSection` (empty `cited_figures`, content stating the section was not produced) plus a `CoverageGap` — same degrade-gracefully idiom as `_fill_missing_resolutions`, never a crash on a malformed model output.
- **VALIDATE**: `uv run pytest tests/unit/test_synthesizer_draft_agent.py -q` (add a case with a missing section)

### CREATE `src/agentic_fundamental_analyst/agents/red_team.py`
- **IMPLEMENT**: `red_team` Agent (`output_type=RedTeamAgentOutput`), `_INSTRUCTIONS` from skill §4 Pass 2, `run_red_team(input: RedTeamInput) -> RedTeamAttack` calling `_resolve_attacks`.
- **PATTERN**: `agents/financial_statements.py::_ground_candidates` (candidate→verified split)
- **VALIDATE**: `uv run pytest tests/unit/test_red_team_agent.py -q`

### CREATE `src/agentic_fundamental_analyst/agents/synthesizer_resolve.py`
- **IMPLEMENT**: `synthesizer_resolve` Agent (`output_type=SynthesizerResolveAgentOutput`), `_INSTRUCTIONS` from skill §4 Pass 3, `run_synthesizer_resolve(input: SynthesizerResolveInput) -> Memo` — applies `apply_grounding_gate` again (resolve pass can reintroduce fabrication while rewriting), `_fill_missing_resolutions` for structural completeness, sets `generated_at=datetime.now(UTC)`.
- **PATTERN**: `agents/investigator.py::_apply_multi_angle_rule` / `_budget_exceeded_verdict` (deterministic enforcement of a rule the prompt also states)
- **VALIDATE**: `uv run pytest tests/unit/test_synthesizer_resolve_agent.py -q`

### CREATE `src/agentic_fundamental_analyst/pipeline.py`
- **IMPLEMENT**: `run_memo_pipeline(ticker: str) -> Memo`, exact sequence in Phase C above.
- **PATTERN**: CLAUDE.md's own "Run all Stage-2/3/4 agents on one ticker end to end" command block — this function is that block, made real and permanent, plus Phase 4's agents and the three new ones.
- **IMPORTS**: `fetch_all`, `discover_sector_peers`, `build_valuation_assumptions`/`trailing_free_cash_flows`/`dcf`/`peer_multiples`, `build_company_macro_profile`, all eight prior `run_X` functions, the three new `run_X` functions.
- **GOTCHA**: `latest_price`/`latest_price_date` — extract from `prices.bars` (`max(bars, key=lambda b: b.bar_date)`), never pass the full `PriceHistory` into `MemoSynthesisInput` (years of daily bars, no marginal value to the model, real token cost).
- **VALIDATE**: `uv run pytest tests/unit/test_pipeline.py -q`

### ADD Markdown/PDF rendering dependencies to `pyproject.toml`
- **IMPLEMENT**: `uv add markdown xhtml2pdf` (pure-Python HTML→PDF via `reportlab` under the
  hood — no system libraries like Cairo/Pango required, unlike `weasyprint`; safer default for
  a personal dev tool with no guaranteed system-package access). If `xhtml2pdf` turns out to
  be unmaintained or broken against the installed Python version at execution time, the
  fallback is `fpdf2` (also pure-Python) — note whichever is actually used in the plan's
  Execution Deviations, don't silently swap without recording why.
- **VALIDATE**: `uv run python -c "import markdown, xhtml2pdf"`

### CREATE `src/agentic_fundamental_analyst/render.py`
- **IMPLEMENT**: `render_memo_to_markdown(memo: Memo) -> str` — a header (ticker, rating,
  conviction, `generated_at`), then each of the 10 `MemoSection`s in `MEMO_SECTION_ORDER`
  (humanized title, `content`), then a mechanically-generated full sourcing table built from
  every section's `cited_figures`/`cited_quotes` concatenated (deterministic — this is the
  "literal traceability table" Section 10 describes, generated from real typed data rather
  than trusting the model's own Appendix section prose alone), then `coverage_gaps` as a
  bulleted list. `render_memo_to_pdf(memo, output_path)` — `render_memo_to_markdown()` →
  `markdown.markdown()` (HTML) → `xhtml2pdf.pisa.CreatePDF()` (PDF bytes) → write to
  `output_path`.
- **PATTERN**: pure formatting function, no Logfire span (not a pipeline stage — a
  post-processing utility, same category as `ratios.py`'s pure functions, not `agents/*.py`'s
  `run_X` stage functions)
- **GOTCHA**: `MemoSectionTitle`'s snake_case values (`"executive_summary_and_recommendation"`)
  need a small title-case lookup for display, not just `.replace("_", " ").title()` verbatim —
  "Recommendation & Sizing" and "Appendix / Sourcing" (PRD §3's real section names) don't
  round-trip cleanly from the Literal's snake_case; hardcode the PRD §3 display names in a
  `dict[MemoSectionTitle, str]` rather than deriving them.
- **VALIDATE**: `uv run pytest tests/unit/test_render.py -q`

### CREATE the five new plumbing test files (TestModel-scripted, network-free)
- **IMPLEMENT**: mirror `tests/unit/test_valuation_interpreter_agent.py`'s shape — one "produces valid output_type" test per agent, one grounded-summary-kept test, one fabricated-number-falls-back test, one missing-section/missing-resolution structural test each where applicable; `test_pipeline.py` overrides all eleven agents with `TestModel` (or scripted `FunctionModel` where a specific output shape matters) and asserts the full call graph completes and returns a `Memo` with 10 sections.
- **VALIDATE**: `uv run pytest tests/unit -q` (full suite — zero regressions)

### CREATE `tests/unit/test_render.py`
- **IMPLEMENT**: build a small fixture `Memo` (2-3 sections is enough — this is pure
  formatting logic, not a grounding test) and assert: `render_memo_to_markdown()` contains the
  ticker, rating, every section's content, and every `cited_figures` source string;
  `render_memo_to_pdf()` writes a file whose first bytes are `b"%PDF"` (a real, valid PDF
  header — the cheapest meaningful assertion that the HTML→PDF step actually produced a PDF,
  without needing a PDF-parsing dependency just to test one).
- **VALIDATE**: `uv run pytest tests/unit/test_render.py -q`

### CREATE `evals/synthesizer_draft.py`, `evals/red_team.py`, `evals/synthesizer_resolve.py`
- **PATTERN**: `evals/valuation_interpreter.py` (grounding evaluator + LLMJudge), `evals/flag_consolidator.py` (closed-set structural evaluator, no judge where recall/deterministic suffice)
- **VALIDATE**: `ANTHROPIC_API_KEY=<key> uv run python -m evals.synthesizer_draft` (and `.red_team`, `.synthesizer_resolve`) — real spend, see Testing Strategy for the passing bar

### UPDATE `.agents/references/agents.md`, `evals.md`, `observability.md`
- **IMPLEMENT**: replace each file's "Not yet built (Phase 5+)" placeholder with the real
  account (module paths, model tier, grounding mechanism, live-verification results) — same
  depth as the Phase 4 entries already there.

### UPDATE `CLAUDE.md`
- **IMPLEMENT**: mark Phase 5 complete in Current State, per the file's own mandatory-update
  rule; update the 6-tuple `fetch_all` note if unchanged (it is); add a
  `run_memo_pipeline(ticker)` command block replacing "not yet available."

---

## TESTING STRATEGY

### Unit tests (deterministic, CI-safe)
- `test_ratios.py` — `build_company_macro_profile`: full data, missing total_debt only,
  fewer-than-2-annual-periods (CAGR → `None`), zero annual periods.
- `test_memo_grounding.py` — see task above; must include a regression case per each of the
  six numeric-grounding false-positive categories, exercised through the larger
  `MemoSynthesisInput` surface (not just re-running `test_numeric_grounding.py`'s existing
  cases — this file's job is proving the *new* known-numbers harvesting is complete, not
  re-testing the shared regex).
- `test_synthesizer_draft_agent.py` — valid output_type; grounded content kept; fabricated
  number in `content` falls back (section-level, other 9 sections untouched); fabricated
  `cited_figures` value falls back even when `content` itself cites no numbers; missing
  section title gets a code-synthesized placeholder + `CoverageGap`; out-of-order sections
  get reordered to `MEMO_SECTION_ORDER`.
- `test_red_team_agent.py` — valid output_type; a real quoted_claim survives into `Attack`;
  a fabricated/paraphrased quoted_claim is dropped into `dropped_candidates`, not silently
  kept.
- `test_synthesizer_resolve_agent.py` — valid output_type; every attack index gets a real
  resolution; a missing attack index gets `_fill_missing_resolutions`'s fallback with
  `model_addressed=False`; a resolve-pass-introduced fabricated number still triggers the
  grounding fallback (proves the gate reapplies, not just at draft time).
- `test_pipeline.py` — full call graph with `TestModel` on every agent, asserts a `Memo` with
  exactly 10 sections in `MEMO_SECTION_ORDER` comes back; `TickerOutOfScope` still propagates
  unchanged for an excluded-sector ticker (regression guard — a bank/insurer/REIT ticker must
  still fail fast before any agent runs, even with the new stages added).

### Eval datasets (Pydantic Evals)

**`evals/synthesizer_draft.py`** — cases: `clean_grounded_full_coverage` (baseline, every
upstream field populated), `thin_data_coverage_gaps_propagate` (no transcript, no peer comps,
no DCF — asserts none of these becomes an implied bullish/bearish signal, CLAUDE.md hard
constraint), `flag_and_investigation_synthesized` (a resolved `benign` capex verdict present
— asserts the Financial Analysis / Earnings Quality sections actually reference it, not just
restate the raw ratio). Evaluators: `MemoGroundingEvaluator` (per-section `is_grounded` +
`fallback_triggered`, deterministic hard gate, 100% required — `is_grounded` holds by
construction given the runtime gate, `fallback_triggered` is the real quality signal, target
0% across cases), `AllTenSectionsPresentInOrder` (deterministic hard gate), recall check for
propagated coverage-gap substrings, `LLMJudge` rubric quoting the memo-writing skill's
good-vs-boilerplate criteria directly (never re-derive the rubric text — copy it) plus the
"never implies DEFERRED content" rule (no "consensus"/"Street"/fabricated transcript-tone
claims) and the reframed-thesis rule (no "vs. Street", must use reverse-DCF/own-history/macro
comparison per skill §1.2).

**`evals/red_team.py`** — cases: `boilerplate_thesis_no_falsifiable_trigger`,
`missing_checklist_item_in_earnings_quality` (a real flag exists in the fixture's
`consolidated_flags` but the fixture draft's Earnings Quality section omits it — expects a
`boilerplate` attack naming that `checklist_item`), `generic_risk_factor_copy_paste` (Item 1A
boilerplate pasted verbatim into Risks & Mitigants), `clean_draft_few_or_no_attacks`
(over-attacking guard — a specific, well-sourced, checklist-covered fixture draft should draw
few/zero attacks, mirroring "raising zero flags is valid" precedent). Evaluators:
`AttackQuoteGroundedEvaluator` (deterministic hard gate — every surviving `Attack.quoted_claim`
verifies via `quote_is_grounded` against the draft section it names), recall check for the
expected `AttackCategory` per case, `LLMJudge` rubric on attack substantiveness (cites the
specific section/sentence/checklist item — PRD §8's own named example of where a judge is the
right tool).

**`evals/synthesizer_resolve.py`** — cases: `attack_reground_with_real_source_available`,
`attack_downgrade_forward_looking_no_hard_source`, `attack_cut_irrelevant_claim`,
`multiple_attacks_all_addressed` (structural completeness under load — 4+ attacks in one
case). Evaluators: `AllAttacksAddressedEvaluator` (deterministic hard gate —
`{r.attack_index for r in resolutions} == set(range(len(attacks)))`), `MemoGroundingEvaluator`
(reused — the final `Memo.sections` must still pass the per-section gate),
`AllTenSectionsPresentInOrder` (reused), recall check on `metadata["expected_resolution_path"]`
per attack, `LLMJudge` rubric quoting skill §4 Pass 3 verbatim ("reads as if it already
survived the attack, not as if the attack was ignored").

**`evals/memo_pipeline_e2e.py`** (optional — Level 5 only, see Validation Commands) — 2 cases
against real tickers, mirroring the Investigator's own canonical-case precedent:
`googl_ai_buildout_benign_e2e`, a declining-core-business analog for the "concerning" case
(candidate: `INTC`, echoing `agents.md`'s Investigator-eval framing — pick whichever real
company currently has a live, well-documented declining-core-vs-buildout-capex story;
re-verify the framing is still current before running, don't assume the Investigator eval's
INTC case is timeless). Runs the *entire* `run_memo_pipeline()` — very expensive (11 agent
calls, several with large filing-text payloads), not a CI gate, run manually and rarely.
Checks: `Memo`-level `MemoGroundingEvaluator` at 100%, `Memo.rating` direction is directionally
sane given the fixture's known story (soft, human-reviewed judgment call — do not hard-fail
CI on rating direction, that's exactly the kind of over-fit-to-one-outcome eval CLAUDE.md warns
against).

### Edge cases
- Zero consolidated flags → zero investigations → `investigations: []`, Earnings Quality
  section states this plainly (not "no data available," which reads as a gap; a genuinely
  clean set of financials is a valid finding, same as Phase 1's "raising zero flags" precedent).
- `transcript_analyst_summary is None` (no transcript found) → Investment Thesis /
  Recommendation sections never reference "management commentary" or "guidance" — this needs
  an explicit prompt instruction, not just relying on the input being absent (a model can
  still hallucinate "management indicated..." even with `None` input if not told not to).
- `valuation_result.dcf is None` and/or `.comps is None` — same null-propagation instruction
  already proven in `valuation_interpreter.py`'s prompt, now needs restating in the
  Synthesizer's Valuation section specifically.
- A ticker with a very large 10-K (Filings Analyst's own note: 65K-132K input tokens already
  at that single-agent stage) — `MemoSynthesisInput` carries the *full* `FilingSections`
  again, so the draft/red-team/resolve calls could be substantially larger. Flagged in Notes,
  not solved this phase (no truncation strategy built yet — same accepted-gap precedent as
  `agents.md`'s "No truncation built yet" for the Filings Analyst itself).
- Investigation `coverage_gaps` from skipped-due-to-budget flags (`max_investigations=5`
  cutoff) must appear in the final `Memo.coverage_gaps`, not just live inside the
  intermediate `run_investigations()` return tuple — verify the union in `pipeline.py`
  actually includes `stage_gaps`, not just `verdicts`.

---

## VALIDATION COMMANDS

### Level 1: Syntax & style
```
uv run ruff check .
uv run pyright src tests evals
```

### Level 2: Unit tests
```
uv run pytest tests/unit -q
```
Zero regressions against the current 157-passing baseline; expect roughly +25-35 new tests.

### Level 3: Evals
```
ANTHROPIC_API_KEY=<key> uv run python -m evals.synthesizer_draft
ANTHROPIC_API_KEY=<key> uv run python -m evals.red_team
ANTHROPIC_API_KEY=<key> uv run python -m evals.synthesizer_resolve
```
Passing bar: every deterministic hard-gate evaluator at 100% across all cases (no exceptions
— per CLAUDE.md, a failing hard gate is never loosened, it's fixed or flagged); recall checks
100%; `LLMJudge` at least (N-1)/N per dataset (same "softest bar, never loosen further"
precedent as `evals/valuation_interpreter.py`'s docstring) — if a judge miss looks like noise
on inspection (per the `transcripts` dataset's documented precedent), say so explicitly rather
than re-rolling or loosening the rubric.

### Level 4: Manual (live)
```python
import asyncio
from agentic_fundamental_analyst.pipeline import run_memo_pipeline
from agentic_fundamental_analyst.render import render_memo_to_pdf


async def main():
    memo = await run_memo_pipeline("GOOGL")
    print(memo.rating, memo.conviction, len(memo.sections), len(memo.coverage_gaps))
    render_memo_to_pdf(memo, "googl_memo.pdf")


asyncio.run(main())
```
Confirm `googl_memo.pdf` opens as a real, readable PDF with all 10 sections present and
legible — this is the actual product-level deliverable this phase now targets, not just a
`Memo` object, so open the file and read it, don't just check the `%PDF` byte-header
programmatic test passed.
Inspect the Logfire trace: one trace, `ticker` baggage-filterable across every span
(financial_statements_analyst_stage through synthesizer_resolve_stage); confirm
`synthesizer_draft_stage`/`red_team_stage`/`synthesizer_resolve_stage` all appear with
non-zero `operation.cost`; confirm `section_fallback_count` is 0 (or investigate why not) on
a real run. Inspect the printed `Memo` directly for the two failure modes red-team exists to
catch (boilerplate, untraceable claims) even if the eval dataset already passed — real-ticker
output is where Phase 1-4's actual bugs were caught, not the fixtures.

### Level 5 (optional): Full-pipeline smoke run
```
ANTHROPIC_API_KEY=<key> uv run python -m evals.memo_pipeline_e2e
```
Expensive (11 agent calls per ticker, 2 tickers) — run once after Level 4 looks clean, not on
every iteration.

---

## ACCEPTANCE CRITERIA
- [ ] Contracts match this plan exactly; no untyped (`dict`) inter-stage boundary introduced
      anywhere in Phase 5's new code
- [ ] All five validation levels pass; eval bar met per Level 3 above
- [ ] `Memo.sections` always has exactly 10 entries in `MEMO_SECTION_ORDER`, even under
      malformed model output (structural fallback, not a crash)
- [ ] Per-section deterministic groundedness check in place; `is_grounded` 100% by
      construction on every real run (fallback content is itself trivially grounded — it
      cites no numbers)
- [ ] Every `AttackResolution.attack_index` in a delivered `Memo.resolutions` has exactly one
      record — no attack silently unaddressed, no fabricated resolution for a nonexistent
      attack
- [ ] Logfire trace shows all three new stage spans with cost attributes; trace-wide `ticker`
      baggage confirmed working (not just locally-scoped `ticker=` kwargs, PRD §9's literal
      requirement)
- [ ] No regressions in any of the eight prior eval datasets or the 157-test unit baseline
- [ ] `CLAUDE.md`, `agents.md`, `evals.md`, `observability.md` updated per their own
      mandatory-update conventions

## COMPLETION CHECKLIST
- [ ] Tasks executed in order, each validation passed immediately
- [ ] Full unit suite + all eleven eval datasets (8 prior + 3 new) pass
- [ ] Manual trace inspection done on a real ticker (GOOGL, matching every prior phase's
      live-verification precedent)
- [ ] Plan file updated with an Execution Deviations section documenting anything caught only
      by live validation — every prior phase found real bugs this way; assume this one will
      too

## NOTES

**Cost — the reason this phase's model tier was revisited before planning began.** This
phase's three new calls are the largest single prompts in the pipeline: `MemoSynthesisInput`
carries the *full* `FilingSections` (already 65K-132K input tokens at the single-agent Filings
Analyst stage per `agents.md`) plus the full `RatioTrendBundle`/`FinancialStatementBundle`,
and the draft/red-team/resolve calls stack similarly large context three times in sequence
(red-team sees the draft *and* the same synthesis input; resolve sees both prior outputs *and*
the synthesis input again). This is exactly the token-volume concern that prompted moving this
phase's tier from Opus to Sonnet (PRD §10, this session) rather than defaulting to the
Investigator's Opus precedent. Real cost is unmeasured until Level 4 — treat the PRD's
~$2/run ceiling (§11) as the thing to check against on the first live run, not an assumption.

**Deferred, explicitly out of scope for this phase**: prompt truncation/summarization
strategy for very large filings (no truncation exists anywhere in the pipeline yet — same
accepted gap as the Filings Analyst); a diff/patch-mode resolve pass (full-rewrite chosen
instead, see Problem/Solution #4); segment-level XBRL data for a richer Business Overview
section (not fetched anywhere in this codebase — Business Overview relies on `item_1_business`
prose only, a pre-existing "known permanent gap," not new to this phase); portfolio-level
position sizing (PRD §7, explicitly deferred at the product level, not a Phase 5 concern).

**Rendering scope, added mid-plan**: originally this plan scoped Phase 5 to stop at the typed
`Memo` object (matching PRD §3's literal "Final Artifact Specification," which is the typed
model, not a rendered document — the PRD never mentions PDF output anywhere). The user asked,
after reading the plan, to add Markdown/PDF rendering to this same execution rather than as a
later follow-up. Scoped as pure deterministic post-processing (`render.py`, not called from
`pipeline.py` or any agent) specifically so it can't leak into the pipeline's own grounding
guarantees or its unit/eval tests' network/filesystem isolation — a bug in PDF layout should
never be able to affect whether `Memo` itself is correct or grounded. `markdown` +
`xhtml2pdf` chosen over `weasyprint` for zero system-library dependencies (Cairo/Pango),
matching this project's "free, zero-marginal-cost, works on the builder's own machine"
principle (PRD §1) — not previously a formal project dependency, so this is a genuinely new
kind of dependency this codebase didn't have before (a document-rendering library, versus the
API-client/data/agent libraries every prior phase added).

**Carried forward from Phase 3**: `agents.md`'s note that "weighing correlated flags as one
story rather than stacking them as independent negatives is explicitly deferred to the Phase 5
Synthesizer/Red-Team." `MemoSynthesisInput.consolidated_flags` and `.investigations` both
carry `InvestigationVerdict.correlated_sibling_indices` through untouched — the Synthesizer's
`_INSTRUCTIONS` should explicitly tell it to treat correlated flags as one narrative thread in
Earnings Quality / Investment Thesis, not as independently-weighted red flags. Verify this
actually happens in eval output, not just that the prompt says to.

---

## EXECUTION DEVIATIONS (post-implementation)

### 1. All three new agents needed an explicit `max_tokens` — the default silently truncated output

pydantic-ai defaults `max_tokens=4096` for Anthropic calls (confirmed against installed
`pydantic_ai.models.anthropic` source: `model_settings.get('max_tokens', 4096)`). Every prior
agent in this codebase produces a small structured output (a short summary plus a handful of
flags/candidates), so this default was never a problem. Phase 5's three agents are the first
to produce output on the scale of an entire memo — running `evals.synthesizer_draft` for the
first time, all three cases failed with `UnexpectedModelBehavior: Exceeded maximum output
retries (1)`. Walking the exception's `__cause__` chain revealed the real error: a
`ValidationError` for `SynthesizerDraftAgentOutput` with `sections` reported as **entirely
missing** (`{'rating': 'buy', 'conviction': 'medium'}` — no `sections` key at all), meaning the
model's tool-call JSON was cut off by the 4096-token cap before it ever reached the `sections`
field. Fixed by setting `model_settings=ModelSettings(max_tokens=8192)` on
`synthesizer_draft`/`red_team` and `max_tokens=10000` on `synthesizer_resolve` (which rewrites
all ten sections *and* emits a resolutions list — strictly more output than the draft pass).
Not anticipated in the plan; caught only by actually running the eval dataset, not by any unit
test (`TestModel` never exercises real token limits). If a future agent's output type grows
similarly large, check this first before assuming a prompt or schema problem.

### 2. `expand_known_numbers`'s unrestricted pairwise cross-product broke down at Phase 5's scale

Caught by this phase's own unit test suite, not a live model run. Phase 4's
`agents/numeric_grounding.py::expand_known_numbers` combines every pair in the known-numbers
set (percent-difference and ratio transforms) with no restriction — safe for Phase 4's small
(10-20 value), homogeneous, comparison-oriented known sets (peer multiples, macro rates), but
Phase 5's `known_numbers_from_synthesis_input` harvests dozens of heterogeneous values (raw
dollar figures in the millions next to small ratios like 0.02). A test asserting a fabricated
~$1e8 `SourcedFigure` value should fail grounding instead passed: a real revenue figure
(~$2M) divided by a real but unrelated small ratio (~0.02) produced a spurious ~$99M
combination that fell within `numeric_grounding`'s *relative* 1% tolerance (huge in absolute
terms for a number that size) of the fabricated value. Fixed by giving `memo_grounding.py` its
own bounded expansion (`_expand_known_numbers`, capping pairwise combination to pairs within
100x magnitude of each other — a legitimate narrative comparison always compares two numbers
of roughly the same kind and scale) rather than reusing the shared Phase 4 function, leaving
Phase 4's own already-passing agents untouched. See `test_memo_grounding.py`'s
`test_apply_grounding_gate_falls_back_on_fabricated_cited_figure_even_with_clean_content`.

### 3. `fallback_triggered` fired live — the safety net working as designed, not a defect

Across the three real eval runs (`synthesizer_draft`: 1/3 cases; `synthesizer_resolve`: 2/4
cases), the per-section numeric-grounding gate fired at least once, replacing a section's
content with the fallback string. Investigated directly rather than assumed benign: re-running
`synthesizer_draft`'s `clean_grounded_full_coverage` case's `investment_thesis` section in
isolation reproduced fully-grounded content on a fresh sample (every extracted number traced
cleanly), and `synthesizer_resolve`'s `attack_cut_irrelevant_claim` case's fallback landed on
`appendix_and_sourcing` while every hard/structural gate (`AllAttacksAddressedEvaluator`,
`AllTenSectionsPresentInOrder`, the independently-recomputed `is_grounded`,
`ExpectedResolutionPath`, `LLMJudge`) passed on every case in every run. This is the grounding
gate doing exactly what it's designed to do — occasionally the model states a genuinely
ungrounded claim (plausible root cause for `appendix_and_sourcing` specifically: this section's
job is to describe the memo's *own* sourcing discipline, which can tempt the model into stating
a self-referential count — e.g. "N figures across M sections" — that is true of the model's own
output but by definition isn't present anywhere in the upstream typed input, so it can never
ground). Per CLAUDE.md's "never quietly patch an eval result," this is reported honestly rather
than re-rolled to force a cleaner-looking number. `fallback_triggered` is correctly a soft
quality signal, not a hard gate, exactly as both this dataset's and `evals/valuation_interpreter.py`'s
docstrings already frame it. Candidate follow-up (not done here, not required for this phase to
ship): tighten the `appendix_and_sourcing` prompt instruction to avoid stating specific counts,
since `render.py` already mechanically generates the real citation table from typed data
separately.

### 4. A real fixture bug in `evals/red_team.py`'s "clean" negative case

Found live: the `red_team` eval's model correctly attacked the `clean_draft_few_or_no_attacks`
case's executive-summary claim of "$120 million of annual capacity" as untraceable — and it was
right to. That fact was present in `evals/synthesizer_draft.py`'s and
`evals/synthesizer_resolve.py`'s filing-text fixtures but had been dropped from
`evals/red_team.py`'s own (shorter) `item_7_mdna` fixture when it was written, so the "known-
good" content this file authored contained a real, unfounded claim. Fixed by adding the same
capacity detail to `evals/red_team.py`'s `item_7_mdna`, matching the other two files — the same
"fix what the fixture's content actually says, not what the eval checks for" precedent
documented in `evals.md` for Phase 2's `filings` dataset. The run had already passed
(`FewAttacksOnCleanDraft` tolerates ≤1 attack, so this didn't fail the case), so this fix
wasn't re-verified with another paid run; low risk, purely additive to the fixture's realism.

### 5. Real GOOGL end-to-end run: consistently rate-limited, not completed live

Level 4's manual live validation (`run_memo_pipeline("GOOGL")` + `render_memo_to_pdf`) was
attempted three times across roughly 10 minutes and failed identically each time with a 429
from Anthropic: `This request would exceed your rate limit of 500,000 input tokens per minute`
— specifically on the **first** Phase 5 call, `synthesizer_draft`'s own request. Unlike a
transient burst (which a short wait clears), the same single request failed identically after a
90s wait and again after a 300s wait, pointing at the request's own size rather than leftover
load from this session's earlier eval runs. `MemoSynthesisInput` for a real GOOGL 10-K carries
the *full* `FilingSections` (the Filings Analyst alone was already measured at 65K-132K input
tokens for just its own narrower slice of this same filing text, per `agents.md`) plus the full
`FinancialStatementBundle`/`RatioTrendBundle`/`ValuationResult`/macro bundles/flags/
investigations — plausibly large enough on its own to approach a meaningful fraction of a
per-minute cap, especially stacked against whatever else this Anthropic org used in the same
window. **Not resolved this phase** — this is a real operational constraint the Notes section
below already flagged as a risk before any live run was attempted (see "Cost — the reason this
phase's model tier was revisited"), now confirmed concretely rather than theoretically. Every
other validation level (unit tests, eval datasets, lint/type-check) completed successfully
against real API calls; only the single largest possible payload (a real ticker's full
`MemoSynthesisInput`) hit this wall. Candidate fixes, out of this phase's scope: confirm the
account's actual rate-limit tier isn't set unusually low, or design a filing-text truncation/
summarization strategy for `MemoSynthesisInput` (the same "no truncation built yet" gap already
flagged for the Filings Analyst itself) — both are Phase 6-shaped (cost/latency hardening), not
Phase 5 correctness concerns. `run_memo_pipeline()` and `render_memo_to_pdf()` are both
implemented, tested (via `TestModel`), and ready to run against a real ticker whenever this is
resolved or on an account with more headroom.
