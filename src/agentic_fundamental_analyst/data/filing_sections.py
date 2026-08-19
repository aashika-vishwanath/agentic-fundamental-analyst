"""Deterministic HTML/text parsing of 10-K and 8-K filing bodies into typed
sections. Pure parsing logic — no fetching, no interpretation of what the
text means (that's the Filings Analyst's job, Phase 2).

10-K heuristic (verified against real Alphabet and Apple 10-Ks during Phase
0 execution — their HTML conventions differ, this generalizes across both):
the Table of Contents lists every "Item N." as a hyperlink (`<a href="#...">`)
to the real section, which is itself rendered bold (`font-weight:700`, or a
`<b>`/`<strong>` tag) and is *not* inside a link. Matching only bold,
non-hyperlinked "Item N." text — first tried an ALL-CAPS-text heuristic,
which worked for Alphabet but silently found nothing for Apple, whose body
headers are mixed-case with CSS-driven visual capitalization — reliably
separates real section headers from both ToC entries and inline
cross-references ("see Item 1A Risk Factors...") for both filers. It is a
common convention, not a guaranteed one, and won't generalize to every
filer's HTML — a filer whose headers aren't bold-styled will show up as a
CoverageGap (item_header_not_found_in_10k_body), never a wrong section.
"""

import re
import warnings

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning
from bs4.element import NavigableString

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

_ITEM_10K_START_RE = re.compile(r"^item\s+(\d+[a-c]?)\.", re.IGNORECASE)
_ITEM_8K_RE = re.compile(r"\bItem\s+(\d+\.\d+)\.?\s*")
_ANCESTOR_SEARCH_DEPTH = 8

# Transcript-exhibit detection (Phase 2). Vendor-formatted earnings-call
# transcripts (the real-world convention for the rare 8-K exhibit that is
# one at all) put the speaker's name/role on its own line rather than a
# "Name:" prefix -- confirmed against a real captured transcript exhibit
# (tests/golden/overstock_8k_transcript_sample.html), which has 8 exact
# "Operator"-only lines and 0 "Name:"-style lines. An ordinary 8-K item body
# (press release, disclosure text) has zero standalone "Operator" lines.
_QA_MARKER_RE = re.compile(r"question[\s-]+and[\s-]+answer", re.IGNORECASE)
_MIN_OPERATOR_ONLY_LINES = 2


def _is_real_header(node: NavigableString) -> bool:
    """True if `node` sits in a bold element that isn't inside a hyperlink
    (i.e. a real section header, not a Table-of-Contents entry)."""
    ancestor = node.parent
    for _ in range(_ANCESTOR_SEARCH_DEPTH):
        if ancestor is None or not isinstance(ancestor, Tag):
            break
        if ancestor.name == "a":
            return False  # inside a link -> Table of Contents entry
        if ancestor.name in ("b", "strong"):
            return True
        style = ancestor.get("style", "")
        if isinstance(style, str):
            compact = style.replace(" ", "").lower()
            if "font-weight:bold" in compact or "font-weight:7" in compact:
                return True
        ancestor = ancestor.parent
    return False


def extract_10k_sections(html: str) -> dict[str, str | None]:
    """Returns item_1_business, item_1a_risk_factors, item_7_mdna — None for
    any section whose real (bold, non-hyperlinked) header wasn't found
    (caller records a CoverageGap, never an empty-string-as-if-found)."""
    soup = BeautifulSoup(html, "lxml")
    strings = [
        s
        for s in soup.find_all(string=True)
        if s.parent is not None and s.parent.name not in ("script", "style")
    ]

    full_text_parts: list[str] = []
    boundaries: list[tuple[int, str]] = []  # (offset, item_number)
    offset = 0
    for s in strings:
        text = str(s)
        stripped = text.strip()
        match = _ITEM_10K_START_RE.match(stripped) if stripped else None
        if match and _is_real_header(s):
            boundaries.append((offset, match.group(1).upper()))
        full_text_parts.append(text)
        offset += len(text)
        full_text_parts.append("\n")
        offset += 1
    full_text = "".join(full_text_parts)

    sections: dict[str, str] = {}
    for i, (start, item_number) in enumerate(boundaries):
        end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(full_text)
        if item_number not in sections:
            sections[item_number] = full_text[start:end].strip()

    return {
        "item_1_business": sections.get("1") or None,
        "item_1a_risk_factors": sections.get("1A") or None,
        "item_7_mdna": sections.get("7") or None,
        "item_9a_controls": sections.get("9A") or None,
    }


def extract_8k_item_bodies(html: str) -> dict[str, str]:
    """Item number (e.g. "8.01") -> extracted text, for every Item N.NN
    header found. 8-Ks have no Table of Contents to collide with, so plain
    text-boundary matching (no bold/hyperlink check) is sufficient. Empty
    dict if none found — never a fabricated entry."""
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text("\n")
    matches = list(_ITEM_8K_RE.finditer(text))
    bodies: dict[str, str] = {}
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        item_number = m.group(1)
        if item_number not in bodies:
            bodies[item_number] = text[start:end].strip()
    return bodies


def extract_plain_text(html: str) -> str:
    """Generic HTML -> newline-joined plain text, for documents with no
    Item N.NN structure to segment on (a transcript or press-release
    exhibit — a *separate* document within the accession, distinct from the
    primary 8-K's own Item N.NN cover text that extract_8k_item_bodies
    parses)."""
    soup = BeautifulSoup(html, "lxml")
    return soup.get_text("\n")


def looks_like_transcript_body(text: str) -> bool:
    """True if `text` looks like a real call-transcript exhibit rather than
    a press release or other 8-K exhibit. False negatives are safe (surfaces
    as a coverage gap, never a wrong answer); this is intentionally
    conservative against false positives, since those would hand the
    Transcript Analyst non-transcript text to interpret."""
    operator_only_lines = sum(1 for line in text.splitlines() if line.strip() == "Operator")
    has_qa_marker = bool(_QA_MARKER_RE.search(text))
    return operator_only_lines >= _MIN_OPERATOR_ONLY_LINES and has_qa_marker
