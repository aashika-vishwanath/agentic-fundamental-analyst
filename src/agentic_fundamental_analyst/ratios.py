"""Deterministic ratio math — the earnings-quality checklist from
.claude/skills/investment-memo-writing/SKILL.md §2. Every function takes
typed FiscalPeriod input(s) and returns a RatioResult: `value=None` with a
`reason` whenever an input field is missing, never a silently-wrong 0.0
(PRD principle #4). Pure arithmetic only — no interpretation, no agent.

Known Phase 0 gap: cash_conversion_cycle (checklist item #17, DSO+DIO-DPO)
cannot compute the DPO leg — FiscalPeriod has no accounts_payable field
(not part of the 5 fields added for Beneish support). Documented here
rather than silently approximated; revisit if a later phase needs it.
"""

from agentic_fundamental_analyst.contracts.financials import FinancialStatementBundle, FiscalPeriod
from agentic_fundamental_analyst.contracts.ratios import PeriodRatios, RatioResult, RatioTrendBundle

_DAYS_PER_YEAR = 365.0


def _ratio(numerator: float | None, denominator: float | None, missing_reason: str) -> RatioResult:
    if numerator is None or denominator is None:
        return RatioResult(value=None, reason=missing_reason)
    if denominator == 0:
        return RatioResult(value=None, reason="denominator_is_zero")
    return RatioResult(value=numerator / denominator)


def _growth(current: float | None, prior: float | None, missing_reason: str) -> RatioResult:
    if current is None or prior is None:
        return RatioResult(value=None, reason=missing_reason)
    if prior == 0:
        return RatioResult(value=None, reason="prior_period_is_zero")
    return RatioResult(value=(current - prior) / prior)


# --- checklist #2: Days Sales Outstanding ---------------------------------


def days_sales_outstanding(period: FiscalPeriod) -> RatioResult:
    ar = period.accounts_receivable
    return _ratio(
        ar * _DAYS_PER_YEAR if ar is not None else None,
        period.revenue,
        "accounts_receivable_or_revenue_missing",
    )


# --- checklist #1: receivables growing faster than revenue ---------------


def receivables_growth_vs_revenue_growth(
    current: FiscalPeriod, prior: FiscalPeriod
) -> RatioResult:
    ar_growth = _growth(
        current.accounts_receivable, prior.accounts_receivable, "ar_growth_unavailable"
    )
    rev_growth = _growth(current.revenue, prior.revenue, "revenue_growth_unavailable")
    if ar_growth.value is None or rev_growth.value is None:
        return RatioResult(value=None, reason=ar_growth.reason or rev_growth.reason)
    return RatioResult(value=ar_growth.value - rev_growth.value)


# --- checklist #3: inventory growing faster than revenue/COGS ------------


def inventory_growth_vs_cogs_growth(current: FiscalPeriod, prior: FiscalPeriod) -> RatioResult:
    inv_growth = _growth(current.inventory, prior.inventory, "inventory_growth_unavailable")
    cogs_growth = _growth(current.cost_of_revenue, prior.cost_of_revenue, "cogs_growth_unavailable")
    if inv_growth.value is None or cogs_growth.value is None:
        return RatioResult(value=None, reason=inv_growth.reason or cogs_growth.reason)
    return RatioResult(value=inv_growth.value - cogs_growth.value)


# --- checklist #4: Sloan accruals -----------------------------------------


def sloan_accruals(period: FiscalPeriod) -> RatioResult:
    if period.net_income is None or period.operating_cash_flow is None:
        return RatioResult(value=None, reason="net_income_or_operating_cash_flow_missing")
    return _ratio(
        period.net_income - period.operating_cash_flow,
        period.total_assets,
        "total_assets_missing",
    )


# --- checklist #5: cash conversion ratio ----------------------------------


def cash_conversion_ratio(period: FiscalPeriod) -> RatioResult:
    return _ratio(
        period.operating_cash_flow, period.net_income, "operating_cash_flow_or_net_income_missing"
    )


# --- checklist #6: capex / D&A --------------------------------------------


def capex_to_depreciation_ratio(period: FiscalPeriod) -> RatioResult:
    return _ratio(
        period.capex, period.depreciation_amortization, "capex_or_depreciation_missing"
    )


# --- checklist #17: cash conversion cycle (partial — see module docstring) --


def days_inventory_outstanding(period: FiscalPeriod) -> RatioResult:
    return _ratio(
        period.inventory * _DAYS_PER_YEAR if period.inventory is not None else None,
        period.cost_of_revenue,
        "inventory_or_cost_of_revenue_missing",
    )


def cash_conversion_cycle(period: FiscalPeriod) -> RatioResult:
    return RatioResult(
        value=None,
        reason="accounts_payable_not_in_fiscal_period_contract_dpo_uncomputable",
    )


# --- checklist #7: Beneish M-Score components -----------------------------


def dsri(current: FiscalPeriod, prior: FiscalPeriod) -> RatioResult:
    """Days Sales in Receivables Index."""
    current_dso = days_sales_outstanding(current)
    prior_dso = days_sales_outstanding(prior)
    if current_dso.value is None or prior_dso.value is None:
        return RatioResult(value=None, reason=current_dso.reason or prior_dso.reason)
    if prior_dso.value == 0:
        return RatioResult(value=None, reason="prior_period_dso_is_zero")
    return RatioResult(value=current_dso.value / prior_dso.value)


def gmi(current: FiscalPeriod, prior: FiscalPeriod) -> RatioResult:
    """Gross Margin Index (prior margin / current margin — a GMI > 1 means
    margin deteriorated, the direction associated with earnings pressure)."""
    if (
        current.revenue is None
        or current.cost_of_revenue is None
        or prior.revenue is None
        or prior.cost_of_revenue is None
    ):
        return RatioResult(value=None, reason="revenue_or_cost_of_revenue_missing")
    if current.revenue == 0 or prior.revenue == 0:
        return RatioResult(value=None, reason="revenue_is_zero")
    current_margin = (current.revenue - current.cost_of_revenue) / current.revenue
    prior_margin = (prior.revenue - prior.cost_of_revenue) / prior.revenue
    if current_margin == 0:
        return RatioResult(value=None, reason="current_period_margin_is_zero")
    return RatioResult(value=prior_margin / current_margin)


def aqi(current: FiscalPeriod, prior: FiscalPeriod) -> RatioResult:
    """Asset Quality Index — non-current, non-PP&E assets as a share of
    total assets, current period vs. prior."""

    def _non_current_asset_quality(period: FiscalPeriod) -> float | None:
        if period.total_assets is None or period.current_assets is None or period.ppe_gross is None:
            return None
        if period.total_assets == 0:
            return None
        return 1 - (period.current_assets + period.ppe_gross) / period.total_assets

    current_q = _non_current_asset_quality(current)
    prior_q = _non_current_asset_quality(prior)
    if current_q is None or prior_q is None:
        return RatioResult(
            value=None, reason="total_assets_or_current_assets_or_ppe_gross_missing"
        )
    if prior_q == 0:
        return RatioResult(value=None, reason="prior_period_asset_quality_is_zero")
    return RatioResult(value=current_q / prior_q)


def sgi(current: FiscalPeriod, prior: FiscalPeriod) -> RatioResult:
    """Sales Growth Index (current revenue / prior revenue)."""
    return _ratio(current.revenue, prior.revenue, "revenue_missing")


def depi(current: FiscalPeriod, prior: FiscalPeriod) -> RatioResult:
    """Depreciation Index — prior depreciation rate / current depreciation
    rate, where the depreciation rate is D&A / (D&A + gross PP&E)."""

    def _depreciation_rate(period: FiscalPeriod) -> float | None:
        if period.depreciation_amortization is None or period.ppe_gross is None:
            return None
        denom = period.depreciation_amortization + period.ppe_gross
        if denom == 0:
            return None
        return period.depreciation_amortization / denom

    current_rate = _depreciation_rate(current)
    prior_rate = _depreciation_rate(prior)
    if current_rate is None or prior_rate is None:
        return RatioResult(value=None, reason="depreciation_or_ppe_gross_missing")
    if current_rate == 0:
        return RatioResult(value=None, reason="current_period_depreciation_rate_is_zero")
    return RatioResult(value=prior_rate / current_rate)


def sgai(current: FiscalPeriod, prior: FiscalPeriod) -> RatioResult:
    """SG&A Index — SG&A as a share of revenue, current vs. prior."""

    def _sga_ratio(period: FiscalPeriod) -> float | None:
        if period.sga_expense is None or period.revenue is None or period.revenue == 0:
            return None
        return period.sga_expense / period.revenue

    current_ratio = _sga_ratio(current)
    prior_ratio = _sga_ratio(prior)
    if current_ratio is None or prior_ratio is None:
        return RatioResult(value=None, reason="sga_expense_or_revenue_missing")
    if prior_ratio == 0:
        return RatioResult(value=None, reason="prior_period_sga_ratio_is_zero")
    return RatioResult(value=current_ratio / prior_ratio)


def lvgi(current: FiscalPeriod, prior: FiscalPeriod) -> RatioResult:
    """Leverage Index — total_debt / total_assets, current vs. prior. Uses
    the approximated total_debt field (see tag_aliases.py note: long-term
    debt only when no combined tag exists)."""

    def _leverage(period: FiscalPeriod) -> float | None:
        if period.total_debt is None or period.total_assets is None or period.total_assets == 0:
            return None
        return period.total_debt / period.total_assets

    current_lev = _leverage(current)
    prior_lev = _leverage(prior)
    if current_lev is None or prior_lev is None:
        return RatioResult(value=None, reason="total_debt_or_total_assets_missing")
    if prior_lev == 0:
        return RatioResult(value=None, reason="prior_period_leverage_is_zero")
    return RatioResult(value=current_lev / prior_lev)


def tata(period: FiscalPeriod) -> RatioResult:
    """Total Accruals to Total Assets — identical formula to sloan_accruals,
    kept as a separate name to mirror the Beneish literature's TATA label."""
    return sloan_accruals(period)


def beneish_m_score(current: FiscalPeriod, prior: FiscalPeriod) -> RatioResult:
    """Beneish (1999) M-Score. Conventional flag threshold: M > -1.78 (see
    checklist item #7). All 8 components must resolve or the score is
    reported as unavailable rather than computed from partial inputs."""
    components = {
        "dsri": dsri(current, prior),
        "gmi": gmi(current, prior),
        "aqi": aqi(current, prior),
        "sgi": sgi(current, prior),
        "depi": depi(current, prior),
        "sgai": sgai(current, prior),
        "lvgi": lvgi(current, prior),
        "tata": tata(current),
    }
    missing = [name for name, result in components.items() if result.value is None]
    if missing:
        return RatioResult(value=None, reason=f"components_unavailable:{','.join(sorted(missing))}")

    v: dict[str, float] = {
        name: result.value for name, result in components.items() if result.value is not None
    }
    m_score = (
        -4.84
        + 0.920 * v["dsri"]
        + 0.528 * v["gmi"]
        + 0.404 * v["aqi"]
        + 0.892 * v["sgi"]
        + 0.115 * v["depi"]
        - 0.172 * v["sgai"]
        + 4.679 * v["tata"]
        - 0.327 * v["lvgi"]
    )
    return RatioResult(value=m_score)


# --- Phase 1: trend computation over annual (10-K) periods ---------------
#
# Deliberately annual-only. Including 10-Q periods here would require ratios
# spanning cash-flow-statement concepts (cash_conversion_ratio, sloan_accruals)
# to trust that operating_cash_flow and net_income represent the same duration
# for a given FiscalPeriod — which EdgarClient cannot currently guarantee: many
# filers never tag a discrete-quarter cash-flow figure at all, so the
# shortest-available-duration fallback (data-layer.md "bug #2") can leave a
# 10-Q's operating_cash_flow as a 9-month YTD figure sitting next to a
# single-quarter net_income, silently. See CLAUDE.md's Known Phase 0 gaps.


def compute_period_ratios(current: FiscalPeriod, prior: FiscalPeriod | None) -> PeriodRatios:
    no_prior = RatioResult(value=None, reason="no_prior_period_available")
    return PeriodRatios(
        fiscal_year=current.fiscal_year,
        fiscal_period=current.fiscal_period,
        period_end=current.period_end,
        days_sales_outstanding=days_sales_outstanding(current),
        receivables_growth_vs_revenue_growth=(
            receivables_growth_vs_revenue_growth(current, prior) if prior is not None else no_prior
        ),
        inventory_growth_vs_cogs_growth=(
            inventory_growth_vs_cogs_growth(current, prior) if prior is not None else no_prior
        ),
        sloan_accruals=sloan_accruals(current),
        cash_conversion_ratio=cash_conversion_ratio(current),
        capex_to_depreciation_ratio=capex_to_depreciation_ratio(current),
        days_inventory_outstanding=days_inventory_outstanding(current),
        cash_conversion_cycle=cash_conversion_cycle(current),
        beneish_m_score=beneish_m_score(current, prior) if prior is not None else no_prior,
        revenue=current.revenue,
        net_income=current.net_income,
        capex=current.capex,
        depreciation_amortization=current.depreciation_amortization,
    )


def compute_trend_bundle(bundle: FinancialStatementBundle) -> RatioTrendBundle:
    annual_periods = sorted(
        (p for p in bundle.periods if p.form == "10-K"),
        key=lambda p: p.period_end,
    )
    periods = [
        compute_period_ratios(period, annual_periods[i - 1] if i > 0 else None)
        for i, period in enumerate(annual_periods)
    ]
    return RatioTrendBundle(
        ticker=bundle.ticker, cik=bundle.cik, periods=periods, coverage_gaps=bundle.coverage_gaps
    )
