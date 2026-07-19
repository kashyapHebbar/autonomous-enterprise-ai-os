from __future__ import annotations

from datetime import datetime
from math import sqrt
from typing import Any


def forecast_monthly_spend(spend_trend: list[dict[str, Any]], periods: int = 3) -> dict[str, Any]:
    """Produce a transparent linear baseline forecast with residual uncertainty."""
    observations = [
        (str(item["month"]), float(item["spend"]))
        for item in spend_trend
        if item.get("month") and item.get("spend") is not None
    ]
    if len(observations) < 3:
        return {
            "status": "insufficient_history",
            "method": "linear_trend",
            "required_months": 3,
            "observed_months": len(observations),
            "forecast": [],
        }
    values = [value for _, value in observations]
    indexes = list(range(len(values)))
    x_mean = sum(indexes) / len(indexes)
    y_mean = sum(values) / len(values)
    denominator = sum((index - x_mean) ** 2 for index in indexes)
    slope = sum(
        (index - x_mean) * (value - y_mean) for index, value in zip(indexes, values, strict=True)
    )
    slope = slope / denominator if denominator else 0.0
    intercept = y_mean - slope * x_mean
    residuals = [
        value - (intercept + slope * index) for index, value in zip(indexes, values, strict=True)
    ]
    residual_std = sqrt(sum(value**2 for value in residuals) / max(len(residuals) - 2, 1))
    last_month = datetime.strptime(observations[-1][0], "%Y-%m")
    forecast = []
    for offset in range(1, periods + 1):
        point = max(0.0, intercept + slope * (len(values) - 1 + offset))
        uncertainty = residual_std * (1 + offset * 0.15)
        forecast.append(
            {
                "month": _add_months(last_month, offset),
                "predicted_spend": round(point, 4),
                "lower_bound": round(max(0.0, point - uncertainty), 4),
                "upper_bound": round(point + uncertainty, 4),
            }
        )
    normalized_error = residual_std / y_mean if y_mean else 1.0
    return {
        "status": "ready",
        "method": "linear_trend",
        "observed_months": len(observations),
        "trend_per_month": round(slope, 4),
        "direction": "increasing" if slope > 0 else "decreasing" if slope < 0 else "stable",
        "confidence": round(max(0.2, min(0.95, 1 - normalized_error)), 2),
        "forecast": forecast,
        "limitations": (
            "Baseline projection; seasonality and external business drivers are not modeled."
        ),
    }


def _add_months(value: datetime, offset: int) -> str:
    month_index = value.year * 12 + value.month - 1 + offset
    return f"{month_index // 12:04d}-{month_index % 12 + 1:02d}"
