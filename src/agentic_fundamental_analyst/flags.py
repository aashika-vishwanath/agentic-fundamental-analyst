"""Deterministic cross-analyst flag dedup (PRD §4's pipeline diagram: exact-dedup
runs before the Flag Consolidator agent's semantic merge). Pure logic, zero
judgment — a real Agent-or-Code split, see the Phase 2 plan."""

from agentic_fundamental_analyst.contracts.flags import Flag


def deduplicate_exact_flags(flags: list[Flag]) -> list[Flag]:
    """Same (metric, fiscal_year, fiscal_period) across analysts -> keep the
    first occurrence only. Distinct from the Flag Consolidator's semantic
    merge of *different* flags describing the same real-world issue."""
    seen: set[tuple[str, int, str]] = set()
    deduped: list[Flag] = []
    for flag in flags:
        key = (flag.metric, flag.fiscal_year, flag.fiscal_period)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(flag)
    return deduped
