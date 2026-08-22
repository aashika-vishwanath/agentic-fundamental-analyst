from datetime import UTC, date, datetime
from pathlib import Path

from agentic_fundamental_analyst.contracts.memo import (
    ConvictionTier,
    Memo,
    MemoSection,
    Rating,
)
from agentic_fundamental_analyst.contracts.sourcing import SourcedFigure, SourcedQuote
from agentic_fundamental_analyst.render import render_memo_to_markdown, render_memo_to_pdf

MEMO = Memo(
    ticker="TEST",
    rating=Rating.BUY,
    conviction=ConvictionTier.MEDIUM,
    generated_at=datetime(2026, 8, 19, tzinfo=UTC),
    sections=[
        MemoSection(
            title="executive_summary_and_recommendation",
            content="TEST trades at a discount to its trailing DCF value.",
            cited_figures=[
                SourcedFigure(value=224.0, source="prices.latest:TEST", as_of=date(2026, 8, 17))
            ],
        ),
        MemoSection(
            title="risks_and_mitigants",
            content="Disclosed litigation risk is company-specific, not boilerplate.",
            cited_figures=[],
            cited_quotes=[
                SourcedQuote(
                    text="The Company is party to ordinary litigation.",
                    source="EDGAR:CIK0000000000:10-K:item_1a",
                    as_of=date(2026, 2, 20),
                )
            ],
        ),
    ],
    coverage_gaps=[],
    investigations=[],
    resolutions=[],
)


def test_render_memo_to_markdown_includes_ticker_rating_and_section_content():
    md = render_memo_to_markdown(MEMO)
    assert "TEST" in md
    assert "BUY" in md
    assert "TEST trades at a discount to its trailing DCF value." in md
    assert "Disclosed litigation risk is company-specific, not boilerplate." in md


def test_render_memo_to_markdown_includes_every_cited_figure_and_quote_source():
    md = render_memo_to_markdown(MEMO)
    assert "prices.latest:TEST" in md
    assert "EDGAR:CIK0000000000:10-K:item_1a" in md


def test_render_memo_to_pdf_writes_a_real_pdf_file(tmp_path: Path):
    output = tmp_path / "memo.pdf"
    render_memo_to_pdf(MEMO, output)
    assert output.exists()
    assert output.read_bytes()[:4] == b"%PDF"
