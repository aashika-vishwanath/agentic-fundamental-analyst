from agentic_fundamental_analyst.agents.numeric_grounding import (
    expand_known_numbers,
    extract_numbers,
    is_grounded,
    summary_is_grounded,
)


def test_extract_numbers_ignores_year_tokens():
    numbers = extract_numbers("In 2024, the P/E was 22.4 versus a peer median of 18.1.")
    assert numbers == [22.4, 18.1]


def test_extract_numbers_empty_for_purely_qualitative_text():
    assert extract_numbers("Broadly in line with sector peers, no notable divergence.") == []


def test_extract_numbers_ignores_maturity_labels_glued_to_a_letter():
    # "10Y"/"2Y" are FRED-series-style Treasury-maturity labels, not numbers
    # to ground — found live during Phase 4 implementation (see
    # numeric_grounding.py's _NUMBER_RE docstring).
    numbers = extract_numbers("The 10Y yield sits at 4.2% with the 2Y at 3.9%.")
    assert numbers == [4.2, 3.9]


def test_extract_numbers_ignores_hyphenated_maturity_labels():
    # "10-year"/"5-year" — the more idiomatic phrasing the model actually
    # used in live eval validation — found live during Phase 4 eval
    # validation (see numeric_grounding.py's _NUMBER_RE docstring).
    numbers = extract_numbers("The 10-year Treasury yield has risen to 4.2%.")
    assert numbers == [4.2]


def test_extract_numbers_handles_comma_thousands_separators():
    # "$1,981.7" must parse as one number (1981.7), not split at the comma
    # into "1" and "981.7" — found live during Phase 4 eval validation (see
    # numeric_grounding.py's _NUMBER_RE docstring).
    numbers = extract_numbers("The base case present value is $1,981.7.")
    assert numbers == [1981.7]


def test_extract_numbers_strips_iso_dates_entirely():
    # "2026-08-17" must not be split into "2026" (a real year, filtered) plus
    # "-08" and "-17" (parsed as -8.0/-17.0, not filterable as years) — found
    # live during Phase 4 eval validation (see numeric_grounding.py's
    # _NUMBER_RE docstring).
    numbers = extract_numbers("As of 2026-08-17, the rate was 4.2%.")
    assert numbers == [4.2]


def test_extract_numbers_does_not_treat_a_comma_grouped_number_as_a_year():
    # "$1,982" happens to fall in the 1900-2099 range but is never a bare
    # calendar-year mention (years are never comma-formatted) — found live
    # during Phase 4 eval validation (see numeric_grounding.py's _YEAR_RE
    # comment).
    numbers = extract_numbers("A present-value span of $1,315 to $1,982.")
    assert numbers == [1315.0, 1982.0]


def test_extract_numbers_still_filters_a_bare_plain_year():
    numbers = extract_numbers("In 2024, revenue grew 12%.")
    assert numbers == [12.0]


def test_extract_numbers_splits_a_hyphenated_range_into_two_positive_endpoints():
    # "3.99%-4.02%" is a range (no spaces around the hyphen) — the second
    # endpoint must extract as +4.02, not -4.02 (a hyphen glued directly
    # after a digit/percent is a range separator, not a minus sign). Found
    # live during Phase 4 eval validation (see numeric_grounding.py's
    # _NUMBER_RE docstring).
    numbers = extract_numbers("The yield held near 4.0% (3.99%-4.02%), stable.")
    assert numbers == [4.0, 3.99, 4.02]


def test_extract_numbers_still_extracts_a_genuine_negative_number():
    numbers = extract_numbers("A negative growth of -3.5 percent was recorded.")
    assert numbers == [-3.5]


def test_is_grounded_real_value_within_tolerance():
    assert is_grounded(22.4, {22.4})
    assert is_grounded(22.41, {22.4})  # within the 1% tolerance
    assert not is_grounded(50.0, {22.4})


def test_expand_known_numbers_includes_pairwise_percent_difference_and_ratio():
    known = expand_known_numbers({22.4, 18.1})
    # (22.4 - 18.1) / 18.1 * 100 ~= 23.76
    assert any(abs(k - 23.76) < 0.01 for k in known)
    # 22.4 / 18.1 ~= 1.2376
    assert any(abs(k - 1.2376) < 0.001 for k in known)


def test_summary_is_grounded_true_for_real_and_derived_numbers():
    known = {22.4, 18.1}
    summary = "The target's P/E of 22.4 sits about 24% above the peer median of 18.1."
    assert summary_is_grounded(summary, known)


def test_expand_known_numbers_includes_positive_percent_discount_regardless_of_pair_order():
    # A "15 vs 8" pair narrated as "a 47% discount" (roughly (15-8)/15*100)
    # must ground as a positive percentage regardless of which direction
    # combinations() happens to compute the signed difference in — found
    # live during Phase 4 eval validation (see numeric_grounding.py's
    # expand_known_numbers docstring).
    known = expand_known_numbers({15.0, 8.0})
    assert any(abs(k - 46.67) < 0.01 for k in known)


def test_summary_is_grounded_false_for_fabricated_number():
    known = {22.4, 18.1}
    summary = "The target trades at a P/E of 45.0, well above peers."
    assert not summary_is_grounded(summary, known)


def test_summary_is_grounded_vacuously_true_for_purely_qualitative_text():
    assert summary_is_grounded("Broadly in line with sector peers.", {22.4, 18.1})
