"""The Flag Consolidator — merges list[Flag] across all three Stage-2
analysts into list[ConsolidatedFlag] (PRD §4). Runs after a deterministic
exact-dedup pass (src/agentic_fundamental_analyst/flags.py). Grounding here
is index-based, not quote- or table-based: the agent only ever refers to an
already-deduped flag by its 0-based position in the array it was given —
never by restating its content — so the resolution step can verify every
output flag is provably one of the real inputs, the same "never trust the
model to echo structured data back correctly" principle as Phase 1's
_ground_candidates, applied to the one place in this phase where the
Phase-1-style closed-set trick maps directly (the input flag list really is
a closed set).
"""

import json

import logfire
from pydantic_ai import Agent

from agentic_fundamental_analyst import config, observability  # noqa: F401
from agentic_fundamental_analyst.agents.models import FLAG_CONSOLIDATOR_MODEL
from agentic_fundamental_analyst.contracts.consolidation import (
    ConsolidatedFlag,
    FlagConsolidatorAgentOutput,
    FlagGroupCandidate,
)
from agentic_fundamental_analyst.contracts.flags import Flag
from agentic_fundamental_analyst.flags import deduplicate_exact_flags

_INSTRUCTIONS = """\
You are the Flag Consolidator for a fundamental-equity research system. You
receive a JSON array of Flags already raised by upstream analysts, each with
a metric, fiscal_year, fiscal_period, severity, and description. The array
is 0-indexed -- refer to each flag ONLY by its position in that array. Never
restate a flag's content; you don't have its full data anyway (its numeric
or quoted source is withheld from you because it isn't needed for this
task).

Task: group flags that describe the SAME underlying real-world issue, even
if raised by different analysts with different phrasing or different metric
names (e.g. a ratio-based capex-spike flag and a filing-text flag both about
the same disclosed capital-expenditure program, for the same fiscal year).
Do NOT group flags merely because they share a metric name if their
descriptions don't actually describe the same real issue. Leaving a flag
ungrouped (in a group of its own, or referencing it in no group at all) is
correct and expected when nothing else in the list relates to it -- do not
force unrelated flags together to seem thorough. For each group you do form,
write a short `summary` of the shared underlying issue.
"""

flag_consolidator = Agent(
    FLAG_CONSOLIDATOR_MODEL,
    name="flag_consolidator",
    output_type=FlagConsolidatorAgentOutput,
    instructions=_INSTRUCTIONS,
)


def _resolve_groups(
    flags: list[Flag], groups: list[FlagGroupCandidate]
) -> tuple[list[ConsolidatedFlag], list[str]]:
    consolidated: list[ConsolidatedFlag] = []
    dropped: list[str] = []
    used: set[int] = set()
    for g in groups:
        valid = [i for i in g.flag_indices if 0 <= i < len(flags) and i not in used]
        invalid = [i for i in g.flag_indices if i not in valid]
        if invalid:
            dropped.append(f"group referenced invalid/duplicate indices {invalid}")
        if not valid:
            continue
        consolidated.append(ConsolidatedFlag(flags=[flags[i] for i in valid], summary=g.summary))
        used.update(valid)
    for i, flag in enumerate(flags):
        if i not in used:
            # Every flag must survive consolidation even if the model
            # grouped nothing for it — a flag must never silently disappear.
            consolidated.append(ConsolidatedFlag(flags=[flag], summary=flag.description))
    return consolidated, dropped


async def run_flag_consolidator(all_flags: list[Flag]) -> list[ConsolidatedFlag]:
    deduped = deduplicate_exact_flags(all_flags)
    if not deduped:
        return []
    with logfire.span("flag_consolidator_stage", flag_count=len(deduped)) as span:
        prompt = json.dumps(
            [f.model_dump(exclude={"source"}, mode="json") for f in deduped], indent=2
        )
        result = await flag_consolidator.run(prompt)
        consolidated, dropped = _resolve_groups(deduped, result.output.groups)
        span.set_attribute("consolidated_group_count", len(consolidated))
        span.set_attribute("dropped_group_reference_count", len(dropped))
    return consolidated
