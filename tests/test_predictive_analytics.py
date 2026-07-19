from aeai_os.analytics.forecasting import forecast_monthly_spend
from aeai_os.analytics.supplier_risk import build_supplier_risk_profiles


def test_forecast_requires_three_months_of_history():
    result = forecast_monthly_spend([{"month": "2026-01", "spend": 100}])

    assert result["status"] == "insufficient_history"
    assert result["forecast"] == []


def test_forecast_projects_explainable_linear_trend():
    result = forecast_monthly_spend(
        [
            {"month": "2026-01", "spend": 100},
            {"month": "2026-02", "spend": 200},
            {"month": "2026-03", "spend": 300},
        ]
    )

    assert result["status"] == "ready"
    assert result["method"] == "linear_trend"
    assert result["trend_per_month"] == 100
    assert result["forecast"][0] == {
        "month": "2026-04",
        "predicted_spend": 400,
        "lower_bound": 400,
        "upper_bound": 400,
    }


def test_supplier_risk_combines_concentration_and_anomaly_exposure():
    profiles = build_supplier_risk_profiles(
        [
            {"supplier": "Acme", "spend": 800, "share": 0.8},
            {"supplier": "Beta", "spend": 200, "share": 0.2},
        ],
        [
            {
                "supplier": "Acme",
                "amount": 400,
                "risk_score": 80,
            }
        ],
    )

    assert profiles[0]["supplier"] == "Acme"
    assert profiles[0]["risk_score"] == 80
    assert profiles[0]["risk_level"] == "high"
    assert profiles[0]["anomaly_exposure"] == 400
    assert profiles[1]["risk_level"] == "low"
