from datetime import date

from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    NativeToolCallPart,
    NativeToolReturnPart,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import UsageLimits

import agentic_fundamental_analyst.agents.investigator as investigator_module
from agentic_fundamental_analyst.agents.investigator import (
    investigator,
    run_investigations,
    run_investigator,
)
from agentic_fundamental_analyst.contracts.consolidation import ConsolidatedFlag
from agentic_fundamental_analyst.contracts.flags import Flag, Severity
from agentic_fundamental_analyst.contracts.investigation import (
    InvestigatorAgentOutput,
    SiblingFlagSummary,
)
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
    return ConsolidatedFlag(
        flags=[_flag(metric, fiscal_year, severity, description)], summary=description
    )


CAPEX_FLAG = _consolidated(
    "capex_to_depreciation_ratio", 2024, Severity.HIGH, "Capex/D&A jumped to 4.3x, AI buildout."
)


def test_agent_default_test_model_produces_valid_output_type():
    with investigator.override(model=TestModel(), native_tools=[]):
        result = investigator.run_sync("investigate")
    assert isinstance(result.output, InvestigatorAgentOutput)


def _single_search_then_output(output_args: dict, real_url: str = "https://real.example.com/story"):
    """A FunctionModel callback scripting: one native web_search call+return
    (single result, single domain -- deliberately thin, to also exercise the
    multi-angle downgrade), then a final structured-output tool call."""
    call_count = 0

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ModelResponse(
                parts=[
                    NativeToolCallPart(
                        tool_name="web_search",
                        args={"query": "why did capex spike"},
                        tool_call_id="c1",
                    ),
                    NativeToolReturnPart(
                        tool_name="web_search",
                        content=[
                            {"type": "web_search_result", "url": real_url, "title": "Real story"}
                        ],
                        tool_call_id="c1",
                    ),
                ]
            )
        return ModelResponse(
            parts=[ToolCallPart(tool_name="final_result", args=output_args, tool_call_id="f1")]
        )

    return fn


async def test_run_investigator_drops_fabricated_url_and_keeps_grounded_one():
    real_url = "https://real.example.com/story"
    fabricated_url = "https://totally-fabricated.example/nonexistent"
    output_args = {
        "hypothesis": "AI buildout",
        "verdict": "concerning",
        "confidence": 0.9,
        "reasoning": "weighed evidence",
        "evidence": [
            {"url": real_url, "claim": "confirmed by reporting", "stance": "supports_concerning"},
            {"url": fabricated_url, "claim": "made up", "stance": "supports_concerning"},
        ],
        "correlated_sibling_indices": [],
    }
    fn = _single_search_then_output(output_args, real_url=real_url)
    with investigator.override(model=FunctionModel(fn), native_tools=[]):
        verdict = await run_investigator(CAPEX_FLAG, siblings=[])

    grounded_urls = {e.url for e in verdict.evidence}
    assert grounded_urls == {real_url}
    assert verdict.dropped_evidence == [fabricated_url]


async def test_run_investigator_forces_unresolved_on_thin_single_domain_evidence():
    real_url = "https://real.example.com/story"
    output_args = {
        "hypothesis": "AI buildout",
        "verdict": "concerning",
        "confidence": 0.9,
        "reasoning": "one source only",
        "evidence": [
            {"url": real_url, "claim": "confirmed by reporting", "stance": "supports_concerning"}
        ],
        "correlated_sibling_indices": [],
    }
    fn = _single_search_then_output(output_args, real_url=real_url)
    with investigator.override(model=FunctionModel(fn), native_tools=[]):
        verdict = await run_investigator(CAPEX_FLAG, siblings=[])

    assert verdict.verdict.value == "unresolved"
    assert verdict.confidence <= 0.5
    assert len(verdict.coverage_gaps) == 1
    assert "distinct domain" in verdict.coverage_gaps[0].reason


def _noisy_search_then_output(output_args: dict, cited_url: str):
    """A FunctionModel callback scripting one native web_search call+return
    with results from SEVEN different domains (raw search-result noise, the
    kind any real search returns regardless of investigation quality), then
    a final structured-output tool call that cites only `cited_url` as
    evidence. Regression case for the bug caught during live eval
    validation: the multi-angle/confidence rules must key off the domain
    diversity of CITED evidence, never raw trajectory.distinct_domains --
    see agents/investigator.py's module docstring and
    .agents/plans/phase-3-investigator.md Notes."""
    call_count = 0
    noisy_domains = [
        "seo-spam-1.example",
        "seo-spam-2.example",
        "unrelated-blog.example",
        "aggregator-site.example",
        "irrelevant-forum.example",
        "stock-screener-noise.example",
        "one-real-source.example",
    ]

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ModelResponse(
                parts=[
                    NativeToolCallPart(
                        tool_name="web_search", args={"query": "flag topic"}, tool_call_id="c1"
                    ),
                    NativeToolReturnPart(
                        tool_name="web_search",
                        content=[
                            {"type": "web_search_result", "url": f"https://{d}/x", "title": d}
                            for d in noisy_domains
                        ],
                        tool_call_id="c1",
                    ),
                ]
            )
        return ModelResponse(
            parts=[ToolCallPart(tool_name="final_result", args=output_args, tool_call_id="f1")]
        )

    return fn, cited_url


async def test_run_investigator_forces_unresolved_despite_many_raw_search_domains():
    cited_url = "https://one-real-source.example/x"
    output_args = {
        "hypothesis": "AI buildout",
        "verdict": "concerning",
        "confidence": 0.9,
        "reasoning": "cited one source despite many raw search hits",
        "evidence": [
            {"url": cited_url, "claim": "confirmed by reporting", "stance": "supports_concerning"}
        ],
        "correlated_sibling_indices": [],
    }
    fn, _ = _noisy_search_then_output(output_args, cited_url)
    with investigator.override(model=FunctionModel(fn), native_tools=[]):
        verdict = await run_investigator(CAPEX_FLAG, siblings=[])

    # Raw search noise spans 7 domains, but only one was actually cited as
    # evidence -- the rule must still force unresolved on the real signal.
    assert len(verdict.trajectory.distinct_domains) == 7
    assert verdict.verdict.value == "unresolved"
    assert verdict.confidence <= 0.5
    assert len(verdict.coverage_gaps) == 1
    assert "distinct domain" in verdict.coverage_gaps[0].reason


async def test_run_investigator_filters_out_of_range_correlated_sibling_indices():
    real_url = "https://real.example.com/story"
    output_args = {
        "hypothesis": "AI buildout",
        "verdict": "unresolved",
        "confidence": 0.3,
        "reasoning": "n/a",
        "evidence": [],
        "correlated_sibling_indices": [0, 99, -1],
    }
    fn = _single_search_then_output(output_args, real_url=real_url)
    siblings = [
        SiblingFlagSummary(
            metric="officer_turnover",
            fiscal_year=2024,
            fiscal_period="FY",
            description="CFO departed",
        )
    ]
    with investigator.override(model=FunctionModel(fn), native_tools=[]):
        verdict = await run_investigator(CAPEX_FLAG, siblings=siblings)
    assert verdict.correlated_sibling_indices == [0]


async def test_run_investigator_degrades_gracefully_when_usage_budget_exceeded(monkeypatch):
    """A single flag exceeding its usage/cost budget must degrade to an
    unresolved verdict with a CoverageGap, not propagate an exception --
    caught live during eval validation, where an UsageLimitExceeded on one
    case would otherwise have crashed the whole asyncio.gather batch in
    run_investigations, losing every other flag's completed investigation
    too. request_limit=1 forces the real UsageLimitExceeded path (not
    mocked) since _single_search_then_output always needs 2 requests."""
    monkeypatch.setattr(
        investigator_module, "_INVESTIGATOR_USAGE_LIMITS", UsageLimits(request_limit=1)
    )

    output_args = {
        "hypothesis": "h",
        "verdict": "concerning",
        "confidence": 0.9,
        "reasoning": "n/a",
        "evidence": [],
        "correlated_sibling_indices": [],
    }
    fn = _single_search_then_output(output_args)
    with investigator.override(model=FunctionModel(fn), native_tools=[]):
        verdict = await run_investigator(CAPEX_FLAG, siblings=[])

    assert verdict.verdict.value == "unresolved"
    assert verdict.confidence == 0.0
    assert verdict.evidence == []
    assert len(verdict.coverage_gaps) == 1
    assert "budget" in verdict.coverage_gaps[0].reason


async def test_run_investigations_empty_input_yields_empty_output_without_calling_model():
    verdicts, gaps = await run_investigations([])
    assert verdicts == []
    assert gaps == []


async def test_run_investigations_skips_below_budget_with_explicit_coverage_gaps():
    flags = [
        _consolidated("metric_a", 2024, Severity.HIGH, "high severity a"),
        _consolidated("metric_b", 2024, Severity.HIGH, "high severity b"),
        _consolidated("metric_c", 2024, Severity.LOW, "low severity c"),
    ]
    output_args = {
        "hypothesis": "h",
        "verdict": "unresolved",
        "confidence": 0.2,
        "reasoning": "n/a",
        "evidence": [],
        "correlated_sibling_indices": [],
    }
    fn = _single_search_then_output(output_args)
    with investigator.override(model=FunctionModel(fn), native_tools=[]):
        verdicts, gaps = await run_investigations(flags, max_investigations=2)

    assert len(verdicts) == 2
    assert len(gaps) == 1
    assert "metric_c" in gaps[0].field
    assert "budget" in gaps[0].reason
