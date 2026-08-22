"""Memo -> Markdown -> PDF rendering. Pure formatting/serialization of an
already-finalized Memo -- no interpretation, nothing left to decide once
Memo exists, so this is deterministic code, not an agent (same Agent-or-Code
reasoning as every other pure function in this codebase).

Deliberately NOT called from pipeline.py or any agent module -- rendering is
a separate, optional downstream concern (file I/O) from memo *generation*.
Keeping them apart means run_memo_pipeline()'s own unit/eval tests never
touch a filesystem or a PDF dependency, and a bug in PDF layout can never
affect whether a Memo itself is correct or grounded.

Added mid-Phase-5 at the user's explicit request -- PRD §3's "Final Artifact
Specification" is the typed Memo object, not a rendered document; this module
is a genuinely new kind of dependency for this codebase (a document-rendering
library, not an API-client/data/agent library). markdown + xhtml2pdf chosen
over weasyprint for zero system-library dependencies (no Cairo/Pango) --
pure-Python, installs anywhere this project's own free/zero-marginal-cost
principle (PRD §1) already assumes.
"""

from pathlib import Path
from typing import Any

import markdown as markdown_lib
from xhtml2pdf import pisa

from agentic_fundamental_analyst.contracts.memo import MEMO_SECTION_DISPLAY_NAMES, Memo


def render_memo_to_markdown(memo: Memo) -> str:
    lines: list[str] = [
        f"# {memo.ticker} — Investment Memo",
        "",
        f"**Rating:** {memo.rating.value.upper()}  ",
        f"**Conviction:** {memo.conviction.value.title()}  ",
        f"**Generated:** {memo.generated_at.isoformat()}",
        "",
    ]

    for section in memo.sections:
        display_name = MEMO_SECTION_DISPLAY_NAMES[section.title]
        lines.append(f"## {display_name}")
        lines.append("")
        lines.append(section.content)
        lines.append("")

    # Mechanically-generated full sourcing table -- built from real typed
    # data (every section's cited_figures/cited_quotes), not trusting the
    # model's own Appendix section prose alone. This is Section 10's "literal
    # traceability table" made real.
    lines.append("## Sourcing Table")
    lines.append("")
    any_citation = False
    for section in memo.sections:
        display_name = MEMO_SECTION_DISPLAY_NAMES[section.title]
        for fig in section.cited_figures:
            any_citation = True
            lines.append(
                f"- **{display_name}** — {fig.value} "
                f"(source: `{fig.source}`, as of {fig.as_of.isoformat()})"
            )
        for quote in section.cited_quotes:
            any_citation = True
            lines.append(
                f'- **{display_name}** — "{quote.text}" '
                f"(source: `{quote.source}`, as of {quote.as_of.isoformat()})"
            )
    if not any_citation:
        lines.append("_No cited figures or quotes were recorded for this memo._")
    lines.append("")

    if memo.coverage_gaps:
        lines.append("## Coverage Gaps")
        lines.append("")
        for gap in memo.coverage_gaps:
            lines.append(f"- **{gap.field}**: {gap.reason}")
        lines.append("")

    return "\n".join(lines)


def render_memo_to_pdf(memo: Memo, output_path: str | Path) -> None:
    md = render_memo_to_markdown(memo)
    html = markdown_lib.markdown(md, extensions=["tables"])
    output = Path(output_path)
    with output.open("wb") as f:
        # xhtml2pdf's bundled type stub claims CreatePDF returns bytes; at
        # runtime (confirmed against installed xhtml2pdf 0.2.17) it returns a
        # pisaContext with a real .err attribute -- the stub is wrong, not
        # this code, hence the Any cast rather than chasing the stub.
        result: Any = pisa.CreatePDF(html, dest=f)
    if result.err:
        raise RuntimeError(f"xhtml2pdf reported {result.err} error(s) rendering {output_path}")
