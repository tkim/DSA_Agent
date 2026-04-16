import os

from agents.aws_agent import AWSAgent
from agents.databricks_agent import DatabricksAgent
from agents.router import Router
from agents.snowflake_agent import SnowflakeAgent
from orchestrator.session import Session

AGENT_MODEL = os.getenv("AGENT_MODEL", "gemma4-agent")
_AMBIGUOUS = (
    "I wasn't sure whether this relates to Databricks, Snowflake, or AWS. "
    "Could you mention the platform, or use the dropdown selector in the UI?"
)


class AgentPipeline:
    _instance = None

    def __init__(self):
        self.router = Router()
        self.agents = {
            "databricks": DatabricksAgent(model=AGENT_MODEL),
            "snowflake":  SnowflakeAgent(model=AGENT_MODEL),
            "aws":        AWSAgent(model=AGENT_MODEL),
        }
        self.session = Session()

    def run(self, query: str, platform_override: str | None = None) -> dict:
        platform = platform_override or self.router.route(query)
        if platform == "ambiguous":
            return {"platform": "ambiguous", "response": _AMBIGUOUS,
                    "tool_calls_made": [], "rag_sources": [], "latency_ms": 0}
        result = self.agents[platform].run(query, self.session.get_history())
        result["platform"] = platform
        self.session.append(query, result["response"])
        return result

    def reset(self):
        self.session.clear()

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
