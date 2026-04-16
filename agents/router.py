"""
Router: keyword classifier with LLM fallback.
Returns one of: 'databricks', 'snowflake', 'aws', or 'ambiguous'.
"""
from __future__ import annotations

import os

import ollama

OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
ROUTER_MODEL = os.getenv("ROUTER_MODEL", "gemma4-agent")

KEYWORDS = {
    "databricks": {
        "databricks", "unity catalog", "delta lake", "delta table", "mlflow",
        "mosaic ai", "dbfs", "dlt", "lakeflow", "autoloader", "dbsql",
        "databricks sql", "medallion", "lakehouse",
    },
    "snowflake": {
        "snowflake", "cortex", "snowpark", "iceberg", "snowpipe",
        "virtual warehouse", "time travel", "zero-copy clone", "tasks",
        "streams", "dynamic tables", "cortex analyst",
    },
    "aws": {
        "aws", "amazon", "s3", "glue", "bedrock", "lambda", "ec2", "ecs",
        "iam", "cloudformation", "cdk", "sagemaker", "athena", "redshift",
        "step functions", "sns", "sqs", "kinesis", "lakeformation", "boto3",
    },
}

# Strong identifiers score 2x — resolves ties where a generic term
# (e.g. "time travel") appears alongside a platform-specific product name.
STRONG_KEYWORDS = {
    "databricks": {
        "databricks", "unity catalog", "delta lake", "delta table", "mlflow",
        "dlt", "lakeflow", "dbsql", "databricks sql",
    },
    "snowflake": {"snowflake", "cortex", "snowpark", "snowpipe", "cortex analyst"},
    "aws": {
        "aws", "amazon", "bedrock", "boto3", "cloudformation",
        "sagemaker", "athena", "redshift", "lakeformation",
    },
}

LLM_PROMPT = (
    "Classify this cloud infrastructure query into exactly one of: "
    "databricks, snowflake, aws.\n"
    "Reply with ONLY the category name, lowercase, nothing else.\n\n"
    "Query: {query}\nCategory:"
)


class Router:
    def __init__(self, model: str = ROUTER_MODEL):
        self.model = model
        self.client = ollama.Client(host=OLLAMA_BASE)

    def route(self, query: str) -> str:
        """Returns 'databricks' | 'snowflake' | 'aws' | 'ambiguous'"""
        q = query.lower()
        scores = {
            p: sum(1 for kw in kws if kw in q)
               + sum(1 for kw in STRONG_KEYWORDS.get(p, set()) if kw in q)  # +1 bonus = 2x weight
            for p, kws in KEYWORDS.items()
        }
        top = max(scores, key=scores.get)

        if scores[top] > 0 and sum(v == scores[top] for v in scores.values()) == 1:
            return top

        # LLM fallback - tiny prompt, temperature=0
        try:
            resp = self.client.chat(
                model=self.model,
                messages=[{"role": "user", "content": LLM_PROMPT.format(query=query)}],
                options={"temperature": 0.0, "num_predict": 8},
            )
            token = resp.message.content.strip().lower().split()[0] if resp.message.content else ""
        except Exception:
            return "ambiguous"
        return token if token in KEYWORDS else "ambiguous"
