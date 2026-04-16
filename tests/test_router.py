"""
Keyword-only router tests. These do not hit Ollama - they rely on unambiguous
keyword scores returning a platform before the LLM fallback is consulted.
"""
from __future__ import annotations

from agents.router import Router


def test_databricks_keyword():
    r = Router()
    assert r.route("List Unity Catalog tables in main.bronze") == "databricks"


def test_snowflake_keyword():
    r = Router()
    assert r.route("What Snowflake warehouses are running?") == "snowflake"


def test_aws_keyword():
    r = Router()
    assert r.route("List my S3 buckets and EC2 instances") == "aws"


def test_delta_lake_routes_to_databricks():
    r = Router()
    assert r.route("Explain Delta Lake time travel") == "databricks"


def test_cortex_routes_to_snowflake():
    r = Router()
    assert r.route("Use Cortex to summarize this text") == "snowflake"


def test_bedrock_routes_to_aws():
    r = Router()
    assert r.route("What Bedrock models are available?") == "aws"
