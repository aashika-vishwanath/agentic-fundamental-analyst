"""SIC-code sector exclusion list (PRD §7).

Codes and descriptions verified live against SEC EDGAR's own company-browse
endpoint (`https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC=...`)
during Phase 0 execution, cross-checked against the canonical SIC manual
(Major Group 60 - Depository Institutions, Major Groups 63/64 - Insurance,
Major Group 67 - Holding & Other Investment Offices). Codes with zero current
SEC registrants are still included for completeness of the classification
range; absence of a live registrant doesn't mean the code is invalid.
"""

from agentic_fundamental_analyst.contracts.intake import ExcludedSector

# Major Group 60 — Depository Institutions (banks, thrifts, credit unions).
_BANK_SIC_CODES: dict[str, str] = {
    "6020": "DEPOSITORY INSTITUTIONS",
    "6021": "NATIONAL COMMERCIAL BANKS",
    "6022": "STATE COMMERCIAL BANKS",
    "6029": "COMMERCIAL BANKS, NEC",
    "6030": "SAVINGS INSTITUTIONS",
    "6035": "SAVINGS INSTITUTION, FEDERALLY CHARTERED",
    "6036": "SAVINGS INSTITUTIONS, NOT FEDERALLY CHARTERED",
    "6060": "CREDIT UNIONS",
    "6061": "CREDIT UNIONS, FEDERALLY CHARTERED",
    "6062": "CREDIT UNIONS, STATE CHARTERED",
    "6080": "FOREIGN BANKING & BRANCHES & AGENCIES",
    "6081": "BRANCHES & AGENCIES OF FOREIGN BANKS",
    "6082": "FOREIGN TRADE & INTERNATIONAL BANKS",
    "6090": "FUNCTIONS RELATED TO DEPOSITORY BANKING",
    "6091": "FEDERAL & FEDERALLY-SPONSORED CREDIT AGENCIES",
    "6099": "FUNCTIONS RELATED TO DEPOSITORY BANKING, NEC",
}

# Major Groups 63/64 — Insurance Carriers and Insurance Agents/Brokers/Service.
# Agents/brokers (6411) are included alongside carriers: their financials are
# fee/commission-driven services businesses, not the revenue/COGS/inventory
# structure this system's ratio framework assumes, same rationale as carriers.
_INSURER_SIC_CODES: dict[str, str] = {
    "6300": "INSURANCE CARRIERS",
    "6311": "LIFE INSURANCE",
    "6321": "ACCIDENT & HEALTH INSURANCE",
    "6324": "HOSPITAL & MEDICAL SERVICE PLANS",
    "6331": "FIRE, MARINE & CASUALTY INSURANCE",
    "6351": "SURETY INSURANCE",
    "6361": "TITLE INSURANCE",
    "6371": "PENSION, HEALTH & WELFARE FUNDS",
    "6399": "INSURANCE CARRIERS, NEC",
    "6411": "INSURANCE AGENTS, BROKERS & SERVICE",
}

# REITs — single code, confirmed live: SIC 6798 = "REAL ESTATE INVESTMENT TRUSTS".
_REIT_SIC_CODES: dict[str, str] = {
    "6798": "REAL ESTATE INVESTMENT TRUSTS",
}

EXCLUDED_SIC_CODES: dict[str, tuple[ExcludedSector, str]] = {
    **{code: (ExcludedSector.BANK, desc) for code, desc in _BANK_SIC_CODES.items()},
    **{code: (ExcludedSector.INSURER, desc) for code, desc in _INSURER_SIC_CODES.items()},
    **{code: (ExcludedSector.REIT, desc) for code, desc in _REIT_SIC_CODES.items()},
}


def classify_sic(sic_code: str) -> tuple[ExcludedSector, str] | None:
    """Return (ExcludedSector, canonical description) if `sic_code` is excluded,
    else None. Canonical description is our verified label, not necessarily
    identical to whatever description the caller already has for the code.
    """
    return EXCLUDED_SIC_CODES.get(sic_code)
