from __future__ import annotations

from aeai_os.analytics.anomalies import detect_procurement_anomalies


def _row(
    row_number: int,
    supplier: str,
    category: str,
    amount: float,
    date: str,
    invoice_id: str | None = None,
) -> dict:
    return {
        "row_number": row_number,
        "supplier": supplier,
        "category": category,
        "amount": amount,
        "date": date,
        "month": date[:7],
        "invoice_id": invoice_id,
        "department": "Finance",
        "approver": "Reviewer One",
    }


def test_anomaly_engine_scores_duplicate_invoices_with_explainable_evidence():
    rows = [
        _row(2, "Acme", "Software", 500, "2026-01-05", "INV-100"),
        _row(3, "Acme", "Software", 500, "2026-01-05", "INV-100"),
        _row(4, "Zenith", "Hardware", 120, "2026-01-06", "INV-101"),
        _row(5, "North", "Office", 80, "2026-01-07", "INV-102"),
    ]

    result = detect_procurement_anomalies(rows)
    duplicate = next(item for item in result["anomalies"] if item["row_number"] == 2)
    signal_codes = {signal["code"] for signal in duplicate["signals"]}

    assert {"duplicate_invoice", "duplicate_transaction"} <= signal_codes
    assert duplicate["risk_score"] >= 70
    assert duplicate["severity"] in {"high", "critical"}
    assert duplicate["confidence"] > 0.7
    assert duplicate["recommended_action"]
    assert result["summary"]["risk_exposure"] >= 1000


def test_anomaly_engine_detects_split_purchases_and_ranks_by_score():
    rows = [
        _row(2, "Acme", "Software", 490, "2026-02-02", "A-1"),
        _row(3, "Acme", "Software", 500, "2026-02-02", "A-2"),
        _row(4, "Acme", "Software", 510, "2026-02-02", "A-3"),
        _row(5, "Zenith", "Hardware", 100, "2026-02-03", "Z-1"),
        _row(6, "North", "Office", 90, "2026-02-04", "N-1"),
    ]

    anomalies = detect_procurement_anomalies(rows)["anomalies"]

    split_rows = [
        item
        for item in anomalies
        if any(signal["code"] == "split_purchase_pattern" for signal in item["signals"])
    ]
    assert {item["row_number"] for item in split_rows} == {2, 3, 4}
    assert [item["risk_score"] for item in anomalies] == sorted(
        (item["risk_score"] for item in anomalies), reverse=True
    )


def test_anomaly_engine_degrades_gracefully_without_optional_fields():
    rows = [
        _row(2, "Acme", "Software", 10, "", None),
        _row(3, "Acme", "Software", 11, "", None),
        _row(4, "Zenith", "Hardware", 12, "", None),
        _row(5, "North", "Office", 1000, "", None),
    ]
    for row in rows:
        row["department"] = None
        row["approver"] = None

    result = detect_procurement_anomalies(rows)

    assert result["anomalies"][0]["row_number"] == 5
    assert any(
        signal["code"] == "amount_outlier"
        for signal in result["anomalies"][0]["signals"]
    )
    assert result["anomalies"][0]["confidence"] < 0.7
