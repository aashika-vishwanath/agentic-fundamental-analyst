"""The Investigator — the system's one and only agentic loop (PRD §4, CLAUDE.md
hard constraint). Takes one ConsolidatedFlag plus lightweight sibling-flag
summaries and investigates it against outside evidence via Anthropic's native
web_search/web_fetch, returning a typed InvestigationVerdict. See
.agents/plans/phase-3-investigator.md for the full design rationale.

Grounding here is URL-provenance, the third mechanism in this codebase (after
Phase 1's closed-ratio-table lookup and Phase 2's verbatim-quote check): the
closed set is "the URLs the provider actually returned during this run",
reconstructed from the run's own message history by agents/provenance.py,
since native tool calls emit no OTel tool-call spans to check against.

Two mechanisms enforce the user's core constraint -- no one-to-one mapping of
flag to a single confirming source: the prompt instructs multi-angle,
judgment-forming search, and _apply_multi_angle_rule below deterministically
forces any verdict resting on <2 distinct *cited-evidence* domains to
UNRESOLVED rather than trusting the model to self-police it. See
evals/investigator.py's MultiAngleInvestigation evaluator for the same rule
checked independently.

IMPORTANT: this rule is deliberately keyed on the domain diversity of the
GROUNDED EVIDENCE the model actually cited (registrable_domain(e.url) for
e in evidence), never on trajectory.distinct_domains (every domain any raw
search call returned, most of them noise the model never engaged with). A
single search typically returns results from 5-10 different domains
regardless of investigation quality -- keying the rule to raw search-result
diversity would let a lazy, one-source-cited investigation pass purely on
search-engine noise. Caught live during eval validation
(.agents/plans/phase-3-investigator.md Notes) on a fictional-company case
that returned 32 raw result domains from pure SEO noise.
"""

import asyncio
import json
from decimal import Decimal

import logfire
from pydantic_ai import Agent
from pydantic_ai.capabilities import Thinking, WebFetch, WebSearch
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.usage import UsageLimits

from agentic_fundamental_analyst import config, observability  # noqa: F401
from agentic_fundamental_analyst.agents.models import INVESTIGATOR_MODEL
from agentic_fundamental_analyst.agents.provenance import (
    extract_trajectory,
    ground_evidence,
    registrable_domain,
)
from agentic_fundamental_analyst.contracts.consolidation import ConsolidatedFlag
from agentic_fundamental_analyst.contracts.financials import CoverageGap
from agentic_fundamental_analyst.contracts.flags import Severity
from agentic_fundamental_analyst.contracts.investigation import (
    InvestigationTrajectory,
    InvestigationVerdict,
    InvestigatorAgentOutput,
    SiblingFlagSummary,
    VerdictType,
)

_INSTRUCTIONS = """\
You are the Investigator for a fundamental-equity research system -- the only
agent in this system with web search and web fetch. You receive one
consolidated anomaly flag (raised deterministically from the company's own
financials or filings) and lightweight one-line summaries of any other flags
raised this run. Your job is to explain WHY the anomaly happened, using real
outside evidence, and to reach an explicit verdict: benign, concerning, or
unresolved.

How to investigate:
1. Form a hypothesis about the likely explanation BEFORE searching. Search to
   test that hypothesis, not to find a source that agrees with it.
2. Investigate from more than one angle -- choose whichever of these fit this
   specific flag, rather than exhausting all of them every time: the
   company's own explanation (press releases, investor materials); independent
   reporting (news, trade press) that corroborates or contradicts it; whether
   peers/the sector show the same pattern (context-specific vs. company-
   specific); the macro backdrop; historical precedent for this company.
3. Never cherry-pick. Report evidence that cuts against your hypothesis too --
   your `reasoning` should show you weighed evidence on both sides, not just
   the evidence that confirms one conclusion.
4. Confidence reflects corroboration, not conviction: multiple independent
   sources agreeing should raise it; a single source, or sources that
   conflict with each other, should lower it. A verdict resting on one search
   result is not confident, no matter how conclusive that one result reads.
5. `unresolved` is a correct and expected answer when the evidence is thin,
   stale, or contradictory -- do not force a benign or concerning verdict to
   seem decisive.
6. Only cite a `url` that actually appeared in your own search/fetch results
   in this run. A citation that doesn't trace back to a real search result of
   yours will be dropped before it reaches the memo.
7. If a sibling flag's one-line summary suggests it plausibly shares a root
   cause with the flag you're investigating (e.g. both trace to one disclosed
   strategic pivot), note its index in `correlated_sibling_indices`. Do not
   restate its content -- you don't have it. This flag alone is what you are
   reaching a verdict on; correlated siblings are context, not additional
   targets.
"""

investigator = Agent(
    INVESTIGATOR_MODEL,
    name="investigator",
    output_type=InvestigatorAgentOutput,
    instructions=_INSTRUCTIONS,
    capabilities=[
        Thinking(effort="medium"),
        WebSearch(max_uses=6),
        WebFetch(max_uses=4, max_content_tokens=8000),
    ],
)

_INVESTIGATOR_USAGE_LIMITS = UsageLimits(request_limit=12, cost_limit=Decimal("0.75"))

_MIN_DISTINCT_DOMAINS_TO_RESOLVE = 2


def _sibling_summary(consolidated: ConsolidatedFlag) -> SiblingFlagSummary:
    representative = consolidated.flags[0]
    return SiblingFlagSummary(
        metric=representative.metric,
        fiscal_year=representative.fiscal_year,
        fiscal_period=representative.fiscal_period,
        description=consolidated.summary,
    )


def _build_prompt(flag: ConsolidatedFlag, siblings: list[SiblingFlagSummary]) -> str:
    flag_payload = {
        "summary": flag.summary,
        "flags": [f.model_dump(exclude={"source"}, mode="json") for f in flag.flags],
    }
    return (
        "Flag to investigate:\n"
        f"{json.dumps(flag_payload, indent=2)}\n\n"
        "Other flags raised this run (context only -- do not investigate these,"
        " only note if one plausibly shares a root cause):\n"
        f"{json.dumps([s.model_dump(mode='json') for s in siblings], indent=2)}\n\n"
        "Investigate the flag above and reach a verdict."
    )


def _apply_multi_angle_rule(
    verdict: VerdictType,
    confidence: float,
    evidence_domain_count: int,
    conflicting_stances: bool,
) -> tuple[VerdictType, float, CoverageGap | None]:
    """Deterministic enforcement of the multi-angle / corroboration rule --
    the model is told this rule in the prompt, but code enforces it, per this
    project's "never trust the model to self-police what code can check"
    convention. A resolved (benign/concerning) verdict backed by CITED
    evidence spanning fewer than 2 distinct domains is downgraded to
    unresolved and a CoverageGap records why. `evidence_domain_count` must be
    derived from the grounded evidence the model actually cited, not from
    raw search-result noise -- see the module docstring."""
    thin_evidence = evidence_domain_count < _MIN_DISTINCT_DOMAINS_TO_RESOLVE
    if verdict != VerdictType.UNRESOLVED and thin_evidence:
        gap = CoverageGap(
            field="investigation_verdict",
            reason=(
                f"cited evidence spanned only {evidence_domain_count} distinct domain(s); "
                "verdict downgraded to unresolved rather than resolved on a single source"
            ),
        )
        return VerdictType.UNRESOLVED, min(confidence, 0.5), gap
    if thin_evidence:
        return verdict, min(confidence, 0.5), None
    if conflicting_stances:
        return verdict, min(confidence, 0.7), None
    return verdict, confidence, None


def _budget_exceeded_verdict(
    flag: ConsolidatedFlag, error: UsageLimitExceeded
) -> InvestigationVerdict:
    """Degrade gracefully rather than propagate. A single flag's investigation
    running over its cost/request budget must not crash the other
    investigations running concurrently in the same asyncio.gather -- and per
    this project's never-coerce-missing-data constraint, a budget cutoff is a
    CoverageGap, not a silently-forced verdict either way."""
    empty_trajectory = InvestigationTrajectory(
        search_queries=[], result_urls=[], fetched_urls=[], distinct_domains=[]
    )
    return InvestigationVerdict(
        flag=flag,
        verdict=VerdictType.UNRESOLVED,
        hypothesis="Investigation did not complete.",
        reasoning=f"Investigation halted before reaching a conclusion: {error}",
        confidence=0.0,
        evidence=[],
        correlated_sibling_indices=[],
        trajectory=empty_trajectory,
        dropped_evidence=[],
        coverage_gaps=[
            CoverageGap(
                field="investigation_verdict",
                reason=f"usage/cost budget exceeded before a verdict was reached: {error}",
            )
        ],
    )


async def run_investigator(
    flag: ConsolidatedFlag, siblings: list[SiblingFlagSummary]
) -> InvestigationVerdict:
    metric = flag.flags[0].metric if flag.flags else "unknown"
    severity = max((f.severity for f in flag.flags), default=Severity.LOW, key=list(Severity).index)
    with logfire.span("investigator_stage", metric=metric, severity=severity.value) as span:
        try:
            result = await investigator.run(
                _build_prompt(flag, siblings), usage_limits=_INVESTIGATOR_USAGE_LIMITS
            )
        except UsageLimitExceeded as error:
            span.set_attribute("verdict", "unresolved")
            span.set_attribute("budget_exceeded", True)
            return _budget_exceeded_verdict(flag, error)
        agent_output = result.output
        trajectory = extract_trajectory(result.all_messages())
        evidence, dropped = ground_evidence(agent_output.evidence, trajectory)

        stance_values = {e.stance.value for e in evidence}
        directional_stances = {"supports_benign", "supports_concerning"}
        conflicting = len(directional_stances & stance_values) > 1
        evidence_domains = {registrable_domain(e.url) for e in evidence}
        evidence_domains.discard("")
        verdict, confidence, gap = _apply_multi_angle_rule(
            agent_output.verdict,
            agent_output.confidence,
            len(evidence_domains),
            conflicting,
        )
        coverage_gaps = [gap] if gap is not None else []

        n_siblings = len(siblings)
        correlated = [i for i in agent_output.correlated_sibling_indices if 0 <= i < n_siblings]

        span.set_attribute("verdict", verdict.value)
        span.set_attribute("confidence", confidence)
        span.set_attribute("search_count", len(trajectory.search_queries))
        span.set_attribute("raw_result_domain_count", len(trajectory.distinct_domains))
        span.set_attribute("evidence_domain_count", len(evidence_domains))
        span.set_attribute("dropped_evidence_count", len(dropped))

    return InvestigationVerdict(
        flag=flag,
        verdict=verdict,
        hypothesis=agent_output.hypothesis,
        reasoning=agent_output.reasoning,
        confidence=confidence,
        evidence=evidence,
        correlated_sibling_indices=correlated,
        trajectory=trajectory,
        dropped_evidence=dropped,
        coverage_gaps=coverage_gaps,
    )


async def run_investigations(
    flags: list[ConsolidatedFlag], max_investigations: int = 5
) -> tuple[list[InvestigationVerdict], list[CoverageGap]]:
    """Investigates up to `max_investigations` flags, selected by severity
    (highest first, stable on ties). Every flag not selected surfaces as an
    explicit CoverageGap rather than being silently dropped -- this stage's
    own instance of the never-coerce-missing-data-into-a-signal constraint.

    Returns (verdicts, stage_coverage_gaps): a tuple rather than a single
    output model, since PRD §4's roster gives the Investigator's output type
    as a bare `list[InvestigationVerdict]`, and no wrapper model for
    stage-level skip-gaps is defined in this repo's contracts. Documented as
    a deviation in .agents/plans/phase-3-investigator.md Notes.
    """
    if not flags:
        return [], []

    def _severity_rank(cf: ConsolidatedFlag) -> int:
        return max((list(Severity).index(f.severity) for f in cf.flags), default=0)

    ordered = sorted(enumerate(flags), key=lambda pair: _severity_rank(pair[1]), reverse=True)
    selected_indices = {i for i, _ in ordered[:max_investigations]}
    selected = [f for i, f in enumerate(flags) if i in selected_indices]
    skipped = [f for i, f in enumerate(flags) if i not in selected_indices]

    async def _investigate(target: ConsolidatedFlag) -> InvestigationVerdict:
        siblings = [_sibling_summary(f) for f in flags if f is not target]
        return await run_investigator(target, siblings)

    verdicts = list(await asyncio.gather(*(_investigate(f) for f in selected)))

    stage_gaps = [
        CoverageGap(
            field=f"investigation:{f.flags[0].metric if f.flags else 'unknown'}",
            reason=(
                f"skipped -- investigation budget is {max_investigations} flags per run, "
                "selected by severity; this flag ranked below the cutoff"
            ),
        )
        for f in skipped
    ]
    return verdicts, stage_gaps
