from travel_risk.config import get_settings
from travel_risk.llm.base import RiskModel


def get_model() -> RiskModel:
    s = get_settings()
    if s.model_provider == "claude":
        from travel_risk.llm.claude import ClaudeRiskModel

        return ClaudeRiskModel(model=s.claude_model, effort=s.claude_effort)
    from travel_risk.llm.heuristic import HeuristicRiskModel

    return HeuristicRiskModel()
