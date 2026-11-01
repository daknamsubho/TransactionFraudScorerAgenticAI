"""Transaction Velocity Analysis Skill (`src/fraud_scorer/skills/velocity_analysis_skill.py`)."""

from typing import Any

from langchain_core.tools import BaseTool

from fraud_scorer.agents.tools import check_velocity_tool
from fraud_scorer.models.transaction import RiskFactor


class VelocityAnalysisSkill:
    """Skill for evaluating transaction burst frequency and velocity anomalies."""

    name: str = "velocity_analysis_skill"
    description: str = (
        "Evaluates transaction velocity in a rolling time window using the check_velocity "
        "LangChain MCP tool adapter and synthesizes VELOCITY risk factors."
    )

    def get_langchain_tool(self) -> BaseTool:
        """Return the underlying LangChain BaseTool for LLM tool binding."""
        return check_velocity_tool

    async def execute(
        self,
        account_id: str,
        window_minutes: int = 60,
    ) -> tuple[dict[str, Any], list[RiskFactor], str]:
        """Invoke check_velocity_tool and evaluate velocity risk factors.

        Returns:
            Tuple of (velocity_dict, velocity_risk_factors, tool_name_invoked).
        """
        v_res: dict[str, Any] = await check_velocity_tool.ainvoke(
            {"account_id": account_id, "window_minutes": window_minutes}
        )
        risk_factors: list[RiskFactor] = []

        is_burst = bool(v_res.get("is_burst", False))
        v_score = float(v_res.get("velocity_risk_score", 0.0))
        tx_count = int(v_res.get("tx_count_in_window", 0))
        win_mins = int(v_res.get("window_minutes", window_minutes))

        if is_burst or v_score >= 40.0:
            risk_factors.append(
                RiskFactor(
                    category="VELOCITY",
                    severity="HIGH" if is_burst else "MEDIUM",
                    contribution_score=round(v_score * 0.25, 2),
                    description=(
                        f"{tx_count} transactions recorded in the last {win_mins} minutes "
                        f"(velocity_risk_score={v_score})."
                    ),
                    details=v_res,
                )
            )

        return v_res, risk_factors, check_velocity_tool.name
