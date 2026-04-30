"""
Ingest plaintext/markdown compendium files into AI DM SQLite for RAG.

Usage:
  python -m ai_dm.ingest_compendium \
    --source-title "DND 5.5e Manual" \
    --edition "5.5e" \
    --doc-title "PHB Excerpts" \
    --file path/to/file.md

You can repeat --file multiple times.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from ai_dm.db import get_conn, init_db


def slugify(value: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    return s.strip("-") or "doc"


def chunk_text(text: str, max_chars: int = 1200, overlap: int = 150) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks = []
    i = 0
    n = len(text)
    while i < n:
        j = min(n, i + max_chars)
        if j < n:
            cut = text.rfind("\n", i, j)
            if cut > i + max_chars // 2:
                j = cut
        chunk = text[i:j].strip()
        if chunk:
            chunks.append(chunk)
        if j >= n:
            break
        i = max(0, j - overlap)
    return chunks


def split_sections(markdown: str) -> list[tuple[str, str]]:
    """Return list of (heading, content)."""
    lines = markdown.splitlines()
    sections: list[tuple[str, list[str]]] = []
    current_heading = "(root)"
    current_lines: list[str] = []

    for line in lines:
        if line.startswith("#"):
            if current_lines:
                sections.append((current_heading, current_lines))
            current_heading = line.lstrip("#").strip() or "(untitled)"
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_heading, current_lines))

    out = []
    for heading, content_lines in sections:
        content = "\n".join(content_lines).strip()
        if content:
            out.append((heading, content))
    return out


def infer_entity_type(heading: str) -> str | None:
    h = heading.lower()
    if "monster" in h or "beast" in h or "stat block" in h:
        return "monster"
    if "condition" in h:
        return "condition"
    if "dm" in h or "technique" in h or "adjudicat" in h:
        return "technique"
    if "lore" in h or "history" in h or "setting" in h:
        return "lore"
    if "rule" in h:
        return "rule"
    return None


def ingest_file(conn, source_id: int, doc_title: str, path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    doc_slug = slugify(f"{doc_title}-{path.stem}")

    cur = conn.execute(
        "INSERT INTO comp_documents (source_id, title, slug, hash) VALUES (?, ?, ?, ?)",
        (source_id, f"{doc_title} / {path.name}", doc_slug, digest),
    )
    doc_id = cur.lastrowid

    sec_idx = 0
    chunk_count = 0
    for heading, section_text in split_sections(text):
        sec_idx += 1
        sec_cur = conn.execute(
            "INSERT INTO comp_sections (document_id, section_path, heading) VALUES (?, ?, ?)",
            (doc_id, f"{sec_idx}", heading),
        )
        section_id = sec_cur.lastrowid

        etype = infer_entity_type(heading)
        if etype:
            conn.execute(
                """
                INSERT INTO comp_entities (entity_type, name, slug, aliases_json, raw_json, section_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    etype,
                    heading,
                    slugify(heading),
                    json.dumps([]),
                    json.dumps({"source_file": str(path), "heading": heading}),
                    section_id,
                ),
            )

        for i, ch in enumerate(chunk_text(section_text), start=1):
            citation = f"{path.name} :: {heading} :: chunk {i}"
            conn.execute(
                """
                INSERT INTO comp_chunks (section_id, chunk_index, text, citation, token_count)
                VALUES (?, ?, ?, ?, ?)
                """,
                (section_id, i, ch, citation, max(1, len(ch) // 4)),
            )
            chunk_count += 1

    return {"doc_id": doc_id, "sections": sec_idx, "chunks": chunk_count}


def main():
    parser = argparse.ArgumentParser(description="Ingest DnD compendium files into SQLite RAG tables")
    parser.add_argument("--source-title", required=True)
    parser.add_argument("--edition", default="")
    parser.add_argument("--version", default="")
    parser.add_argument("--doc-title", required=True)
    parser.add_argument("--file", action="append", required=True, help="Path to .md/.txt file")
    args = parser.parse_args()

    init_db()
    with get_conn() as conn:
        src = conn.execute(
            "INSERT INTO comp_sources (title, edition, version) VALUES (?, ?, ?)",
            (args.source_title, args.edition or None, args.version or None),
        )
        source_id = src.lastrowid

        total_docs = 0
        total_chunks = 0
        for f in args.file:
            p = Path(f)
            if not p.exists() or not p.is_file():
                print(f"skip: {p} does not exist")
                continue
            result = ingest_file(conn, source_id, args.doc_title, p)
            total_docs += 1
            total_chunks += result["chunks"]
            print(f"ingested {p.name}: sections={result['sections']} chunks={result['chunks']}")

        conn.commit()

    print(f"done: source_id={source_id} docs={total_docs} chunks={total_chunks}")


if __name__ == "__main__":
    main()
