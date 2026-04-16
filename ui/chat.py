"""
Launch: python ui\chat.py
Opens:  http://localhost:7860
"""
import gradio as gr

from orchestrator.pipeline import AgentPipeline


def respond(message: str, history: list, platform: str) -> str:
    override = None if platform == "auto" else platform
    result = AgentPipeline.get().run(message, platform_override=override)

    body = result["response"]
    tools = ", ".join(t["name"] for t in result.get("tool_calls_made", []))
    # Use forward slash for display even on Windows paths
    sources = ", ".join(
        r["source"].replace("\\", "/").split("/")[-1]
        for r in result.get("rag_sources", [])[:3]
    )
    footer = [
        f"**Platform:** `{result['platform']}`",
        f"**Latency:** {result['latency_ms']}ms",
    ]
    if tools:
        footer.append(f"**Tools:** {tools}")
    if sources:
        footer.append(f"**RAG:** {sources}")

    return body + "\n\n---\n" + " | ".join(footer)


with gr.Blocks(title="Cloud Agent") as demo:
    gr.Markdown(
        "## Cloud Platform Agent\n"
        "Gemma 4 26B A4B - AMD Ryzen AI MAX+ 395 - Windows 11 - Vulkan\n"
        "Databricks / Snowflake / AWS"
    )
    with gr.Row():
        sel = gr.Dropdown(
            choices=["auto", "databricks", "snowflake", "aws"],
            value="auto", label="Platform override", scale=1,
        )
        rst = gr.Button("New session", variant="secondary", scale=1)

    gr.ChatInterface(
        fn=lambda msg, hist: respond(msg, hist, sel.value),
        examples=[
            "List all tables in the bronze schema of the main catalog",
            "What Snowflake virtual warehouses are running right now?",
            "List my S3 buckets and their regions",
            "Show recent MLflow runs with validation accuracy above 0.95",
            "What Bedrock models are available in us-east-1?",
        ],
    )
    rst.click(fn=lambda: AgentPipeline.get().reset())


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, theme=gr.themes.Soft())
