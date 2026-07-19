from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from math import ceil, floor
from statistics import median
from typing import Any

MIN_ANOMALY_SCORE = 20


def detect_procurement_anomalies(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Score explainable procurement anomalies without requiring a trained model."""
    if not rows:
        return _result([], 0.0)

    amounts = sorted(float(row["amount"]) for row in rows)
    q1 = _percentile(amounts, 0.25)
    q3 = _percentile(amounts, 0.75)
    amount_threshold = q3 + 1.5 * (q3 - q1) if len(amounts) >= 4 else float("inf")
    invoice_counts = Counter(
        _normalized(row.get("invoice_id"))
        for row in rows
        if _normalized(row.get("invoice_id"))
    )
    transaction_counts = Counter(_transaction_fingerprint(row) for row in rows)
    supplier_amounts: dict[str, list[float]] = defaultdict(list)
    supplier_counts: Counter[str] = Counter()
    split_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        supplier = str(row.get("supplier") or "<missing>")
        supplier_amounts[supplier].append(float(row["amount"]))
        supplier_counts[supplier] += 1
        date = _normalized(row.get("date"))
        if date:
            split_groups[(supplier, str(row.get("category") or "<missing>"), date)].append(row)

    split_rows = {
        int(row["row_number"])
        for group in split_groups.values()
        if _looks_like_split_purchase(group, q3)
        for row in group
    }

    anomalies: list[dict[str, Any]] = []
    for row in rows:
        signals: list[dict[str, Any]] = []
        amount = float(row["amount"])
        supplier = str(row.get("supplier") or "<missing>")
        invoice_id = _normalized(row.get("invoice_id"))

        if amount > amount_threshold:
            signals.append(
                _signal(
                    "amount_outlier",
                    "Unusual transaction amount",
                    45,
                    f"Amount exceeds the robust IQR threshold of {amount_threshold:.2f}.",
                )
            )
        if invoice_id and invoice_counts[invoice_id] > 1:
            signals.append(
                _signal(
                    "duplicate_invoice",
                    "Duplicate invoice identifier",
                    60,
                    f"Invoice {invoice_id} appears {invoice_counts[invoice_id]} times.",
                )
            )
        fingerprint_count = transaction_counts[_transaction_fingerprint(row)]
        if fingerprint_count > 1 and _normalized(row.get("date")):
            signals.append(
                _signal(
                    "duplicate_transaction",
                    "Repeated transaction fingerprint",
                    45,
                    (
                        "The same supplier, category, date, and amount appear "
                        f"{fingerprint_count} times."
                    ),
                )
            )
        supplier_baseline = median(supplier_amounts[supplier])
        if (
            len(supplier_amounts[supplier]) >= 3
            and supplier_baseline > 0
            and amount >= supplier_baseline * 3
            and amount > q3
        ):
            signals.append(
                _signal(
                    "supplier_amount_spike",
                    "Supplier amount spike",
                    30,
                    (
                        f"Amount is {amount / supplier_baseline:.1f}x this supplier's "
                        "median transaction."
                    ),
                )
            )
        if int(row["row_number"]) in split_rows:
            signals.append(
                _signal(
                    "split_purchase_pattern",
                    "Potential split purchase",
                    35,
                    "Three or more similar purchases share a supplier, category, and date.",
                )
            )
        parsed_date = _parse_date(row.get("date"))
        if parsed_date is not None and parsed_date.weekday() >= 5:
            signals.append(
                _signal(
                    "weekend_activity",
                    "Weekend transaction",
                    12,
                    f"Transaction date {parsed_date.date().isoformat()} falls on a weekend.",
                )
            )
        if supplier_counts[supplier] == 1 and amount > q3 and len(rows) >= 4:
            signals.append(
                _signal(
                    "single_use_high_value_supplier",
                    "High-value single-use supplier",
                    20,
                    (
                        "Supplier appears once and the transaction is above the dataset's "
                        "upper quartile."
                    ),
                )
            )

        score = _combined_score(signals)
        if score < MIN_ANOMALY_SCORE:
            continue
        anomalies.append(
            {
                "id": f"anomaly-row-{row['row_number']}",
                **row,
                "amount": round(amount, 4),
                "risk_score": score,
                "severity": _severity(score),
                "confidence": _confidence(row, len(rows), signals),
                "signals": signals,
                "reason": "; ".join(signal["label"] for signal in signals),
                "recommended_action": _recommended_action(score),
            }
        )

    anomalies.sort(key=lambda item: (-item["risk_score"], -item["amount"], item["row_number"]))
    return _result(anomalies, amount_threshold)


def _result(anomalies: list[dict[str, Any]], amount_threshold: float) -> dict[str, Any]:
    severity_counts = Counter(item["severity"] for item in anomalies)
    return {
        "model": {
            "name": "explainable-procurement-risk",
            "version": "1.0",
            "method": "robust-statistics-and-rules",
            "minimum_score": MIN_ANOMALY_SCORE,
            "amount_outlier_threshold": (
                round(amount_threshold, 4) if amount_threshold != float("inf") else None
            ),
        },
        "summary": {
            "anomaly_count": len(anomalies),
            "critical_count": severity_counts["critical"],
            "high_risk_count": severity_counts["high"],
            "medium_risk_count": severity_counts["medium"],
            "risk_exposure": round(sum(float(item["amount"]) for item in anomalies), 4),
        },
        "anomalies": anomalies,
    }


def _transaction_fingerprint(row: dict[str, Any]) -> tuple[str, str, str, float]:
    return (
        _normalized(row.get("supplier")),
        _normalized(row.get("category")),
        _normalized(row.get("date")),
        round(float(row["amount"]), 4),
    )


def _looks_like_split_purchase(rows: list[dict[str, Any]], upper_quartile: float) -> bool:
    if len(rows) < 3:
        return False
    amounts = [float(row["amount"]) for row in rows if float(row["amount"]) > 0]
    if len(amounts) < 3 or min(amounts) <= 0:
        return False
    similar_amounts = max(amounts) / min(amounts) <= 1.15
    material_total = sum(amounts) >= max(upper_quartile * 2, median(amounts) * 3)
    return similar_amounts and material_total


def _signal(code: str, label: str, weight: int, evidence: str) -> dict[str, Any]:
    return {"code": code, "label": label, "weight": weight, "evidence": evidence}


def _combined_score(signals: list[dict[str, Any]]) -> int:
    remaining_probability = 1.0
    for signal in signals:
        remaining_probability *= 1 - int(signal["weight"]) / 100
    return min(100, round((1 - remaining_probability) * 100))


def _severity(score: int) -> str:
    if score >= 80:
        return "critical"
    if score >= 60:
        return "high"
    if score >= 35:
        return "medium"
    return "low"


def _confidence(
    row: dict[str, Any], row_count: int, signals: list[dict[str, Any]]
) -> float:
    populated = sum(
        bool(_normalized(row.get(field)))
        for field in ("invoice_id", "date", "department", "approver")
    )
    value = 0.52 + populated * 0.07 + min(row_count, 100) / 1000 + len(signals) * 0.03
    return round(min(value, 0.98), 2)


def _recommended_action(score: int) -> str:
    if score >= 80:
        return "Hold for immediate investigation and verify supporting documents."
    if score >= 60:
        return "Prioritize for investigator review before approval or payment."
    if score >= 35:
        return "Review the transaction and compare it with supplier history."
    return "Monitor and include in the next routine procurement review."


def _normalized(value: Any) -> str:
    return str(value or "").strip().lower()


def _parse_date(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    for date_format in ("%d/%m/%Y", "%m/%d/%Y", "%b-%y"):
        try:
            return datetime.strptime(text, date_format)
        except ValueError:
            continue
    return None


def _percentile(values: list[float], percentile: float) -> float:
    position = (len(values) - 1) * percentile
    lower = floor(position)
    upper = ceil(position)
    if lower == upper:
        return values[lower]
    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight
