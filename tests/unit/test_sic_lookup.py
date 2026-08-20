from pathlib import Path

from agentic_fundamental_analyst.data.sic_lookup import parse_sic_atom_feed

GOLDEN = Path(__file__).parent.parent / "golden"


def test_parse_sic_atom_feed_extracts_ciks_in_order_ignoring_broken_name_fields():
    xml_text = (GOLDEN / "sic7370_browse_edgar_sample.xml").read_text()
    ciks = parse_sic_atom_feed(xml_text)
    assert ciks == ["0001595326", "0001730732", "0001525494"]


def test_parse_sic_atom_feed_empty_feed_returns_empty_list():
    empty_feed = '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    assert parse_sic_atom_feed(empty_feed) == []
