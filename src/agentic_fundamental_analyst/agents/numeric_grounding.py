"""Numeric-value grounding — shared by the Sector, Macro Sensitivity, and
Valuation Interpreter agents (Phase 4). The fourth grounding mechanism in
this codebase, after closed-table lookup (Phase 1), verbatim-quote checking
(Phase 2), and URL provenance (Phase 3) — none of those apply here because
these three agents produce no Flags to promote-or-drop against a closed
table or a quote. They narrate small, fully-typed numeric bundles (peer
multiples, macro series values, DCF scenario present values) directly into
free text, so the agent's own output_type IS the final output — there is no
separate candidate to verify before promotion.

Grounding here means: every number appearing in a `summary` must be
traceable, within tolerance, to a real number in the typed input, or a
simple derived transform of two such numbers (a percent difference or
ratio — the natural vocabulary of a *comparative* narrative, e.g. "trades
at a 22% discount to peer median P/E"). This generalizes the informational-
only numeric-grounding idiom first prototyped in
evals/financial_statements.py's _summary_numeric_grounding_ratio, promoted
here to a real, hard runtime gate — each agent's run_X() function calls
summary_is_grounded() and replaces an ungrounded summary with a fixed
fallback rather than shipping unverified prose (see agents/sector.py et
al.)."""

import re
from itertools import combinations

# ISO dates (risk_free_rate_as_of, filing dates, etc. commonly get cited
# verbatim, e.g. "as of 2026-08-17") are stripped before number extraction
# entirely, rather than left to fall through the main pattern — a plain
# digit-run pattern applied to "2026-08-17" splits it into "2026" (a real
# year, filtered below) plus "-08" and "-17" (parsed as the negative numbers
# -8.0 and -17.0, neither filterable as a year) — found live during Phase 4
# eval validation (evals/valuation_interpreter.py, which cites this field).
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

# Two alternatives, tried in order: a comma-thousands-grouped number first
# (e.g. "$1,981.7" as one token, not "1" + "981.7" — a plain \d+ pattern
# stops at the comma and silently mis-splits any number in the thousands or
# above, which is routine for real dollar figures; found live during Phase 4
# eval validation, evals/valuation_interpreter.py's DCF present values), then
# a plain number. Both alternatives share the same guards: (?<![a-zA-Z]) /
# (?!...) exclude a digit run glued directly to a letter on either side —
# "10Y"/"2Y"/"T10Y2Y" (Treasury-maturity labels, this codebase's own FRED
# series IDs) parse as a label, not a number to ground; (?!-[a-zA-Z])
# additionally excludes a digit run followed by a hyphenated word —
# "10-year"/"5-year" (the more idiomatic phrasing the model actually reached
# for in live eval validation, over "10Y") — same category, just with a
# hyphen separator. Both found live: "The 10-year Treasury yield..." was
# extracting a spurious, ungroundable "10" and failing the whole summary —
# see the Phase 4 plan's Execution Deviations. (?>...) atomic groups (not
# possessive-quantifier-per-piece — that syntax doesn't compose across a
# `?` group in Python's re) prevent backtracking into a shorter digit run
# ("1" out of "10") to satisfy the trailing lookahead once the full run
# fails it, which would silently reintroduce the same bug in a subtler form
# — also found live. Side effect, accepted as reasonable: a token like
# "0.8x" (a multiple, not a standalone quantity) is also excluded, since "x"
# is a letter suffix.
# The leading `(?:(?<![0-9%])-)?` (replacing a plain `-?`) treats a hyphen as
# a genuine minus sign only when it is NOT immediately preceded by a digit or
# "%" — a range written as "3.99%-4.02%" or "$1,315-$1,982" (a plain ASCII
# hyphen directly between two values, the model's own idiomatic phrasing for
# a range, no spaces) would otherwise have its second endpoint misparsed as a
# negative number ("-4.02" instead of the real, positive "4.02"), which then
# fails to ground against the real +4.02 in the known set. Found live during
# Phase 4 eval validation (evals/macro_analyst.py's flat_stable_regime case:
# "held near 4.0% (3.99%-4.02%)"). A genuine negative number is always
# preceded by whitespace/punctuation/start-of-string in practice, never
# glued directly to a preceding digit or "%", so this doesn't lose real
# negative-number extraction.
_NUMBER_RE = re.compile(
    r"(?<![a-zA-Z0-9,])(?:(?<![0-9%])-)?"
    r"(?>\d{1,3}(?:,\d{3})+(?:\.\d+)?)(?![a-zA-Z])(?!-[a-zA-Z])"
    r"|"
    r"(?<![a-zA-Z])(?:(?<![0-9%])-)?(?>\d+\.?\d*)(?![a-zA-Z])(?!-[a-zA-Z])"
)
# Applied only to non-comma-grouped tokens — a genuinely comma-formatted
# number (e.g. "1,982") is never a bare calendar-year mention, so it must
# never be filtered as one even when it happens to fall in the 1900-2099
# range (a real DCF present value or dollar figure landing in that numeric
# range purely by coincidence is exactly what happened live in eval
# validation — see the Phase 4 plan's Execution Deviations).
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")


def extract_numbers(text: str) -> list[float]:
    text = _DATE_RE.sub(" ", text)
    numbers = []
    for match in _NUMBER_RE.finditer(text):
        raw = match.group()
        has_comma = "," in raw
        token = raw.replace(",", "")
        if not has_comma and _YEAR_RE.match(token):
            continue
        try:
            numbers.append(float(token))
        except ValueError:
            continue
    return numbers


def expand_known_numbers(raw: set[float]) -> set[float]:
    """Raw values plus percent/rounded transforms (same tolerance idiom
    already prototyped in evals/financial_statements.py's _known_numbers)
    plus pairwise percent-differences and ratios between every pair of raw
    values — the natural vocabulary of a relative/comparative narrative.

    abs() variants of every percent-difference are included alongside the
    signed ones: combinations() yields each pair in one arbitrary order, so
    without abs() a "47% discount" narrated as a plain positive number could
    fail to match if the only generated transform for that pair happened to
    land as -46.67 rather than +46.67 — found live during Phase 4 eval
    validation (evals/sector_analyst.py's discount_to_peer_median case)."""
    known: set[float] = set()
    for v in raw:
        known.update({round(v, 4), round(v * 100, 4), round(v), round(v * 100)})
    for a, b in combinations(raw, 2):
        if b:
            pct = (a - b) / b * 100
            known.add(round(pct, 4))
            known.add(round(abs(pct), 4))
            known.add(round(a / b, 4))
        if a:
            pct2 = (b - a) / a * 100
            known.add(round(pct2, 4))
            known.add(round(abs(pct2), 4))
            known.add(round(b / a, 4))
    return known | raw


def is_grounded(x: float, known: set[float]) -> bool:
    tolerance = max(0.5, 0.01 * abs(x))
    return any(abs(x - k) <= tolerance for k in known)


def summary_is_grounded(summary: str, known_raw: set[float]) -> bool:
    """Hard gate — every number in `summary` must be grounded. An empty
    number list is vacuously grounded (a purely qualitative summary is a
    valid output, same as raising zero flags is valid in Phases 1-2)."""
    numbers = extract_numbers(summary)
    if not numbers:
        return True
    known = expand_known_numbers(known_raw)
    return all(is_grounded(x, known) for x in numbers)
