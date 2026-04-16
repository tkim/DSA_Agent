"""
Snowflake tool executors + Ollama tool schemas.

When SNOWFLAKE_ACCOUNT/USER/PASSWORD are not set, every tool returns a mock.
"""
from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

from tools._common import env_ready, run_with_timeout, tool_wrapper

load_dotenv()

_LIVE_ENV = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD")


def _connect():
    import snowflake.connector
    return snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA"),
    )


def _fetch_rows(sql: str, limit: int | None = None) -> dict:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        cols = [c[0] for c in (cur.description or [])]
        rows = cur.fetchmany(limit) if limit else cur.fetchall()
        return {"rows": [list(r) for r in rows], "column_names": cols, "row_count": len(rows)}
    finally:
        conn.close()


# --- execute_sql -------------------------------------------------------------
@tool_wrapper("execute_sql")
def execute_sql(sql: str, limit: int = 100) -> dict:
    if not env_ready(*_LIVE_ENV):
        return {
            "_mock": True,
            "rows": [[1, "sample"], [2, "row"]],
            "column_names": ["id", "name"],
            "row_count": 2,
        }
    return run_with_timeout(_fetch_rows, sql, limit)


# --- list_databases ----------------------------------------------------------
@tool_wrapper("list_databases")
def list_databases() -> dict:
    if not env_ready(*_LIVE_ENV):
        return {
            "_mock": True,
            "databases": [
                {"name": "ANALYTICS", "created_on": "2024-01-15T10:30:00Z", "owner": "ACCOUNTADMIN"},
                {"name": "RAW",       "created_on": "2024-01-15T10:30:00Z", "owner": "ACCOUNTADMIN"},
            ],
        }

    def _live():
        res = _fetch_rows("SHOW DATABASES")
        return [
            {"name": r[1] if len(r) > 1 else r[0], "created_on": str(r[0]), "owner": r[5] if len(r) > 5 else ""}
            for r in res["rows"]
        ]

    return {"databases": run_with_timeout(_live)}


# --- list_schemas ------------------------------------------------------------
@tool_wrapper("list_schemas")
def list_schemas(database: str) -> dict:
    if not env_ready(*_LIVE_ENV):
        return {
            "_mock": True,
            "schemas": [
                {"name": "PUBLIC",  "database_name": database},
                {"name": "BRONZE",  "database_name": database},
                {"name": "SILVER",  "database_name": database},
            ],
        }

    def _live():
        res = _fetch_rows(f"SHOW SCHEMAS IN DATABASE {database}")
        return [{"name": r[1] if len(r) > 1 else r[0], "database_name": database} for r in res["rows"]]

    return {"schemas": run_with_timeout(_live)}


# --- describe_table ----------------------------------------------------------
@tool_wrapper("describe_table")
def describe_table(database: str, schema: str, table: str) -> dict:
    if not env_ready(*_LIVE_ENV):
        return {
            "_mock": True,
            "columns": [
                {"name": "ID", "type": "NUMBER(38,0)"},
                {"name": "CREATED_AT", "type": "TIMESTAMP_NTZ"},
                {"name": "PAYLOAD", "type": "VARIANT"},
            ],
            "row_count": 987_654,
        }

    def _live():
        res = _fetch_rows(f"DESCRIBE TABLE {database}.{schema}.{table}")
        return {
            "columns": [{"name": r[0], "type": r[1]} for r in res["rows"]],
            "row_count": 0,
        }

    return run_with_timeout(_live)


# --- cortex_complete ---------------------------------------------------------
@tool_wrapper("cortex_complete")
def cortex_complete(prompt: str, model: str = "mistral-large2") -> dict:
    if not env_ready(*_LIVE_ENV):
        return {"_mock": True, "completion": f"[mock Cortex {model}] {prompt[:60]}..."}

    def _live():
        safe_prompt = prompt.replace("'", "''")
        res = _fetch_rows(f"SELECT SNOWFLAKE.CORTEX.COMPLETE('{model}', '{safe_prompt}')")
        return {"completion": res["rows"][0][0] if res["rows"] else ""}

    return run_with_timeout(_live)


# --- get_query_history -------------------------------------------------------
@tool_wrapper("get_query_history")
def get_query_history(limit: int = 10) -> dict:
    if not env_ready(*_LIVE_ENV):
        return {
            "_mock": True,
            "queries": [
                {"query_id": "01b2-3c4d", "status": "SUCCESS", "duration_ms": 1234},
                {"query_id": "01b2-5e6f", "status": "SUCCESS", "duration_ms": 5678},
            ][:limit],
        }

    def _live():
        sql = (
            "SELECT query_id, execution_status, total_elapsed_time "
            "FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(RESULT_LIMIT=>{}))"
        ).format(int(limit))
        res = _fetch_rows(sql)
        return [{"query_id": r[0], "status": r[1], "duration_ms": int(r[2] or 0)} for r in res["rows"]]

    return {"queries": run_with_timeout(_live)}


# --- list_warehouses ---------------------------------------------------------
@tool_wrapper("list_warehouses")
def list_warehouses() -> dict:
    if not env_ready(*_LIVE_ENV):
        return {
            "_mock": True,
            "warehouses": [
                {"name": "COMPUTE_WH", "state": "STARTED", "size": "X-SMALL", "auto_suspend": 300},
                {"name": "ETL_WH",     "state": "SUSPENDED", "size": "MEDIUM", "auto_suspend": 600},
            ],
        }

    def _live():
        res = _fetch_rows("SHOW WAREHOUSES")
        return [
            {"name": r[0], "state": r[1], "size": r[3] if len(r) > 3 else "",
             "auto_suspend": int(r[7]) if len(r) > 7 and r[7] else 0}
            for r in res["rows"]
        ]

    return {"warehouses": run_with_timeout(_live)}


# --- get_table_sample --------------------------------------------------------
@tool_wrapper("get_table_sample")
def get_table_sample(database: str, schema: str, table: str, n: int = 5) -> dict:
    if not env_ready(*_LIVE_ENV):
        return {
            "_mock": True,
            "rows": [[i, f"sample_{i}"] for i in range(1, n + 1)],
            "column_names": ["ID", "NAME"],
        }

    def _live():
        res = _fetch_rows(f"SELECT * FROM {database}.{schema}.{table} LIMIT {int(n)}")
        return {"rows": res["rows"], "column_names": res["column_names"]}

    return run_with_timeout(_live)


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "execute_sql",
            "description": "Execute a SQL query in Snowflake (auto-LIMIT applied)",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string"},
                    "limit": {"type": "integer", "default": 100},
                },
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_databases",
            "description": "List Snowflake databases",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_schemas",
            "description": "List schemas in a Snowflake database",
            "parameters": {
                "type": "object",
                "properties": {"database": {"type": "string"}},
                "required": ["database"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_table",
            "description": "Describe columns and types of a Snowflake table",
            "parameters": {
                "type": "object",
                "properties": {
                    "database": {"type": "string"},
                    "schema": {"type": "string"},
                    "table": {"type": "string"},
                },
                "required": ["database", "schema", "table"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cortex_complete",
            "description": "Call Snowflake Cortex COMPLETE for LLM inference inside Snowflake",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "model": {"type": "string", "default": "mistral-large2"},
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_query_history",
            "description": "Get recent Snowflake query history",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 10}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_warehouses",
            "description": "List Snowflake virtual warehouses and their state",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_table_sample",
            "description": "Return first N rows of a Snowflake table",
            "parameters": {
                "type": "object",
                "properties": {
                    "database": {"type": "string"},
                    "schema": {"type": "string"},
                    "table": {"type": "string"},
                    "n": {"type": "integer", "default": 5},
                },
                "required": ["database", "schema", "table"],
            },
        },
    },
]


TOOL_EXECUTORS = {
    "execute_sql": execute_sql,
    "list_databases": list_databases,
    "list_schemas": list_schemas,
    "describe_table": describe_table,
    "cortex_complete": cortex_complete,
    "get_query_history": get_query_history,
    "list_warehouses": list_warehouses,
    "get_table_sample": get_table_sample,
}
