"""The Filings Analyst — interprets 10-K prose (Item 1, 1A, 7, 9A) and 8-K
item bodies, raising Flags for earnings-quality checklist items #8, 9, 11,
12, 13, 14, 15 (investment-memo-writing skill §2). See
.agents/plans/phase-2-filings-transcript-consolidator.md for full design
rationale, including the two checklist items only partially covered here.

Grounding is verbatim-quote-based, not table-lookup-based (Phase 1's trick
needs a closed numeric table; filing prose has none): the agent's own output
type (FilingFlagCandidate) carries a `quoted_evidence` span instead of a
value. Deterministic code checks that span is a real substring of the exact
section it claims before promoting it to a Flag with a SourcedQuote — any
candidate that doesn't verify is dropped, never trusted.
"""

import logfire
from pydantic_ai import Agent

from agentic_fundamental_analyst import config, observability  # noqa: F401
from agentic_fundamental_analyst.agents.grounding import quote_is_grounded
from agentic_fundamental_analyst.agents.models import FILINGS_ANALYST_MODEL
from agentic_fundamental_analyst.contracts.filings import FilingSections
from agentic_fundamental_analyst.contracts.filings_analyst import (
    FilingFlagCandidate,
    FilingsAnalystAgentOutput,
    FilingsAnalystOutput,
)
from agentic_fundamental_analyst.contracts.flags import Flag
from agentic_fundamental_analyst.contracts.sourcing import SourcedQuote

_INSTRUCTIONS = """\
You are the Filings Analyst for a fundamental-equity research system. You
receive a FilingSections bundle: the latest 10-K's Item 1 (Business), Item 1A
(Risk Factors), Item 7 (MD&A), and Item 9A (Controls and Procedures), plus
item bodies merged from several recent 8-Ks (auditor changes, officer
departures, restatements, earnings releases, etc.), each keyed by 8-K item
number (e.g. "4.01", "5.02"). Any section that is null was not found in the
filing -- never treat a null section as evidence of anything, and never
invent content for it.

Task:
1. Write a 2-4 sentence `summary` of what the filings actually disclose --
   specific to this company's real language, not generic commentary.
2. Raise a flag candidate only when the text genuinely supports one of these
   seven checklist signals:
   - non_gaap_gap_widening: a GAAP-vs-non-GAAP reconciliation (typically in an
     8-K press-release exhibit) shows a large, growing, recurring gap.
   - recurring_one_time_items: MD&A describes a restructuring/impairment/
     "special charge" that has now recurred across multiple consecutive
     periods -- you only have this single filing's own narrative, so only
     flag this when the filing's own text explicitly describes the item as
     recurring (e.g. "for the third consecutive year") -- do not infer
     recurrence you cannot see stated.
   - auditor_change: Item 4.01 in the 8-K item bodies describes a dismissal
     or resignation of the auditor.
   - officer_turnover: Item 5.02 describes an unexpected CFO/Controller/CEO
     departure.
   - material_weakness: Item 9A (or an 8-K) discloses a material weakness in
     internal controls.
   - going_concern_language: Item 7 or Item 1A contains explicit
     substantial-doubt-about-going-concern language. Note: the formal audit
     opinion (typically Item 8) is not in your input at all -- only flag
     this if the going-concern language appears in the sections you do have.
   - restatement: Item 4.02 states prior financials should no longer be
     relied upon.
3. Every flag candidate MUST carry `quoted_evidence`: the exact, verbatim
   text (copied character-for-character from the input, not paraphrased)
   that supports the flag, and the exact `section` it was quoted from (use
   `"eightk_item_body"` plus the matching `eightk_item_number` for an 8-K
   item; otherwise the input's own section field name). A quote that isn't a
   real, verbatim excerpt will be discarded, so never paraphrase or
   summarize what you quote.
4. Raising zero flags is a valid, expected outcome for a clean filing -- do
   not manufacture a flag to seem thorough. Ordinary risk-factor boilerplate
   or a routine earnings release is not evidence of anything on its own.
"""

filings_analyst = Agent(
    FILINGS_ANALYST_MODEL,
    name="filings_analyst",
    output_type=FilingsAnalystAgentOutput,
    instructions=_INSTRUCTIONS,
)


def _fiscal_label(
    candidate: FilingFlagCandidate, sections: FilingSections
) -> tuple[int, str] | None:
    if candidate.section == "eightk_item_body":
        item_source = sections.eightk_item_sources.get(candidate.eightk_item_number or "")
        return (item_source.filed_date.year, "8K") if item_source else None
    ref_date = sections.period_of_report or sections.filed_date
    return (ref_date.year, "FY") if ref_date is not None else None


def _as_of_date(candidate: FilingFlagCandidate, sections: FilingSections):
    if candidate.section == "eightk_item_body":
        item_source = sections.eightk_item_sources.get(candidate.eightk_item_number or "")
        return item_source.filed_date if item_source else None
    return sections.period_of_report or sections.filed_date


def _section_text(candidate: FilingFlagCandidate, sections: FilingSections) -> str | None:
    if candidate.section == "eightk_item_body":
        return sections.eightk_item_bodies.get(candidate.eightk_item_number or "")
    return getattr(sections, candidate.section)


def _ground_filing_candidates(
    sections: FilingSections, candidates: list[FilingFlagCandidate]
) -> tuple[list[Flag], list[str]]:
    flags: list[Flag] = []
    dropped: list[str] = []
    for c in candidates:
        source_text = _section_text(c, sections)
        fiscal_label = _fiscal_label(c, sections)
        as_of = _as_of_date(c, sections)
        quoted_ok = quote_is_grounded(c.quoted_evidence, source_text)
        if fiscal_label is None or as_of is None or not quoted_ok:
            dropped.append(f"{c.metric} ({c.section}): quote not verified verbatim")
            continue
        fiscal_year, fiscal_period = fiscal_label
        item_suffix = (
            f":8K:{c.eightk_item_number}" if c.section == "eightk_item_body" else f":{c.section}"
        )
        flags.append(
            Flag(
                metric=c.metric,
                fiscal_year=fiscal_year,
                fiscal_period=fiscal_period,
                severity=c.severity,
                description=c.description,
                source=SourcedQuote(
                    text=c.quoted_evidence,
                    source=f"EDGAR:{sections.accession_number}{item_suffix}",
                    as_of=as_of,
                ),
            )
        )
    return flags, dropped


async def run_filings_analyst(ticker: str, sections: FilingSections) -> FilingsAnalystOutput:
    # FilingSections carries no ticker field (it's keyed by accession_number,
    # which is filer- not ticker-scoped) — the caller supplies it, same
    # pattern as run_transcript_analyst(ticker, transcript).
    with logfire.span(
        "filings_analyst_stage", ticker=ticker, accession_number=sections.accession_number
    ) as span:
        result = await filings_analyst.run(sections.model_dump_json(indent=2))
        agent_output = result.output
        flags, dropped = _ground_filing_candidates(sections, agent_output.flag_candidates)
        span.set_attribute("flag_count", len(flags))
        span.set_attribute("dropped_candidate_count", len(dropped))
    return FilingsAnalystOutput(
        ticker=ticker,
        summary=agent_output.summary,
        flags=flags,
        coverage_gaps=sections.coverage_gaps,
        dropped_candidates=dropped,
    )
