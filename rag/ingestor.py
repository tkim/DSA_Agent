"""
RAG ingestor - reads platform docs from rag/docs/{platform}/, chunks them,
embeds with SentenceTransformer (CPU), and upserts into ChromaDB.

CLI:
    python -m rag.ingestor --platform databricks
    python -m rag.ingestor --all
    python -m rag.ingestor --all --force
"""
from __future__ import annotations

import argparse
import os
from html.parser import HTMLParser
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PLATFORMS = ("databricks", "snowflake", "aws")
DOC_EXTS = (".md", ".mdx", ".txt", ".rst", ".html")


class _HTMLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


def _strip_html(raw: str) -> str:
    parser = _HTMLStripper()
    parser.feed(raw)
    return parser.text()


def _read_doc(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix.lower() == ".html":
        return _strip_html(raw)
    return raw


def ingest_platform_docs(platform: str, force: bool = False) -> int:
    """Returns number of chunks ingested."""
    # Lazy imports so --help works without heavy deps installed.
    import chromadb
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
    except ImportError:  # old langchain
        from langchain.text_splitter import RecursiveCharacterTextSplitter
    from sentence_transformers import SentenceTransformer
    from rich.console import Console
    from rich.table import Table

    console = Console()

    chunk_size = int(os.getenv("RAG_CHUNK_SIZE", "512"))
    chunk_overlap = int(os.getenv("RAG_CHUNK_OVERLAP", "64"))
    embed_model_name = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")
    chroma_dir = os.getenv("CHROMA_PERSIST_DIR", "./rag/chroma_db")

    docs_dir = Path("rag") / "docs" / platform
    if not docs_dir.exists():
        console.print(f"[yellow]No docs directory at {docs_dir}. Run rag/fetch_docs.ps1.[/]")
        return 0

    client = chromadb.PersistentClient(path=str(Path(chroma_dir)))
    collection_name = f"cloud_agents_{platform}"

    existing = {c.name for c in client.list_collections()}
    if collection_name in existing and not force:
        console.print(f"[yellow]Collection {collection_name} already exists. Use --force to reingest.[/]")
        return 0
    if collection_name in existing and force:
        client.delete_collection(collection_name)

    collection = client.create_collection(collection_name)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    model = SentenceTransformer(embed_model_name, device="cpu")

    files = [p for p in docs_dir.rglob("*") if p.is_file() and p.suffix.lower() in DOC_EXTS]
    if not files:
        console.print(f"[yellow]No doc files found under {docs_dir}[/]")
        return 0

    table = Table(title=f"Ingest: {platform}")
    table.add_column("File")
    table.add_column("Chunks", justify="right")

    total = 0
    for f in files:
        text = _read_doc(f)
        chunks = splitter.split_text(text)
        if not chunks:
            table.add_row(str(f.relative_to(docs_dir)), "0")
            continue

        embeddings = model.encode(chunks, show_progress_bar=False, normalize_embeddings=True)
        ids = [f"{f.name}::{i}" for i in range(len(chunks))]
        metadatas = [
            {"source": str(f), "platform": platform, "chunk_index": i}
            for i in range(len(chunks))
        ]
        # Chroma rejects batches above ~5461 records — upsert in chunks.
        BATCH = 4000
        emb_lists = [e.tolist() for e in embeddings]
        for i in range(0, len(chunks), BATCH):
            collection.upsert(
                ids=ids[i:i + BATCH],
                documents=chunks[i:i + BATCH],
                embeddings=emb_lists[i:i + BATCH],
                metadatas=metadatas[i:i + BATCH],
            )
        table.add_row(str(f.relative_to(docs_dir)), str(len(chunks)))
        total += len(chunks)

    console.print(table)
    console.print(f"[green]Ingested {total} chunks into {collection_name}[/]")
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest platform docs into ChromaDB")
    parser.add_argument("--platform", choices=PLATFORMS, help="Single platform to ingest")
    parser.add_argument("--all", action="store_true", help="Ingest all platforms")
    parser.add_argument("--force", action="store_true", help="Re-ingest if collection exists")
    args = parser.parse_args()

    if not args.platform and not args.all:
        parser.error("Supply --platform <name> or --all")

    targets = PLATFORMS if args.all else (args.platform,)
    grand_total = 0
    for p in targets:
        grand_total += ingest_platform_docs(p, force=args.force)
    print(f"Total chunks ingested: {grand_total}")


if __name__ == "__main__":
    main()
