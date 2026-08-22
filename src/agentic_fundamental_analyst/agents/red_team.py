"""Red-Team (Phase 5). Attacks a MemoDraft for exactly the two failure modes
.claude/skills/investment-memo-writing/SKILL.md §4 Pass 2 names: untraceable
claims and boilerplate masquerading as substance. Independently re-checks the
earnings-quality checklist against the same real data the draft pass saw
(RedTeamInput carries the full MemoSynthesisInput, not just the draft).

Grounding here is verbatim-quote verification (agents/grounding.py, the same
mechanism Phase 2's Filings/Transcript Analysts use): an attack's
`quoted_claim` must be a real substring of the section it names, or it's
dropped -- the red-team cannot invent a claim that isn't really in the draft
to attack. See .agents/plans/phase-5-synthesis-redteam-pipeline.md.
"""

import logfire
from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings

from agentic_fundamental_analyst import config, observability  # noqa: F401
from agentic_fundamental_analyst.agents.grounding import quote_is_grounded
from agentic_fundamental_analyst.agents.models import RED_TEAM_MODEL
from agentic_fundamental_analyst.contracts.memo import (
    Attack,
    AttackCandidate,
    RedTeamAgentOutput,
    RedTeamAttack,
)
from agentic_fundamental_analyst.contracts.synthesis import RedTeamInput

_INSTRUCTIONS = """\
You are the Red-Team for a fundamental-equity research system. You receive a
RedTeamInput: a drafted MemoDraft (ten sections, a rating, a conviction
tier) plus the same full MemoSynthesisInput the draft pass saw (financials,
filing text, consolidated flags, investigations, macro/sector/valuation
context). Your job is to attack the draft, not to rewrite or improve it.

Attack for exactly two failure modes:
1. untraceable_claim -- a specific sentence or number in a section that
   cannot be traced to the real typed data in `synthesis_input`. This
   includes any implied comparison to analyst consensus, "Street"
   expectations, or price targets (no such data exists in this system --
   flag any hint of it immediately), any fabricated management-guidance or
   earnings-call-tone claim when `synthesis_input.transcript_analyst_summary`
   is null, and any dollar or percent-of-portfolio position size in
   recommendation_and_sizing (this system has no portfolio-level state).
2. boilerplate -- a claim that reads as generic sector commentary that could
   describe any company sharing this SIC code, rather than something specific
   to this company's real numbers; a thesis pillar with no falsifiable
   trigger; Item 1A risk-factor language copied near-verbatim without
   filtering to what's actually company-specific; OR a real red flag present
   in `synthesis_input.consolidated_flags` that earnings_quality_and_red_flags
   does not mention at all -- name the specific checklist item skipped in
   `checklist_item` when this applies.

For every attack, `quoted_claim` MUST be an exact, verbatim substring of the
`content` of the section named in `section` -- copy it exactly, do not
paraphrase. `critique` should explain specifically what's wrong and, for
boilerplate attacks citing a missing checklist item, name the item.

Raising zero attacks is a valid, expected outcome when a draft is genuinely
specific, well-sourced, and checklist-complete -- do not manufacture an
attack to seem thorough. Do not attack a claim merely because it is
disclosed as an assumption (e.g. the DCF discount rate) -- an assumption
correctly framed as an assumption is not untraceable.
"""

# pydantic-ai defaults max_tokens to 4096 for Anthropic calls -- raised here
# for the same reason as agents/synthesizer_draft.py: an attack list citing
# several exact-verbatim quoted_claims (some drawn from long sections) plus
# critiques can exceed the default before the model finishes. See that
# module's comment for the full account of the failure this fixes.
_MAX_OUTPUT_TOKENS = 8192

red_team = Agent(
    RED_TEAM_MODEL,
    name="red_team",
    output_type=RedTeamAgentOutput,
    instructions=_INSTRUCTIONS,
    model_settings=ModelSettings(max_tokens=_MAX_OUTPUT_TOKENS),
)


def _resolve_attacks(
    input: RedTeamInput, candidates: list[AttackCandidate]
) -> tuple[list[Attack], list[str]]:
    content_by_section = {s.title: s.content for s in input.draft.sections}
    attacks: list[Attack] = []
    dropped: list[str] = []
    for c in candidates:
        if not quote_is_grounded(c.quoted_claim, content_by_section.get(c.section)):
            dropped.append(f"{c.section}: quoted_claim not found verbatim in draft section")
            continue
        attacks.append(
            Attack(
                section=c.section,
                category=c.category,
                quoted_claim=c.quoted_claim,
                critique=c.critique,
                checklist_item=c.checklist_item,
            )
        )
    return attacks, dropped


async def run_red_team(input: RedTeamInput) -> RedTeamAttack:
    with logfire.span("red_team_stage", ticker=input.draft.ticker) as span:
        result = await red_team.run(input.model_dump_json(indent=2))
        attacks, dropped = _resolve_attacks(input, result.output.attack_candidates)
        span.set_attribute("attack_count", len(attacks))
        span.set_attribute("dropped_candidate_count", len(dropped))

    return RedTeamAttack(attacks=attacks, dropped_candidates=dropped)
