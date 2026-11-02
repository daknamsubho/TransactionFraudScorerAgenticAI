"""Merchant Risk Analysis Skill (`src/fraud_scorer/skills/merchant_risk_skill.py`)."""

from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool

from fraud_scorer.agents.tools import check_merchant_risk_tool
from fraud_scorer.models.transaction import RiskFactor


class MerchantRiskSkill:
    """Skill for evaluating Merchant Category Code (MCC) risk and merchant reputation."""

    name: str = "merchant_risk_skill"
    description: str = (
        "Evaluates merchant category risk tiers (e.g., gambling, crypto/quasi-cash, wire transfers) "
        "and historical rejection rates via check_merchant_risk_tool."
    )

    def get_langchain_tool(self) -> BaseTool:
        """Return the underlying LangChain BaseTool for LLM tool binding."""
        return check_merchant_risk_tool

    async def execute(
        self,
        merchant_id: str,
        mcc: str,
        db_path: str | Path | None = None,
    ) -> tuple[dict[str, Any], list[RiskFactor], str]:
        """Invoke check_merchant_risk_tool and evaluate merchant risk factors.

        Returns:
            Tuple of (merchant_dict, merchant_risk_factors, tool_name_invoked).
        """
        payload: dict[str, Any] = {"merchant_id": merchant_id, "mcc": mcc}
        if db_path is not None:
            payload["db_path"] = str(db_path)

        merch_res: dict[str, Any] = await check_merchant_risk_tool.ainvoke(payload)
        risk_factors: list[RiskFactor] = []

        is_high_risk_mcc = bool(merch_res.get("is_high_risk_mcc", False))
        merch_score = float(merch_res.get("merchant_risk_score", 0.0))
        category_desc = str(merch_res.get("category_description", "Unknown Category"))

        if is_high_risk_mcc:
            risk_factors.append(
                RiskFactor(
                    category="MERCHANT_RISK",
                    severity="HIGH",
                    contribution_score=round(merch_score * 0.25, 2),
                    description=f"Merchant MCC {mcc} belongs to high-risk category: {category_desc}.",
                    details=merch_res,
                )
            )

        return merch_res, risk_factors, check_merchant_risk_tool.name
