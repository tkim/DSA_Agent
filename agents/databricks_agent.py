from agents.base_agent import BaseAgent
from tools.databricks_tools import TOOL_EXECUTORS, TOOL_SCHEMAS


class DatabricksAgent(BaseAgent):
    platform = "databricks"
    tool_schemas = TOOL_SCHEMAS
    tool_executors = TOOL_EXECUTORS
    system_template = (
        "You are a Databricks specialist. You know Unity Catalog three-part naming "
        "(catalog.schema.table), Delta Lake ACID guarantees and time travel, MLflow "
        "experiment tracking and model registry, Structured Streaming checkpoints, "
        "and LakeFlow DLT pipelines. Security: never grant ALL PRIVILEGES broadly.\n\n"
        "Use the registered tools to answer the user's question. If a tool can answer "
        "the request, call it; do not describe what you would do.\n\n"
        "Platform documentation context:\n{rag_context}"
    )

    def register_tools(self):
        # class-level attrs handle registration
        pass
