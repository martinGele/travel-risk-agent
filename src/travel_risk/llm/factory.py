from travel_risk.config import get_settings
from travel_risk.llm.base import RiskModel


def get_model() -> RiskModel:
    s = get_settings()
    if s.model_provider == "claude":
        import anthropic

        from travel_risk.llm.claude import ClaudeRiskModel

        key = s.anthropic_api_key.get_secret_value() if s.anthropic_api_key else None
        client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
        return ClaudeRiskModel(model=s.claude_model, effort=s.claude_effort, client=client)
    if s.model_provider == "ollama":
        from travel_risk.llm.ollama import OllamaRiskModel

        return OllamaRiskModel(model=s.ollama_model, base_url=s.ollama_url)
    from travel_risk.llm.heuristic import HeuristicRiskModel

    return HeuristicRiskModel()
