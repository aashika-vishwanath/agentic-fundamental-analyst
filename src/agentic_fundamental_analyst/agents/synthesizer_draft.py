"""The Synthesizer — draft pass (Phase 5). Reads every upstream typed output
(financials, filing text, macro series, valuation, flags, investigations, and
the three Phase 4 narrated summaries) and writes a full 10-section MemoDraft.
Prompt content mirrors .claude/skills/investment-memo-writing/SKILL.md §1
directly — that skill file is the source of truth for section structure and
good-vs-boilerplate criteria, not reinvented here.

Grounding is the per-section numeric gate (agents/memo_grounding.py) — the
runtime enforcement of PRD §3's "every quantitative claim... must resolve to
a SourcedFigure," never a best-effort prompt instruction. See
.agents/plans/phase-5-synthesis-redteam-pipeline.md for the full design
rationale, including why `cited_figures` IS asked of the model here (unlike
Phase 4's agents).
"""

import logfire
from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings

from agentic_fundamental_analyst import config, observability  # noqa: F401
from agentic_fundamental_analyst.agents.memo_grounding import (
    apply_grounding_gate,
    known_numbers_from_synthesis_input,
)
from agentic_fundamental_analyst.agents.models import SYNTHESIZER_DRAFT_MODEL
from agentic_fundamental_analyst.contracts.financials import CoverageGap
from agentic_fundamental_analyst.contracts.memo import (
    MEMO_SECTION_ORDER,
    MemoDraft,
    MemoSection,
    SynthesizerDraftAgentOutput,
)
from agentic_fundamental_analyst.contracts.synthesis import MemoSynthesisInput

_INSTRUCTIONS = """\
You are the Synthesizer for a fundamental-equity research system, writing the
DRAFT pass of an investment memo. You receive a MemoSynthesisInput: the
company's filed financials and ratio trends, its filing text (Item 1, 1A,
MD&A, 8-K items), macro series, a trailing DCF plus self-built peer comps,
the consolidated red-flag list, resolved anomaly investigations, and narrated
summaries from the Sector/Macro/Valuation agents. Every number in it is
already correct -- never restate a number from memory, and never invent a
figure, peer, flag, or investigation not present in the input. A `None`
field (no transcript, no DCF, no peer comps, a missing macro-profile figure)
is a genuine data gap, never a bullish or bearish signal -- state plainly
that the data is unavailable rather than treating its absence as informative.

Write exactly these ten sections, in this order, each as its own entry in
`sections` with the matching `title`:
1. executive_summary_and_recommendation -- the rating, the one-sentence
   thesis, and the 2-3 numbers that matter, before any scene-setting.
2. investment_thesis -- 2-3 falsifiable pillars, each with a stated break
   condition. This system has NO consensus/analyst-estimate data -- never
   compare against "Street expectations" or "consensus." Instead compare
   against: what the current price implies via a reverse-DCF using the filed
   cash flows, the company's own historical trend in filed fundamentals, or
   the macro backdrop.
3. business_overview -- segment/revenue-mix drivers from Item 1 and the
   financial trend, not a restated company description.
4. financial_analysis -- the multi-year ratio trend (margins, returns,
   leverage, cash conversion), with inflection points tied to the thesis.
5. earnings_quality_and_red_flags -- run the earnings-quality checklist
   against the consolidated flags and resolved investigations; a flag with a
   `benign` verdict is not omitted, it's reported as investigated and
   resolved. Raising zero flags is a valid, expected outcome for clean
   financials.
6. valuation -- the DCF bull/base/bear present values (if available) with
   the discount rate and terminal growth stated explicitly as DISCLOSED
   ASSUMPTIONS, never as fact; cross-check against peer comps (if available).
   If either dcf or comps is null in the input, rely on whichever is
   available and say so plainly.
7. catalysts -- 2-3 dated, verifiable events from the filing text (debt
   maturities, contract/patent expirations, next filing deadline). Never
   invent a catalyst tied to management guidance or analyst estimate
   revisions -- neither data source exists here.
8. risks_and_mitigants -- company-specific downside scenarios, filtered from
   Item 1A (never copy generic risk-factor boilerplate verbatim) plus the red
   flag checklist and macro framing.
9. recommendation_and_sizing -- the rating and a qualitative conviction tier
   (high/medium/low), explicitly tied to the thesis pillars and the
   valuation gap. This system has no portfolio-level state -- never output a
   dollar or percent-of-portfolio position size.
10. appendix_and_sourcing -- a plain-language account of the memo's sourcing
    discipline; the mechanical citation table itself is generated separately
    by code from every section's `cited_figures`, not by you.

For EVERY section, populate `cited_figures` with the real SourcedFigure(s)
(value, source, as_of) backing that section's numeric claims, drawn from the
typed input -- never a number you cannot point to a real field for. A
qualitative section with no numeric claims may have an empty `cited_figures`
list. `cited_quotes` is for verbatim filing-text spans you rely on, when
relevant.

Investigations whose `correlated_sibling_indices` point at each other
describe ONE underlying story, not independent negatives -- weave them into
one narrative thread in Earnings Quality / Investment Thesis rather than
stacking them as separate red flags.
"""

# pydantic-ai defaults max_tokens to 4096 for Anthropic calls (confirmed
# against installed pydantic_ai.models.anthropic source) -- fine for every
# prior agent's small output, but a full 10-section MemoDraft (each section's
# prose plus cited_figures) genuinely needs more. Without this, the model's
# tool-call JSON was observed truncating mid-generation, before `sections`
# was emitted at all, and pydantic-ai's retry-once-on-validation-failure
# still failed the same way -- found live running this phase's own eval
# dataset, not anticipated in the plan.
#
# 8192 itself proved insufficient against a real ticker's full-size
# MemoSynthesisInput (found live this session, GOOGL, after the eval
# datasets' small synthetic fixtures had already passed at that cap): the
# `sections` array was either truncated entirely (Field required [missing])
# or, once, mis-encoded as a stringified JSON blob rather than a native
# array under the pressure of generating that much structured content (see
# contracts/memo.py's _coerce_stringified_list_fields for that separate
# fix). Claude Sonnet 5 supports up to 128K output tokens on the standard
# Messages API, and OTPM billing/rate-limits are based on tokens actually
# generated, not this cap -- raising it well above what a real memo needs is
# free, so this is deliberately generous rather than tuned to the minimum
# that happened to work once.
_MAX_OUTPUT_TOKENS = 32000

synthesizer_draft = Agent(
    SYNTHESIZER_DRAFT_MODEL,
    name="synthesizer_draft",
    output_type=SynthesizerDraftAgentOutput,
    instructions=_INSTRUCTIONS,
    model_settings=ModelSettings(max_tokens=_MAX_OUTPUT_TOKENS),
)


def _fill_missing_sections(
    sections: list[MemoSection],
) -> tuple[list[MemoSection], list[CoverageGap]]:
    """Reorders to MEMO_SECTION_ORDER and synthesizes a placeholder for any
    missing title -- a malformed model output must never crash the pipeline
    or silently drop a section, same degrade-gracefully idiom as every other
    stage function in this codebase."""
    by_title = {s.title: s for s in sections}
    ordered: list[MemoSection] = []
    gaps: list[CoverageGap] = []
    for title in MEMO_SECTION_ORDER:
        if title in by_title:
            ordered.append(by_title[title])
        else:
            ordered.append(
                MemoSection(
                    title=title,
                    content="This section was not produced by the draft pass.",
                    cited_figures=[],
                    cited_quotes=[],
                )
            )
            gaps.append(CoverageGap(field=f"section:{title}", reason="section_missing_from_draft"))
    return ordered, gaps


async def run_synthesizer_draft(input: MemoSynthesisInput) -> MemoDraft:
    with logfire.span("synthesizer_draft_stage", ticker=input.ticker) as span:
        result = await synthesizer_draft.run(input.model_dump_json(indent=2))
        agent_output = result.output
        known = known_numbers_from_synthesis_input(input)
        grounded_sections, grounding_gaps = apply_grounding_gate(agent_output.sections, known)
        ordered_sections, missing_gaps = _fill_missing_sections(grounded_sections)
        span.set_attribute("section_fallback_count", len(grounding_gaps))
        span.set_attribute("section_missing_count", len(missing_gaps))

    return MemoDraft(
        ticker=input.ticker,
        rating=agent_output.rating,
        conviction=agent_output.conviction,
        sections=ordered_sections,
        coverage_gaps=[*input.coverage_gaps, *grounding_gaps, *missing_gaps],
    )
