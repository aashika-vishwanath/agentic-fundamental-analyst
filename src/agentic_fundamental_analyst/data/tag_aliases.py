"""Per-concept us-gaap XBRL tag fallback lists.

Different filers tag conceptually identical line items under different
us-gaap tags (see .agents/references/free-data-sources.md §1). A concept
lookup tries each alias in order and stops at the first that resolves;
if none resolve, the caller records a CoverageGap rather than a false 0.0.
"""

TAG_ALIASES: dict[str, list[str]] = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ],
    "net_income": [
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsForCapitalImprovements",
        "PaymentsToAcquireProductiveAssets",
    ],
    "depreciation_amortization": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization",
        "Depreciation",
    ],
    "accounts_receivable": [
        "AccountsReceivableNetCurrent",
        "ReceivablesNetCurrent",
        "AccountsReceivableNet",
    ],
    "inventory": [
        "InventoryNet",
        "InventoryFinishedGoodsNetOfReserves",
    ],
    "total_assets": [
        "Assets",
    ],
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "cost_of_revenue": [
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
    ],
    "sga_expense": [
        "SellingGeneralAndAdministrativeExpense",
        "GeneralAndAdministrativeExpense",
    ],
    "current_assets": [
        "AssetsCurrent",
    ],
    "ppe_gross": [
        "PropertyPlantAndEquipmentGross",
    ],
    # No single us-gaap tag reliably captures "total debt" across filers;
    # this approximates it as long-term debt when no combined tag exists,
    # which excludes any current portion of debt/short-term borrowings
    # tagged separately — a known simplification, not a precise total.
    "total_debt": [
        "DebtLongtermAndShorttermCombinedAmount",
        "LongTermDebtNoncurrent",
        "LongTermDebt",
    ],
}
