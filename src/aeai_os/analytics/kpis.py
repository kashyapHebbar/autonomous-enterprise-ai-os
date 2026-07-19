from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from math import ceil, floor
from typing import Any

from aeai_os.data import DatasetQueryAdapter
from aeai_os.data.profiling import is_missing_value

COLUMN_ALIASES = {
    "supplier": ("supplier", "supplier_name", "vendor", "vendor_name"),
    "category": (
        "category",
        "spend_category",
        "commodity",
        "procurement_category",
        "expense_type",
        "expenditure_type",
    ),
    "amount": (
        "spend_amount",
        "amount",
        "amount_gbp",
        "invoice_amount",
        "net_amount",
        "total_amount",
        "transaction_amount",
        "cost",
        "spend",
    ),
    "date": (
        "invoice_date",
        "transaction_date",
        "purchase_date",
        "payment_date",
        "posting_date",
        "date",
    ),
}


class AnalyticsError(ValueError):
    pass


@dataclass(frozen=True)
class ProcurementAnalysisResult:
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return self.payload


def analyze_procurement_dataset(adapter: DatasetQueryAdapter) -> ProcurementAnalysisResult:
    rows = adapter.rows()
    columns = adapter.columns()
    resolved = _resolve_columns(columns)
    required = {"supplier", "category", "amount"}
    missing_required = sorted(required - set(resolved))
    if missing_required:
        raise AnalyticsError(
            "Dataset is missing required procurement columns: " + ", ".join(missing_required)
        )

    currency = _detect_currency(resolved.get("amount"), rows)
    currency_symbol = _currency_symbol(currency)

    supplier_totals: dict[str, float] = {}
    category_totals: dict[str, float] = {}
    monthly_totals: dict[str, float] = {}
    parsed_rows: list[dict[str, Any]] = []
    missing_counts = {role: 0 for role in COLUMN_ALIASES}
    invalid_amount_rows = 0

    for row_number, row in enumerate(rows, start=2):
        supplier = _value(row, resolved.get("supplier"))
        category = _value(row, resolved.get("category"))
        raw_amount = _value(row, resolved.get("amount"))
        raw_date = _value(row, resolved.get("date"))

        for role, value in {
            "supplier": supplier,
            "category": category,
            "amount": raw_amount,
            "date": raw_date,
        }.items():
            if value is None or is_missing_value(value):
                missing_counts[role] += 1

        amount = _parse_amount(raw_amount)
        if amount is None:
            invalid_amount_rows += 1
            continue

        supplier_key = supplier or "<missing>"
        category_key = category or "<missing>"
        supplier_totals[supplier_key] = supplier_totals.get(supplier_key, 0.0) + amount
        category_totals[category_key] = category_totals.get(category_key, 0.0) + amount
        month = _parse_month(raw_date)
        if month:
            monthly_totals[month] = monthly_totals.get(month, 0.0) + amount
        parsed_rows.append(
            {
                "row_number": row_number,
                "supplier": supplier_key,
                "category": category_key,
                "amount": amount,
                "month": month,
            }
        )

    total_spend = round(sum(row["amount"] for row in parsed_rows), 4)
    spend_by_supplier = _ranked_spend(supplier_totals, total_spend, "supplier")
    spend_by_category = _ranked_spend(category_totals, total_spend, "category")
    spend_trend = [
        {"month": month, "spend": round(amount, 4)}
        for month, amount in sorted(monthly_totals.items())
    ]
    outliers = _find_outliers(parsed_rows)
    missing_risks = _missing_data_risks(missing_counts, len(rows), resolved)
    savings = _savings_opportunities(
        total_spend=total_spend,
        supplier_totals=supplier_totals,
        outliers=outliers,
    )
    insights = _build_insights(
        total_spend=total_spend,
        spend_by_supplier=spend_by_supplier,
        spend_by_category=spend_by_category,
        outliers=outliers,
        missing_risks=missing_risks,
        currency_symbol=currency_symbol,
    )

    return ProcurementAnalysisResult(
        payload={
            "dataset": {
                "row_count": len(rows),
                "valid_amount_rows": len(parsed_rows),
                "invalid_amount_rows": invalid_amount_rows,
                "resolved_columns": resolved,
                "currency": currency,
                "currency_symbol": currency_symbol,
            },
            "kpis": {
                "total_spend": total_spend,
                "supplier_count": len(supplier_totals),
                "category_count": len(category_totals),
                "average_transaction_value": (
                    round(total_spend / len(parsed_rows), 4) if parsed_rows else 0.0
                ),
                "outlier_count": len(outliers),
                "estimated_savings": round(sum(item["estimated_savings"] for item in savings), 4),
            },
            "spend_by_supplier": spend_by_supplier,
            "spend_by_category": spend_by_category,
            "spend_trend": spend_trend,
            "outliers": outliers,
            "savings_opportunities": savings,
            "missing_data_risks": missing_risks,
            "insights": insights,
        }
    )


def _resolve_columns(columns: list[str]) -> dict[str, str]:
    normalized = {_normalize_column_name(column): column for column in columns}
    resolved: dict[str, str] = {}
    for role, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                resolved[role] = normalized[alias]
                break
    return resolved


def _normalize_column_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _value(row: dict[str, str], column: str | None) -> str | None:
    if column is None:
        return None
    value = row.get(column, "").strip()
    return value or None


def _parse_amount(value: str | None) -> float | None:
    if value is None or is_missing_value(value):
        return None
    normalized = value.replace(",", "").strip()
    normalized = normalized.translate(str.maketrans("", "", "$£€¥₹"))
    try:
        return float(normalized)
    except ValueError:
        return None


def _detect_currency(amount_column: str | None, rows: list[dict[str, str]]) -> str:
    normalized_column = _normalize_column_name(amount_column or "")
    column_currencies = {
        "gbp": "GBP",
        "eur": "EUR",
        "inr": "INR",
        "jpy": "JPY",
        "usd": "USD",
    }
    for marker, currency in column_currencies.items():
        if marker in normalized_column.split("_"):
            return currency

    symbol_currencies = {"£": "GBP", "€": "EUR", "₹": "INR", "¥": "JPY", "$": "USD"}
    if amount_column:
        for row in rows:
            value = row.get(amount_column, "")
            for symbol, currency in symbol_currencies.items():
                if symbol in value:
                    return currency
    return "USD"


def _currency_symbol(currency: str) -> str:
    return {"GBP": "£", "EUR": "€", "INR": "₹", "JPY": "¥", "USD": "$"}.get(
        currency, "$"
    )


def _parse_month(value: str | None) -> str | None:
    if value is None or is_missing_value(value):
        return None
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m")
    except ValueError:
        pass
    for date_format in ("%d/%m/%Y", "%m/%d/%Y", "%b-%y"):
        try:
            return datetime.strptime(value, date_format).strftime("%Y-%m")
        except ValueError:
            continue
    return None


def _ranked_spend(
    totals: dict[str, float],
    total_spend: float,
    dimension: str,
) -> list[dict[str, Any]]:
    return [
        {
            dimension: name,
            "spend": round(amount, 4),
            "share": round(amount / total_spend, 4) if total_spend else 0.0,
        }
        for name, amount in sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    ]


def _find_outliers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    amounts = sorted(row["amount"] for row in rows)
    if len(amounts) < 4:
        return []
    q1 = _percentile(amounts, 0.25)
    q3 = _percentile(amounts, 0.75)
    threshold = q3 + 1.5 * (q3 - q1)
    return [
        {
            **row,
            "amount": round(row["amount"], 4),
            "reason": f"Amount exceeds IQR threshold of {round(threshold, 4)}.",
        }
        for row in rows
        if row["amount"] > threshold
    ]


def _percentile(values: list[float], percentile: float) -> float:
    position = (len(values) - 1) * percentile
    lower = floor(position)
    upper = ceil(position)
    if lower == upper:
        return values[lower]
    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def _missing_data_risks(
    missing_counts: dict[str, int],
    row_count: int,
    resolved: dict[str, str],
) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    for role, count in missing_counts.items():
        if role not in resolved:
            count = row_count
        if not count:
            continue
        ratio = count / row_count if row_count else 0.0
        risks.append(
            {
                "field_role": role,
                "column": resolved.get(role),
                "missing_count": count,
                "missing_ratio": round(ratio, 4),
                "severity": "high" if ratio >= 0.1 else "medium",
            }
        )
    return risks


def _savings_opportunities(
    total_spend: float,
    supplier_totals: dict[str, float],
    outliers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    opportunities: list[dict[str, Any]] = []
    if supplier_totals and total_spend:
        top_supplier, top_spend = max(supplier_totals.items(), key=lambda item: item[1])
        top_share = top_spend / total_spend
        if top_share >= 0.4:
            opportunities.append(
                {
                    "type": "supplier_concentration",
                    "supplier": top_supplier,
                    "rationale": "High supplier concentration may support volume negotiation.",
                    "estimated_savings": round(top_spend * 0.03, 4),
                }
            )

        tail_spend = sum(
            amount for amount in supplier_totals.values() if amount / total_spend < 0.05
        )
        if tail_spend:
            opportunities.append(
                {
                    "type": "tail_supplier_consolidation",
                    "rationale": "Low-share suppliers may be candidates for consolidation.",
                    "estimated_savings": round(tail_spend * 0.02, 4),
                }
            )

    if outliers:
        outlier_spend = sum(item["amount"] for item in outliers)
        opportunities.append(
            {
                "type": "outlier_review",
                "rationale": "Unusually large transactions should be reviewed for leakage.",
                "estimated_savings": round(outlier_spend * 0.05, 4),
            }
        )
    return opportunities


def _build_insights(
    total_spend: float,
    spend_by_supplier: list[dict[str, Any]],
    spend_by_category: list[dict[str, Any]],
    outliers: list[dict[str, Any]],
    missing_risks: list[dict[str, Any]],
    currency_symbol: str = "$",
) -> list[str]:
    insights = [f"Total analyzed procurement spend is {currency_symbol}{total_spend:,.2f}."]
    if spend_by_supplier:
        top = spend_by_supplier[0]
        insights.append(
            f"Top supplier {top['supplier']} represents {round(top['share'] * 100, 1)}% of spend."
        )
    if spend_by_category:
        top = spend_by_category[0]
        insights.append(
            f"Largest category is {top['category']} at {currency_symbol}{top['spend']:,.2f}."
        )
    if outliers:
        noun = "outlier" if len(outliers) == 1 else "outliers"
        insights.append(f"Detected {len(outliers)} high-value transaction {noun}.")
    if missing_risks:
        noun = "area" if len(missing_risks) == 1 else "areas"
        insights.append(f"Detected {len(missing_risks)} missing-data risk {noun}.")
    return insights
