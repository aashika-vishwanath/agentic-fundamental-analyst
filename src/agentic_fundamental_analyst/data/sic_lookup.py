"""Parsing for SEC EDGAR's SIC-based company browse feed (Phase 4 peer discovery).

`https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC=...&output=atom` returns an Atom
feed of companies sharing one SIC code. Confirmed live (2026-08-19, see
tests/golden/sic7370_browse_edgar_sample.xml, captured against SIC=7370): the feed's `<entry
title="...">` and `<company-info name="...">` attributes are literal `"ARRAY(0x...)"` strings — a
PHP/Perl array-to-string bug on SEC's own legacy CGI page, not usable for company name or ticker.
The only reliable per-entry field is `<cik>`. Ticker/name resolution happens separately, by
cross-referencing these CIKs against the already-cached company_tickers.json (see
EdgarClient.peers_by_sic in edgar.py).
"""

from bs4 import BeautifulSoup


def parse_sic_atom_feed(xml_text: str) -> list[str]:
    """Every <cik> value inside an <entry>, zero-padded to 10 digits, in feed order."""
    soup = BeautifulSoup(xml_text, "xml")
    ciks: list[str] = []
    for entry in soup.find_all("entry"):
        cik_tag = entry.find("cik")
        if cik_tag is None or not cik_tag.text.strip():
            continue
        ciks.append(cik_tag.text.strip().zfill(10))
    return ciks
