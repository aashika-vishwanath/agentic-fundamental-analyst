from pathlib import Path

from agentic_fundamental_analyst.data.filing_sections import (
    extract_8k_item_bodies,
    extract_10k_sections,
)

GOLDEN = Path(__file__).parent.parent / "golden"


def _read(name: str) -> str:
    return (GOLDEN / name).read_text()


def test_googl_10k_sections_found_via_bold_all_caps_headers():
    sections = extract_10k_sections(_read("googl_10k_item1_1a_7.html"))
    assert sections["item_1_business"] is not None
    assert sections["item_1a_risk_factors"] is not None
    assert sections["item_7_mdna"] is not None
    assert sections["item_1_business"].startswith("ITEM 1.\nBUSINESS")
    # Table-of-Contents "Item 1A." entries must not leak into item_1_business
    assert "RISK FACTORS" not in sections["item_1_business"][:200]


def test_aapl_10k_sections_found_via_bold_mixed_case_headers():
    """Apple's body headers are mixed-case with CSS-driven visual caps —
    the plain ALL-CAPS heuristic that works for Google finds nothing here;
    this is the case that forced the bold/hyperlink-aware rewrite."""
    sections = extract_10k_sections(_read("aapl_10k_item1_1a_7.html"))
    assert sections["item_1_business"] is not None
    assert sections["item_1a_risk_factors"] is not None
    assert sections["item_7_mdna"] is not None
    assert sections["item_1_business"].lower().startswith("item 1.")
    assert "business" in sections["item_1_business"][:40].lower()


def test_10k_sections_do_not_include_table_of_contents_page_numbers():
    sections = extract_10k_sections(_read("googl_10k_item1_1a_7.html"))
    # The real section runs thousands of characters; a ToC entry would be
    # a handful of characters ending in a page number.
    business = sections["item_1_business"]
    risk_factors = sections["item_1a_risk_factors"]
    assert business is not None and len(business) > 1000
    assert risk_factors is not None and len(risk_factors) > 1000


def test_10k_missing_headers_yields_none_not_empty_string():
    sections = extract_10k_sections("<html><body><p>No items here.</p></body></html>")
    assert sections == {
        "item_1_business": None,
        "item_1a_risk_factors": None,
        "item_7_mdna": None,
    }


def test_googl_8k_item_bodies_trailing_period_format():
    bodies = extract_8k_item_bodies(_read("googl_8k_sample.html"))
    assert set(bodies) == {"8.01", "9.01"}
    assert "Alphabet" in bodies["8.01"]


def test_aapl_8k_item_bodies_no_trailing_period_format():
    """Apple's 8-K omits the trailing period after the item number
    ("Item 2.02" vs. Google's "Item 8.01.") — the regex must handle both."""
    bodies = extract_8k_item_bodies(_read("aapl_8k_sample.html"))
    assert set(bodies) == {"2.02", "9.01"}
    assert "Results of Operations" in bodies["2.02"]


def test_8k_no_items_yields_empty_dict_not_error():
    bodies = extract_8k_item_bodies("<html><body><p>No items here.</p></body></html>")
    assert bodies == {}
