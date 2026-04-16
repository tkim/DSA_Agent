"""
Databricks tool executors + Ollama tool schemas.

When DATABRICKS_HOST + DATABRICKS_TOKEN are not set, every tool returns a
realistic mock payload with "_mock": True.
"""
from __future__ import annotations

from typing import Any

from dotenv import load_dotenv

from tools._common import env_ready, run_with_timeout, tool_wrapper

load_dotenv()

_LIVE_ENV = ("DATABRICKS_HOST", "DATABRICKS_TOKEN")


def _client():
    from databricks.sdk import WorkspaceClient
    return WorkspaceClient()


# --- list_clusters -----------------------------------------------------------
@tool_wrapper("list_clusters")
def list_clusters() -> dict:
    if not env_ready(*_LIVE_ENV):
        return {
            "_mock": True,
            "clusters": [
                {"cluster_id": "0123-abc456", "state": "RUNNING",
                 "num_workers": 4, "driver_node_type": "Standard_DS3_v2"},
                {"cluster_id": "0456-def789", "state": "TERMINATED",
                 "num_workers": 2, "driver_node_type": "Standard_DS3_v2"},
            ],
        }

    def _live():
        w = _client()
        return [
            {
                "cluster_id": c.cluster_id,
                "state": str(c.state),
                "num_workers": c.num_workers or 0,
                "driver_node_type": c.driver_node_type_id,
            }
            for c in w.clusters.list()
        ]

    return {"clusters": run_with_timeout(_live)}


# --- get_cluster_status ------------------------------------------------------
@tool_wrapper("get_cluster_status")
def get_cluster_status(cluster_id: str) -> dict:
    if not env_ready(*_LIVE_ENV):
        return {
            "_mock": True,
            "state": "RUNNING",
            "cluster_id": cluster_id,
            "driver": "Standard_DS3_v2",
            "num_workers": 4,
            "uptime_s": 3600,
        }

    def _live():
        w = _client()
        c = w.clusters.get(cluster_id=cluster_id)
        return {
            "state": str(c.state),
            "cluster_id": c.cluster_id,
            "driver": c.driver_node_type_id,
            "num_workers": c.num_workers or 0,
            "uptime_s": 0,
        }

    return run_with_timeout(_live)


# --- run_sql_statement -------------------------------------------------------
@tool_wrapper("run_sql_statement")
def run_sql_statement(sql: str, warehouse_id: str) -> dict:
    if not env_ready(*_LIVE_ENV):
        return {
            "_mock": True,
            "rows": [["main", "bronze", "events"], ["main", "bronze", "users"]],
            "column_names": ["catalog", "schema", "table"],
            "row_count": 2,
        }

    def _live():
        w = _client()
        resp = w.statement_execution.execute_statement(
            statement=sql, warehouse_id=warehouse_id
        )
        data = resp.result.data_array if resp.result else []
        cols = [c.name for c in (resp.manifest.schema.columns if resp.manifest else [])]
        return {"rows": data or [], "column_names": cols, "row_count": len(data or [])}

    return run_with_timeout(_live)


# --- list_uc_tables ----------------------------------------------------------
@tool_wrapper("list_uc_tables")
def list_uc_tables(catalog: str, schema: str) -> dict:
    if not env_ready(*_LIVE_ENV):
        return {
            "_mock": True,
            "tables": [
                {"name": "events", "table_type": "MANAGED", "owner": "data-eng@acme.com"},
                {"name": "users",  "table_type": "MANAGED", "owner": "data-eng@acme.com"},
                {"name": "orders", "table_type": "EXTERNAL", "owner": "data-eng@acme.com"},
            ],
            "catalog": catalog,
            "schema": schema,
        }

    def _live():
        w = _client()
        return [
            {"name": t.name, "table_type": str(t.table_type), "owner": t.owner}
            for t in w.tables.list(catalog_name=catalog, schema_name=schema)
        ]

    return {"tables": run_with_timeout(_live), "catalog": catalog, "schema": schema}


# --- get_uc_table_details ----------------------------------------------------
@tool_wrapper("get_uc_table_details")
def get_uc_table_details(catalog: str, schema: str, table: str) -> dict:
    if not env_ready(*_LIVE_ENV):
        return {
            "_mock": True,
            "columns": [
                {"name": "id", "type": "BIGINT"},
                {"name": "created_at", "type": "TIMESTAMP"},
                {"name": "payload", "type": "STRING"},
            ],
            "row_count": 1_250_000,
            "owner": "data-eng@acme.com",
        }

    def _live():
        w = _client()
        t = w.tables.get(full_name=f"{catalog}.{schema}.{table}")
        return {
            "columns": [{"name": c.name, "type": str(c.type_text)} for c in (t.columns or [])],
            "row_count": 0,
            "owner": t.owner,
        }

    return run_with_timeout(_live)


# --- list_mlflow_experiments -------------------------------------------------
@tool_wrapper("list_mlflow_experiments")
def list_mlflow_experiments() -> dict:
    if not env_ready(*_LIVE_ENV):
        return {
            "_mock": True,
            "experiments": [
                {"experiment_id": "1001", "name": "fx_model_v2", "lifecycle_stage": "active"},
                {"experiment_id": "1002", "name": "churn_model", "lifecycle_stage": "active"},
            ],
        }

    def _live():
        w = _client()
        return [
            {"experiment_id": e.experiment_id, "name": e.name,
             "lifecycle_stage": str(e.lifecycle_stage)}
            for e in w.experiments.list_experiments()
        ]

    return {"experiments": run_with_timeout(_live)}


# --- get_mlflow_run ----------------------------------------------------------
@tool_wrapper("get_mlflow_run")
def get_mlflow_run(run_id: str) -> dict:
    if not env_ready(*_LIVE_ENV):
        return {
            "_mock": True,
            "params": {"lr": "0.01", "epochs": "20"},
            "metrics": {"val_accuracy": 0.962, "loss": 0.031},
            "tags": {"stage": "prod-candidate"},
            "artifact_uri": f"dbfs:/mlflow/{run_id}/artifacts",
        }

    def _live():
        w = _client()
        r = w.experiments.get_run(run_id=run_id)
        run = r.run
        return {
            "params": {p.key: p.value for p in (run.data.params or [])},
            "metrics": {m.key: m.value for m in (run.data.metrics or [])},
            "tags": {t.key: t.value for t in (run.data.tags or [])},
            "artifact_uri": run.info.artifact_uri,
        }

    return run_with_timeout(_live)


# --- list_jobs ---------------------------------------------------------------
@tool_wrapper("list_jobs")
def list_jobs(limit: int = 20) -> dict:
    if not env_ready(*_LIVE_ENV):
        return {
            "_mock": True,
            "jobs": [
                {"job_id": 111, "name": "nightly-etl", "schedule": "0 2 * * *"},
                {"job_id": 222, "name": "hourly-ingest", "schedule": "0 * * * *"},
            ][:limit],
        }

    def _live():
        w = _client()
        jobs = list(w.jobs.list(limit=limit))
        return [
            {"job_id": j.job_id, "name": j.settings.name if j.settings else None,
             "schedule": (j.settings.schedule.quartz_cron_expression
                          if j.settings and j.settings.schedule else None)}
            for j in jobs
        ]

    return {"jobs": run_with_timeout(_live)}


# --- trigger_job_run ---------------------------------------------------------
@tool_wrapper("trigger_job_run")
def trigger_job_run(job_id: int) -> dict:
    if not env_ready(*_LIVE_ENV):
        return {"_mock": True, "run_id": 99999, "state": "PENDING", "job_id": job_id}

    def _live():
        w = _client()
        run = w.jobs.run_now(job_id=int(job_id)).result()
        return {"run_id": run.run_id, "state": str(run.state.life_cycle_state)}

    return run_with_timeout(_live)


# --- schemas + executor map --------------------------------------------------
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_clusters",
            "description": "List all Databricks clusters in the workspace",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_cluster_status",
            "description": "Get the current state of a Databricks cluster",
            "parameters": {
                "type": "object",
                "properties": {"cluster_id": {"type": "string"}},
                "required": ["cluster_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_sql_statement",
            "description": "Run a SQL statement on a Databricks SQL warehouse",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string"},
                    "warehouse_id": {"type": "string"},
                },
                "required": ["sql", "warehouse_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_uc_tables",
            "description": "List Unity Catalog tables in a schema",
            "parameters": {
                "type": "object",
                "properties": {
                    "catalog": {"type": "string"},
                    "schema": {"type": "string"},
                },
                "required": ["catalog", "schema"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_uc_table_details",
            "description": "Get columns and metadata for a Unity Catalog table",
            "parameters": {
                "type": "object",
                "properties": {
                    "catalog": {"type": "string"},
                    "schema": {"type": "string"},
                    "table": {"type": "string"},
                },
                "required": ["catalog", "schema", "table"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_mlflow_experiments",
            "description": "List MLflow experiments",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_mlflow_run",
            "description": "Get parameters, metrics and tags for an MLflow run",
            "parameters": {
                "type": "object",
                "properties": {"run_id": {"type": "string"}},
                "required": ["run_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_jobs",
            "description": "List Databricks jobs",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 20}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trigger_job_run",
            "description": "Trigger a run of a Databricks job now",
            "parameters": {
                "type": "object",
                "properties": {"job_id": {"type": "integer"}},
                "required": ["job_id"],
            },
        },
    },
]


TOOL_EXECUTORS = {
    "list_clusters": list_clusters,
    "get_cluster_status": get_cluster_status,
    "run_sql_statement": run_sql_statement,
    "list_uc_tables": list_uc_tables,
    "get_uc_table_details": get_uc_table_details,
    "list_mlflow_experiments": list_mlflow_experiments,
    "get_mlflow_run": get_mlflow_run,
    "list_jobs": list_jobs,
    "trigger_job_run": trigger_job_run,
}
