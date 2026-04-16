from agents.base_agent import BaseAgent
from tools.snowflake_tools import TOOL_EXECUTORS, TOOL_SCHEMAS


class SnowflakeAgent(BaseAgent):
    platform = "snowflake"
    tool_schemas = TOOL_SCHEMAS
    tool_executors = TOOL_EXECUTORS
    system_template = (
        "You are a Snowflake specialist. You know Cortex AI (COMPLETE, EMBED_TEXT, "
        "EXTRACT_ANSWER), Snowpark Python UDFs and stored procedures, Iceberg external "
        "tables, virtual warehouse cost optimization, clustering keys and materialized "
        "views. SQL rule: always include LIMIT on SELECT queries.\n\n"
        "Use the registered tools to answer the user's question. If a tool can answer "
        "the request, call it; do not describe what you would do.\n\n"
        "Platform documentation context:\n{rag_context}"
    )

    def register_tools(self):
        pass
