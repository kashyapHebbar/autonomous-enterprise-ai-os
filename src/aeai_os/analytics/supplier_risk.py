from __future__ import annotations

from collections import defaultdict
from typing import Any


def build_supplier_risk_profiles(
    spend_by_supplier: list[dict[str, Any]],
    anomalies: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    anomaly_scores: dict[str, list[int]] = defaultdict(list)
    anomaly_exposure: dict[str, float] = defaultdict(float)
    for anomaly in anomalies:
        supplier = str(anomaly.get("supplier") or "<missing>")
        anomaly_scores[supplier].append(int(anomaly.get("risk_score") or 0))
        anomaly_exposure[supplier] += float(anomaly.get("amount") or 0)
    profiles = []
    for supplier in spend_by_supplier:
        name = str(supplier.get("supplier") or "<missing>")
        share = float(supplier.get("share") or 0)
        spend = float(supplier.get("spend") or 0)
        scores = anomaly_scores[name]
        concentration_component = min(50, round(share * 100 * 0.5))
        anomaly_component = round(max(scores, default=0) * 0.5)
        score = min(100, concentration_component + anomaly_component)
        factors = []
        if share >= 0.4:
            factors.append("High supplier concentration")
        if scores:
            factors.append(f"{len(scores)} flagged transaction(s)")
        if anomaly_exposure[name] and spend:
            factors.append(f"{anomaly_exposure[name] / spend:.0%} of supplier spend is flagged")
        profiles.append(
            {
                "supplier": name,
                "risk_score": score,
                "risk_level": "high" if score >= 60 else "medium" if score >= 30 else "low",
                "spend": round(spend, 4),
                "spend_share": round(share, 4),
                "anomaly_count": len(scores),
                "anomaly_exposure": round(anomaly_exposure[name], 4),
                "risk_factors": factors or ["No elevated internal risk signals"],
            }
        )
    return sorted(profiles, key=lambda item: (-item["risk_score"], -item["spend"]))
