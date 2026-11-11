"""As-reported XBRL facts from SEC companyfacts (free, no key; same rules as EDGAR)."""
from __future__ import annotations

from datetime import date

import requests

from ingestion.edgar import _get

COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# metric -> (kind, concepts in priority order). Companies switch tags over time
# (e.g. Revenues -> RevenueFromContractWithCustomer...), so each metric merges several.
METRICS: dict[str, tuple[str, list[str]]] = {
    "revenue": ("flow", [
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:Revenues",
        "us-gaap:SalesRevenueNet",
        "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax",
        "us-gaap:RevenuesNetOfInterestExpense",  # banks and brokers (JPM, GS)
    ]),
    "gross_profit": ("flow", ["us-gaap:GrossProfit"]),
    "operating_income": ("flow", ["us-gaap:OperatingIncomeLoss"]),
    "net_income": ("flow", ["us-gaap:NetIncomeLoss", "us-gaap:ProfitLoss"]),  # ProfitLoss: e.g. Broadcom
    "eps_diluted": ("flow", ["us-gaap:EarningsPerShareDiluted"]),
    "cfo": ("flow", ["us-gaap:NetCashProvidedByUsedInOperatingActivities"]),
    "capex": ("flow", [
        "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
        "us-gaap:PaymentsToAcquireProductiveAssets",  # Amazon
        "us-gaap:PaymentsToAcquireOtherPropertyPlantAndEquipment",  # Eli Lilly
    ]),
    "equity": ("instant", ["us-gaap:StockholdersEquity"]),
    "long_term_debt": ("instant", ["us-gaap:LongTermDebtNoncurrent", "us-gaap:LongTermDebt"]),
    "cash": ("instant", ["us-gaap:CashAndCashEquivalentsAtCarryingValue"]),
    "shares_outstanding": ("instant", ["dei:EntityCommonStockSharesOutstanding"]),
}

CONCEPTS = sorted({c for _, concepts in METRICS.values() for c in concepts})
FORMS = {"10-K", "10-Q", "10-K/A", "10-Q/A"}


def parse_companyfacts(symbol: str, payload: dict, filed_since: date) -> list[dict]:
    facts = payload.get("facts", {})
    rows: dict[tuple, dict] = {}
    for qualified in CONCEPTS:
        taxonomy, name = qualified.split(":", 1)
        units = facts.get(taxonomy, {}).get(name, {}).get("units", {})
        for unit, items in units.items():
            for f in items:
                if f.get("form") not in FORMS or f.get("val") is None:
                    continue
                if date.fromisoformat(f["filed"]) < filed_since:
                    continue
                end = f["end"]
                row = {
                    "ticker": symbol,
                    "concept": qualified,
                    "unit": unit,
                    "period_start": f.get("start", end),
                    "period_end": end,
                    "value": float(f["val"]),
                    "form": f.get("form"),
                    "fp": f.get("fp"),
                    "fy": f.get("fy"),
                    "filed": f["filed"],
                    "accn": f["accn"],
                }
                key = (qualified, unit, row["period_start"], end, f["accn"])
                rows[key] = row
    return list(rows.values())


def fetch_fundamentals(session: requests.Session, symbol: str, cik: int, filed_since: date) -> list[dict]:
    payload = _get(session, COMPANYFACTS_URL.format(cik=cik)).json()
    return parse_companyfacts(symbol, payload, filed_since)
