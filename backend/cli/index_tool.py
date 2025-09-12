import argparse
import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional

# absolute imports relative to package root
from backend.services import kb_manager, indexer

logger = logging.getLogger("backend.cli.index_tool")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def read_text_from_file(p: Path) -> str:
    """
    Best-effort text extraction for simple file types.
    - .txt, .md => raw text
    - .html => strip tags
    - .pdf => try PyPDF2 if available, otherwise return empty
    """
    try:
        suf = p.suffix.lower()
        if suf in (".txt", ".md", ".rst"):
            return p.read_text(encoding="utf-8", errors="ignore")
        if suf in (".html", ".htm"):
            raw = p.read_text(encoding="utf-8", errors="ignore")
            return re.sub(r"<[^>]+>", " ", raw)
        if suf == ".pdf":
            try:
                import PyPDF2  # type: ignore

                text_parts: List[str] = []
                with open(p, "rb") as fh:
                    reader = PyPDF2.PdfReader(fh)
                    for page in reader.pages:
                        try:
                            text_parts.append(page.extract_text() or "")
                        except Exception:
                            continue
                return "\n".join(text_parts)
            except Exception:
                logger.warning("PyPDF2 not available or failed to read PDF: %s", p)
                return ""
        # fallback: try reading as text
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        logger.debug("Failed to read file %s: %s", p, e)
        return ""


def discover_files(source: Path, exts: List[str], recursive: bool) -> List[Path]:
    exts_l = [e.lower() if e.startswith(".") else f".{e.lower()}" for e in exts]
    if source.is_file():
        return [source] if source.suffix.lower() in exts_l else []
    files: List[Path] = []
    if recursive:
        for p in source.rglob("*"):
            if p.suffix.lower() in exts_l and p.is_file():
                files.append(p)
    else:
        for p in source.iterdir():
            if p.suffix.lower() in exts_l and p.is_file():
                files.append(p)
    return sorted(files)


async def index_source(
    collection_name: str,
    paths: Iterable[Path],
    chunk_opts: Optional[Dict] = None,
    batch_size: int = 64,
    create_if_missing: bool = True,
    dry_run: bool = False,
) -> Dict:
    docs = []
    for p in paths:
        text = read_text_from_file(p)
        if not text or len(text.strip()) == 0:
            logger.info("Skipping empty/unreadable file: %s", p)
            continue
        doc = {"id": str(p.name), "text": text, "metadata": {"path": str(p.resolve())}}
        docs.append(doc)

    logger.info("Discovered %d document(s) to index", len(docs))
    if dry_run:
        # show brief summary
        sizes = [(d["id"], len(d["text"])) for d in docs[:20]]
        for name, size in sizes:
            logger.info(" - %s (%d chars)", name, size)
        return {"discovered": len(docs)}

    # ensure collection exists if requested
    if create_if_missing:
        try:
            await kb_manager.create_kb(name=collection_name)
        except Exception:
            # ignore if already exists or create fails (kb_manager will upsert into chroma)
            logger.debug("create_kb failed or collection exists; continuing")

    # use KB manager (handles chunk -> embed -> upsert)
    resp = await kb_manager.add_documents(collection_name=collection_name, docs=docs, chunk_opts=chunk_opts, batch_size=batch_size)
    return resp


def parse_chunk_opts(arg: Optional[str]) -> Dict:
    if not arg:
        return {"max_tokens": 512, "overlap": 64}
    # expect comma separated key=value pairs
    out = {}
    for part in arg.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            try:
                out[k.strip()] = int(v.strip())
            except Exception:
                out[k.strip()] = v.strip()
    return out


def main():
    ap = argparse.ArgumentParser(description="Index local files/folders into a KB (Chroma) via KBManager")
    ap.add_argument("source", type=str, help="File or directory to index")
    ap.add_argument("--collection", "-c", required=True, help="Target KB collection name")
    ap.add_argument("--exts", type=str, default="txt,md,pdf,html", help="Comma-separated file extensions to include (default: txt,md,pdf,html)")
    ap.add_argument("--recursive", "-r", action="store_true", help="Recursively scan directories")
    ap.add_argument("--chunk-opts", type=str, default=None, help="Chunk options, e.g. max_tokens=512,overlap=64")
    ap.add_argument("--batch-size", type=int, default=64, help="Embedding/upsert batch size")
    ap.add_argument("--dry-run", action="store_true", help="Don't index; only show discovered files")
    ap.add_argument("--no-create", action="store_true", help="Don't attempt to create collection before indexing")
    args = ap.parse_args()

    src = Path(args.source).expanduser().resolve()
    if not src.exists():
        logger.error("Source path does not exist: %s", src)
        raise SystemExit(1)

    exts = [e.strip() for e in args.exts.split(",") if e.strip()]
    files = discover_files(src, exts=exts, recursive=args.recursive)
    if not files:
        logger.error("No files found matching extensions %s under %s", exts, src)
        raise SystemExit(1)

    chunk_opts = parse_chunk_opts(args.chunk_opts)
    create_if_missing = not args.no_create

    async def _run():
        resp = await index_source(
            collection_name=args.collection,
            paths=files,
            chunk_opts=chunk_opts,
            batch_size=args.batch_size,
            create_if_missing=create_if_missing,
            dry_run=args.dry_run,
        )
        logger.info("Indexing result: %s", resp)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")


if __name__ == "__main__":
    main()
