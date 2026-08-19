from datetime import date

from pydantic_ai.models.test import TestModel

from agentic_fundamental_analyst.agents.filings import filings_analyst, run_filings_analyst
from agentic_fundamental_analyst.contracts.filings import EightKItemSource, FilingSections
from agentic_fundamental_analyst.contracts.filings_analyst import FilingsAnalystAgentOutput
from agentic_fundamental_analyst.contracts.sourcing import SourcedQuote

SECTIONS = FilingSections(
    accession_number="0001-24-000001",
    filed_date=date(2024, 2, 20),
    period_of_report=date(2023, 12, 31),
    item_1_business="We sell widgets across North America.",
    item_1a_risk_factors="Our business is subject to ordinary competitive risk factors.",
    item_7_mdna="Revenue grew 8% year over year, driven by widget demand.",
    item_9a_controls="Our disclosure controls and procedures were effective.",
    eightk_item_bodies={
        "4.01": "On February 1, 2024, the Audit Committee dismissed Example LLP as the "
        "Company's independent registered public accounting firm.",
        "9.01": "Financial statements and exhibits.",
    },
    eightk_item_sources={
        "4.01": EightKItemSource(accession_number="0001-24-000002", filed_date=date(2024, 2, 1)),
        "9.01": EightKItemSource(accession_number="0001-24-000002", filed_date=date(2024, 2, 1)),
    },
    coverage_gaps=[],
)


def test_agent_default_test_model_produces_valid_output_type():
    with filings_analyst.override(model=TestModel()):
        result = filings_analyst.run_sync(SECTIONS.model_dump_json())
    assert isinstance(result.output, FilingsAnalystAgentOutput)


async def test_run_filings_analyst_grounds_real_quote_and_drops_fabricated_one():
    scripted_output = {
        "summary": "The company dismissed its auditor and disclosed ordinary risks.",
        "flag_candidates": [
            {
                # Real: this exact sentence is in eightk_item_bodies["4.01"].
                "metric": "auditor_change",
                "section": "eightk_item_body",
                "eightk_item_number": "4.01",
                "quoted_evidence": (
                    "the Audit Committee dismissed Example LLP as the Company's "
                    "independent registered public accounting firm."
                ),
                "severity": "high",
                "description": "Auditor dismissed.",
            },
            {
                # Fake: this sentence does not appear anywhere in the input.
                "metric": "going_concern_language",
                "section": "item_7_mdna",
                "quoted_evidence": "substantial doubt about our ability to continue as a "
                "going concern",
                "severity": "high",
                "description": "Hallucinated quote.",
            },
        ],
    }
    with filings_analyst.override(model=TestModel(custom_output_args=scripted_output)):
        result = await run_filings_analyst("TEST", SECTIONS)

    assert len(result.flags) == 1
    real_flag = result.flags[0]
    assert real_flag.metric == "auditor_change"
    assert real_flag.fiscal_year == 2024
    assert real_flag.fiscal_period == "8K"
    assert isinstance(real_flag.source, SourcedQuote)
    assert real_flag.source.text.startswith("the Audit Committee dismissed")
    assert real_flag.source.source == "EDGAR:0001-24-000001:8K:4.01"
    assert real_flag.source.as_of == date(2024, 2, 1)

    assert len(result.dropped_candidates) == 1
    assert "going_concern_language" in result.dropped_candidates[0]


async def test_run_filings_analyst_drops_quote_claimed_from_wrong_section():
    """A real, verbatim quote from item_1a_risk_factors claimed under
    item_7_mdna must not be grounded against a different field than it
    actually names."""
    scripted_output = {
        "summary": "s",
        "flag_candidates": [
            {
                "metric": "recurring_one_time_items",
                "section": "item_7_mdna",  # wrong: this text is really in item_1a_risk_factors
                "quoted_evidence": "ordinary competitive risk factors",
                "severity": "low",
                "description": "d",
            }
        ],
    }
    with filings_analyst.override(model=TestModel(custom_output_args=scripted_output)):
        result = await run_filings_analyst("TEST", SECTIONS)

    assert result.flags == []
    assert len(result.dropped_candidates) == 1


async def test_run_filings_analyst_passes_through_coverage_gaps_from_input():
    from agentic_fundamental_analyst.contracts.financials import CoverageGap

    sections = SECTIONS.model_copy(
        update={"coverage_gaps": [CoverageGap(field="item_9a_controls", reason="not_found")]}
    )
    scripted_output = {"summary": "s", "flag_candidates": []}
    with filings_analyst.override(model=TestModel(custom_output_args=scripted_output)):
        result = await run_filings_analyst("TEST", sections)
    assert result.coverage_gaps == sections.coverage_gaps
