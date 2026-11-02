"""Geographic Anomaly Detection Skill (`src/fraud_scorer/skills/geo_anomaly_skill.py`)."""

from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool

from fraud_scorer.agents.tools import check_geo_anomaly_tool
from fraud_scorer.models.transaction import RiskFactor


class GeoAnomalySkill:
    """Skill for computing haversine distance and impossible travel anomalies."""

    name: str = "geo_anomaly_skill"
    description: str = (
        "Calculates geographical distance and implied travel speed between the current "
        "transaction and the account's previous transaction location."
    )

    def get_langchain_tool(self) -> BaseTool:
        """Return the underlying LangChain BaseTool for LLM tool binding."""
        return check_geo_anomaly_tool

    async def execute(
        self,
        account_id: str,
        current_lat: float,
        current_lon: float,
        current_timestamp_iso: str,
        db_path: str | Path | None = None,
    ) -> tuple[dict[str, Any], list[RiskFactor], str]:
        """Invoke check_geo_anomaly_tool and evaluate geographic risk factors.

        Returns:
            Tuple of (geo_dict, geo_risk_factors, tool_name_invoked).
        """
        payload: dict[str, Any] = {
            "account_id": account_id,
            "current_lat": current_lat,
            "current_lon": current_lon,
            "current_timestamp_iso": current_timestamp_iso,
        }
        if db_path is not None:
            payload["db_path"] = str(db_path)

        geo_res: dict[str, Any] = await check_geo_anomaly_tool.ainvoke(payload)
        risk_factors: list[RiskFactor] = []

        is_impossible = bool(
            geo_res.get("impossible_travel") or geo_res.get("is_impossible_travel", False)
        )
        geo_score = float(geo_res.get("geo_risk_score", 0.0))
        distance_km = float(geo_res.get("distance_km", 0.0))
        last_city = str(geo_res.get("last_known_city", "prior location"))
        speed_kmh = float(geo_res.get("speed_kmh") or geo_res.get("implied_speed_kmh", 0.0))

        if is_impossible:
            risk_factors.append(
                RiskFactor(
                    category="GEO_ANOMALY",
                    severity="CRITICAL",
                    contribution_score=round(geo_score * 0.40, 2),
                    description=(
                        f"Impossible travel detected: transaction is {distance_km} km from {last_city} "
                        f"(implied speed {speed_kmh} km/h)."
                    ),
                    details=geo_res,
                )
            )
        elif geo_score >= 40.0:
            risk_factors.append(
                RiskFactor(
                    category="GEO_ANOMALY",
                    severity="MEDIUM",
                    contribution_score=round(geo_score * 0.25, 2),
                    description=f"Unusual distance ({distance_km} km) from previous location ({last_city}).",
                    details=geo_res,
                )
            )

        return geo_res, risk_factors, check_geo_anomaly_tool.name
