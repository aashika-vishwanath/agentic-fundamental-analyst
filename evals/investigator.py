"""Eval dataset for the Investigator (Phase 3) — the system's one agentic
loop. Every case makes REAL Opus 5 calls with REAL native web search/fetch;
estimated cost per case is ~$0.30-0.55 (.agents/plans/phase-3-investigator.md
Research Findings §5), so a full 4-case run is roughly $1.20-2.20.

Run with: ANTHROPIC_API_KEY=<key> uv run python -m evals.investigator

Passing bar (see .agents/plans/phase-3-investigator.md Testing Strategy):
- EvidenceProvenanceEvaluator, MultiAngleInvestigation, ConfidenceCalibration
  at 100% across all 4 cases — hard gates, deterministic.
- ExpectedVerdict 4/4 — the two canonical PRD §11 capex cases are exit
  criteria and are not negotiable; the other two are this dataset's
  clean/negative guards.
- LLMJudge >= 3/4 — softest bar; a miss gets investigated and documented,
  never silenced by loosening the rubric (Phase 2 evals.md precedent).

Trajectory evaluation reads the typed InvestigationVerdict.trajectory field
rather than pydantic-evals' ToolCorrectness/MaxToolCalls/TrajectoryMatch,
because those only recognize locally-executed tool spans and native
web_search/web_fetch calls never emit one (see the plan's Research Findings
§2 -- confirmed against the installed pydantic-evals 2.32.0 source).

Two real, well-documented companies anchor the canonical cases so a live web
search actually has something to find, rather than a fictional company
returning nothing: Alphabet's AI-infrastructure capex buildout (benign, and
the project's own established live-verification ticker) and Intel's foundry
capex buildout alongside a declining core CPU business (concerning, widely
covered by 2024). The obscure-microcap case is deliberately fictional --
that's what forces thin evidence.
"""

import json
from dataclasses import dataclass
from datetime import date
from functools import partial

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext, HasMatchingSpan, LLMJudge
from pydantic_evals.otel.span_tree import SpanQuery

from agentic_fundamental_analyst.agents.investigator import run_investigator
from agentic_fundamental_analyst.agents.models import INVESTIGATOR_MODEL
from agentic_fundamental_analyst.agents.provenance import normalize_url, registrable_domain
from agentic_fundamental_analyst.contracts.consolidation import ConsolidatedFlag
from agentic_fundamental_analyst.contracts.flags import Flag, Severity
from agentic_fundamental_analyst.contracts.investigation import InvestigationVerdict, VerdictType
from agentic_fundamental_analyst.contracts.sourcing import SourcedFigure


def _flag(metric: str, fiscal_year: int, severity: Severity, description: str) -> Flag:
    return Flag(
        metric=metric,
        fiscal_year=fiscal_year,
        fiscal_period="FY",
        severity=severity,
        description=description,
        source=SourcedFigure(value=4.3, source=f"ratios.{metric}", as_of=date(fiscal_year, 12, 31)),
    )


def _consolidated(
    metric: str, fiscal_year: int, severity: Severity, description: str
) -> ConsolidatedFlag:
    flag = _flag(metric, fiscal_year, severity, description)
    return ConsolidatedFlag(flags=[flag], summary=description)


# --- capex_spike_ai_buildout_benign (PRD §11 canonical case #1) ---
_GOOGL_CAPEX = _consolidated(
    "capex_to_depreciation_ratio",
    2024,
    Severity.MEDIUM,
    "Alphabet Inc. (GOOGL) capital expenditures rose sharply in fiscal year 2024, driven by "
    "AI and data-center infrastructure investment, pushing capex/D&A well above its historical "
    "range. Google Cloud segment revenue and operating income were both growing over the same "
    "period.",
)

# --- capex_spike_declining_core_concerning (PRD §11 canonical case #2) ---
_INTEL_CAPEX = _consolidated(
    "capex_to_depreciation_ratio",
    2024,
    Severity.HIGH,
    "Intel Corporation (INTC) capital expenditures remained elevated in fiscal year 2024 as "
    "part of its foundry/fab-buildout strategy, pushing capex/D&A well above its historical "
    "range, while its core x86 CPU business (Client Computing and Data Center segments) saw "
    "declining revenue and market share pressure from competitors over the same period.",
)

# --- obscure_microcap_thin_evidence_unresolved (over-reach guard) ---
_MICROCAP_CAPEX = _consolidated(
    "days_sales_outstanding",
    2024,
    Severity.MEDIUM,
    "Quillhaven Precision Instruments Inc. (ticker QVPI), a small obscure US-listed "
    "instrumentation manufacturer, shows a multi-period uptrend in days sales outstanding in "
    "fiscal year 2024, with no further detail available in the filings reviewed so far.",
)

# --- routine_disclosure_benign (clean/negative guard) ---
_COSTCO_CAPEX = _consolidated(
    "capex_to_depreciation_ratio",
    2024,
    Severity.LOW,
    "Costco Wholesale Corporation (COST) capital expenditures were elevated in fiscal year "
    "2024 relative to depreciation, tied to its ongoing new-warehouse-opening program, while "
    "membership revenue and comparable sales continued to grow over the same period.",
)


_MIN_QUERIES_TO_RESOLVE = 3
_MIN_DOMAINS_TO_RESOLVE = 2


def _evidence_domains(verdict: InvestigationVerdict) -> set[str]:
    """Domains of the CITED, grounded evidence only -- never
    trajectory.distinct_domains, which counts every domain any raw search
    call returned, most of it noise the model never engaged with. A single
    search typically returns 5-10 different-domain results regardless of
    investigation quality; keying diversity checks to that would let a
    one-source investigation pass on search-engine noise alone. Caught live
    on a fictional-company case that returned 32 raw domains from pure SEO
    noise while citing only 2 real pieces of evidence -- see
    .agents/plans/phase-3-investigator.md Notes."""
    domains = {registrable_domain(e.url) for e in verdict.evidence}
    domains.discard("")
    return domains


@dataclass
class EvidenceProvenanceEvaluator(Evaluator[ConsolidatedFlag, InvestigationVerdict, dict]):
    """Hard gate, independently re-derived (not trusting run_investigator's
    own grounding pass): every EvidenceItem.url in the output must appear,
    once normalized, among the trajectory's own result/fetched URLs."""

    def evaluate(
        self, ctx: EvaluatorContext[ConsolidatedFlag, InvestigationVerdict, dict]
    ) -> dict[str, bool]:
        returned = {
            normalize_url(u)
            for u in (*ctx.output.trajectory.result_urls, *ctx.output.trajectory.fetched_urls)
        }
        grounded = all(normalize_url(e.url) in returned for e in ctx.output.evidence)
        return {"evidence_provenance": grounded}


@dataclass
class MultiAngleInvestigation(Evaluator[ConsolidatedFlag, InvestigationVerdict, dict]):
    """The user's core constraint, made mechanical: a resolved
    (benign/concerning) verdict must rest on >=3 distinct search queries and
    evidence spanning >=2 distinct domains. unresolved is exempt -- it is the
    honest answer to thin evidence, not a failure to investigate broadly."""

    def evaluate(self, ctx: EvaluatorContext[ConsolidatedFlag, InvestigationVerdict, dict]) -> bool:
        if ctx.output.verdict == VerdictType.UNRESOLVED:
            return True
        enough_queries = len(ctx.output.trajectory.search_queries) >= _MIN_QUERIES_TO_RESOLVE
        enough_domains = len(_evidence_domains(ctx.output)) >= _MIN_DOMAINS_TO_RESOLVE
        return enough_queries and enough_domains


@dataclass
class ConfidenceCalibration(Evaluator[ConsolidatedFlag, InvestigationVerdict, dict]):
    """Corroboration, not conviction: thin (< 2 domain) evidence caps
    confidence at 0.5; conflicting evidence stances cap it at 0.7."""

    def evaluate(self, ctx: EvaluatorContext[ConsolidatedFlag, InvestigationVerdict, dict]) -> bool:
        domains = len(_evidence_domains(ctx.output))
        stances = {e.stance.value for e in ctx.output.evidence}
        conflicting = len({"supports_benign", "supports_concerning"} & stances) > 1
        if domains < _MIN_DOMAINS_TO_RESOLVE:
            return ctx.output.confidence <= 0.5
        if conflicting:
            return ctx.output.confidence <= 0.7
        return True


@dataclass
class ExpectedVerdict(Evaluator[ConsolidatedFlag, InvestigationVerdict, dict]):
    def evaluate(self, ctx: EvaluatorContext[ConsolidatedFlag, InvestigationVerdict, dict]) -> bool:
        expected = (ctx.metadata or {}).get("expected_verdict")
        if expected is None:
            return True
        return ctx.output.verdict.value == expected


_REASONING_QUALITY_RUBRIC = (
    "The reasoning weighs evidence on both sides of the hypothesis -- it names at least one "
    "thing that would cut against its own conclusion, or explicitly notes the absence of "
    "counter-evidence -- rather than simply restating one source that confirms the verdict."
)

_cases: list[Case[ConsolidatedFlag, InvestigationVerdict, dict]] = [
    Case(
        name="capex_spike_ai_buildout_benign",
        inputs=_GOOGL_CAPEX,
        metadata={"expected_verdict": "benign"},
    ),
    Case(
        name="capex_spike_declining_core_concerning",
        inputs=_INTEL_CAPEX,
        metadata={"expected_verdict": "concerning"},
    ),
    Case(
        name="obscure_microcap_thin_evidence_unresolved",
        inputs=_MICROCAP_CAPEX,
        metadata={"expected_verdict": "unresolved"},
    ),
    Case(
        name="routine_disclosure_benign",
        inputs=_COSTCO_CAPEX,
        metadata={"expected_verdict": "benign"},
    ),
]

dataset = Dataset(
    name="investigator",
    cases=_cases,
    evaluators=[
        EvidenceProvenanceEvaluator(),
        MultiAngleInvestigation(),
        ConfidenceCalibration(),
        ExpectedVerdict(),
        LLMJudge(rubric=_REASONING_QUALITY_RUBRIC, model=INVESTIGATOR_MODEL),
        HasMatchingSpan(query=SpanQuery(name_equals="investigator_stage")),
    ],
)


if __name__ == "__main__":
    report = dataset.evaluate_sync(partial(run_investigator, siblings=[]))

    # The default report.print(include_output=True) blows up here -- each
    # case's trajectory can carry dozens of URLs, which drowns the actual
    # pass/fail scores in terminal output. Keep the table compact (scores/
    # assertions are always included regardless of include_output) and
    # persist the full per-case detail to JSON separately, so a real
    # inspection never depends on re-running (real money) a second time.
    report.print(include_input=False, include_output=False, include_durations=True)

    summary = [
        {
            "case": c.name,
            "verdict": c.output.verdict.value,
            "confidence": c.output.confidence,
            "assertions": {k: v.value for k, v in c.assertions.items()},
            "scores": {k: v.value for k, v in c.scores.items()},
            "search_queries": c.output.trajectory.search_queries,
            "distinct_domains": c.output.trajectory.distinct_domains,
            "evidence_count": len(c.output.evidence),
            "dropped_evidence": c.output.dropped_evidence,
            "cost": c.metrics.get("cost"),
        }
        for c in report.cases
    ]
    out_path = "evals/investigator_last_run.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nPer-case summary written to {out_path}")
    for row in summary:
        print(
            f"  {row['case']}: verdict={row['verdict']} confidence={row['confidence']:.2f} "
            f"queries={len(row['search_queries'])} domains={len(row['distinct_domains'])} "
            f"assertions={row['assertions']} cost=${row['cost']:.3f}"
        )
