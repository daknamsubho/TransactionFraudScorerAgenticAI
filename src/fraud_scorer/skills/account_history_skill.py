"""Account History Retrieval Skill (`src/fraud_scorer/skills/account_history_skill.py`)."""

from typing import Any

from langchain_core.tools import BaseTool

from fraud_scorer.agents.tools import lookup_account_history_tool
from fraud_scorer.models.transaction import RiskFactor


class AccountHistorySkill:
    """Skill for retrieving customer account history and evaluating account-level risk signals."""

    name: str = "account_history_skill"
    description: str = (
        "Retrieves account age, prior chargeback disputes, historical average transaction amount, "
        "and trust tier via LangChain MCP tool adapter and evaluates ACCOUNT_HISTORY risk factors."
    )

    def get_langchain_tool(self) -> BaseTool:
        """Return the underlying LangChain BaseTool for LLM tool binding."""
        return lookup_account_history_tool

    async def execute(self, account_id: str) -> tuple[dict[str, Any], list[RiskFactor], str]:
        """Invoke lookup_account_history_tool and evaluate account history risk factors.

        Returns:
            Tuple of (account_history_dict, account_risk_factors, tool_name_invoked).
        """
        hist_res: dict[str, Any] = await lookup_account_history_tool.ainvoke(
            {"account_id": account_id}
        )
        risk_factors: list[RiskFactor] = []

        trust_tier = str(hist_res.get("trust_tier", "new"))
        prior_disputes = int(hist_res.get("prior_disputes", 0))
        account_age_days = int(hist_res.get("account_age_days", 0))

        if trust_tier == "untrusted" or prior_disputes > 0:
            risk_factors.append(
                RiskFactor(
                    category="ACCOUNT_HISTORY",
                    severity="HIGH",
                    contribution_score=20.0,
                    description=(
                        f"Account age is {account_age_days} days with "
                        f"{prior_disputes} prior fraud disputes (trust_tier='{trust_tier}')."
                    ),
                    details=hist_res,
                )
            )

        return hist_res, risk_factors, lookup_account_history_tool.name
