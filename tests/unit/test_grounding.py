from agentic_fundamental_analyst.agents.grounding import normalize_whitespace, quote_is_grounded


def test_normalize_whitespace_collapses_runs_and_strips():
    assert normalize_whitespace("  a\n\nb\t c  ") == "a b c"


def test_quote_is_grounded_exact_match():
    text = "we identified a material weakness"
    assert quote_is_grounded(text, text)


def test_quote_is_grounded_tolerates_whitespace_differences():
    source = "we\n identified   a material\tweakness in our controls"
    assert quote_is_grounded("we identified a material weakness", source)


def test_quote_is_grounded_false_for_absent_quote():
    assert not quote_is_grounded("we identified a material weakness", "everything was fine")


def test_quote_is_grounded_false_for_paraphrase():
    source = "management identified a significant control deficiency"
    assert not quote_is_grounded("we identified a material weakness", source)


def test_quote_is_grounded_false_when_source_is_none():
    assert not quote_is_grounded("anything", None)
