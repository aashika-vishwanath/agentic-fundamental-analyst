"""The Synthesizer — resolve pass (Phase 5). Answers or downgrades every
Red-Team attack and produces the Memo that ships. Full-rewrite, not a patch:
regenerates all ten sections given the draft, the attacks, and the same full
MemoSynthesisInput context, per PRD §4's literal roster I/O
(MemoDraft + RedTeamAttack -> Memo).

Directly targets PRD §14's stated risk -- "sycophantic resolve-pass (caves to
red-team without real re-grounding)" -- with a structural check, not just a
prompt instruction: every attack index must have exactly one AttackResolution
record (_fill_missing_resolutions), and the per-section numeric grounding
gate (agents/memo_grounding.py) reapplies here too, since a resolve pass
rewriting content could reintroduce a fabricated number while "fixing"
something else. See .agents/plans/phase-5-synthesis-redteam-pipeline.md.
"""

from datetime import UTC, datetime

import logfire
from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings

from agentic_fundamental_analyst import config, observability  # noqa: F401
from agentic_fundamental_analyst.agents.memo_grounding import (
    apply_grounding_gate,
    known_numbers_from_synthesis_input,
)
from agentic_fundamental_analyst.agents.models import SYNTHESIZER_RESOLVE_MODEL
from agentic_fundamental_analyst.contracts.financials import CoverageGap
from agentic_fundamental_analyst.contracts.memo import (
    MEMO_SECTION_ORDER,
    Attack,
    AttackResolution,
    Memo,
    MemoSection,
    ResolutionPath,
    SynthesizerResolveAgentOutput,
)
from agentic_fundamental_analyst.contracts.synthesis import SynthesizerResolveInput

_INSTRUCTIONS = """\
You are the Synthesizer for a fundamental-equity research system, writing the
RESOLVE pass -- the final memo that ships. You receive a
SynthesizerResolveInput: the drafted MemoDraft, the Red-Team's RedTeamAttack
(a 0-indexed list of `attacks`, each naming a section, a quoted_claim from
that section, and a critique), and the same full MemoSynthesisInput the draft
pass saw.

For EVERY attack in `red_team.attacks` (there may be zero), you MUST produce
exactly one AttackResolution in `resolutions`, with `attack_index` set to
that attack's position in the list. Each resolution states one of three
paths:
- re_grounded: a real source for the challenged claim DOES exist in
  `synthesis_input` -- keep the claim, but make sure the rewritten section
  actually cites it (a real SourcedFigure in `cited_figures`, or a real
  quoted span).
- downgraded: the claim has some basis but isn't a hard fact -- rewrite it
  explicitly as a stated assumption or caveat, not asserted as established.
- cut: the claim has no real basis -- remove it entirely from the rewritten
  section's content.
Never silently drop a challenged claim without picking one of these three and
rewriting the section accordingly -- the delivered memo should read as if it
already survived the attack, not as if the attack was ignored. Do not simply
restate the draft's original sections unchanged when there are real attacks
to address.

Rewrite ALL ten sections (not just attacked ones) from the draft plus
whatever changes the resolutions above require, following the same section
structure, numbering, and citation discipline (`cited_figures` per section)
as the draft pass. Re-state the final `rating` and `conviction` -- these may
change if resolving an attack invalidates a thesis pillar or valuation claim
the original rating depended on.
"""

# pydantic-ai defaults max_tokens to 4096 for Anthropic calls -- raised here
# for the same reason as agents/synthesizer_draft.py, and higher still: this
# pass rewrites all ten full sections AND emits a resolutions list, strictly
# more output than the draft pass. See that module's comment for the full
# account of the failure this fixes.
_MAX_OUTPUT_TOKENS = 10000

synthesizer_resolve = Agent(
    SYNTHESIZER_RESOLVE_MODEL,
    name="synthesizer_resolve",
    output_type=SynthesizerResolveAgentOutput,
    instructions=_INSTRUCTIONS,
    model_settings=ModelSettings(max_tokens=_MAX_OUTPUT_TOKENS),
)


def _fill_missing_resolutions(
    attacks: list[Attack], resolutions: list[AttackResolution]
) -> list[AttackResolution]:
    by_index = {r.attack_index: r for r in resolutions if 0 <= r.attack_index < len(attacks)}
    filled: list[AttackResolution] = []
    for i in range(len(attacks)):
        if i in by_index:
            filled.append(by_index[i])
        else:
            filled.append(
                AttackResolution(
                    attack_index=i,
                    resolution=ResolutionPath.DOWNGRADED,
                    explanation=(
                        "not addressed by the resolve pass -- auto-downgraded as a "
                        "structural safety fallback"
                    ),
                    model_addressed=False,
                )
            )
    return filled


def _fill_missing_sections(
    sections: list[MemoSection],
) -> tuple[list[MemoSection], list[CoverageGap]]:
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
                    content="This section was not produced by the resolve pass.",
                    cited_figures=[],
                    cited_quotes=[],
                )
            )
            gaps.append(
                CoverageGap(field=f"section:{title}", reason="section_missing_from_resolve")
            )
    return ordered, gaps


async def run_synthesizer_resolve(input: SynthesizerResolveInput) -> Memo:
    with logfire.span("synthesizer_resolve_stage", ticker=input.draft.ticker) as span:
        result = await synthesizer_resolve.run(input.model_dump_json(indent=2))
        agent_output = result.output

        known = known_numbers_from_synthesis_input(input.synthesis_input)
        grounded_sections, grounding_gaps = apply_grounding_gate(agent_output.sections, known)
        ordered_sections, missing_gaps = _fill_missing_sections(grounded_sections)

        resolutions = _fill_missing_resolutions(input.red_team.attacks, agent_output.resolutions)
        unaddressed = sum(1 for r in resolutions if not r.model_addressed)

        span.set_attribute("section_fallback_count", len(grounding_gaps))
        span.set_attribute("section_missing_count", len(missing_gaps))
        span.set_attribute("attack_count", len(input.red_team.attacks))
        span.set_attribute("unaddressed_attack_count", unaddressed)

    return Memo(
        ticker=input.draft.ticker,
        rating=agent_output.rating,
        conviction=agent_output.conviction,
        generated_at=datetime.now(UTC),
        sections=ordered_sections,
        coverage_gaps=[*input.draft.coverage_gaps, *grounding_gaps, *missing_gaps],
        investigations=input.synthesis_input.investigations,
        resolutions=resolutions,
    )
