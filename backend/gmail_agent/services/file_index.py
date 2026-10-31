from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from ..db import Database, utc_now


SUPPORTED_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".pdf", ".log"}
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 1_000_000


class LocalFileIndex:
    def __init__(self, db: Database, root: Path):
        self.db = db
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def index(self) -> dict[str, Any]:
        indexed = skipped = 0
        errors: list[str] = []
        seen_paths: set[str] = set()
        for path in self.root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            try:
                resolved = path.resolve()
                if self.root not in resolved.parents:
                    skipped += 1
                    continue
                if path.stat().st_size > MAX_FILE_BYTES:
                    errors.append(f"Skipped {path.name}: file exceeds 10 MB limit.")
                    continue
                text = self._extract(path)[:MAX_TEXT_CHARS]
                if not text.strip():
                    skipped += 1
                    continue
                relative = resolved.relative_to(self.root).as_posix()
                seen_paths.add(relative)
                modified = path.stat().st_mtime
                from datetime import datetime, timezone
                modified_iso = datetime.fromtimestamp(modified, tz=timezone.utc).isoformat()
                self.db.execute(
                    "INSERT INTO file_index(relative_path,filename,content,modified_at,indexed_at) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(relative_path) DO UPDATE SET filename=excluded.filename,content=excluded.content,modified_at=excluded.modified_at,indexed_at=excluded.indexed_at",
                    (relative, path.name, text, modified_iso, utc_now()),
                )
                indexed += 1
            except Exception as exc:
                errors.append(f"Could not index {path.name}: {type(exc).__name__}")
        # Remove stale records for files that were deleted or are no longer supported.
        for row in self.db.fetch_all("SELECT relative_path FROM file_index"):
            if row["relative_path"] not in seen_paths:
                self.db.execute("DELETE FROM file_index WHERE relative_path=?", (row["relative_path"],))
        return {"indexed": indexed, "skipped": skipped, "errors": errors[:20]}

    @staticmethod
    def _extract(path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        if suffix == ".json":
            return json.dumps(json.loads(path.read_text(encoding="utf-8", errors="replace")), ensure_ascii=False, indent=2)
        if suffix == ".csv":
            with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
                return "\n".join(", ".join(row) for row in csv.reader(handle))
        return path.read_text(encoding="utf-8", errors="replace")

    def search(self, query: str, limit: int = 10) -> list[dict[str, str]]:
        tokens = [token.lower() for token in query.split() if len(token) > 1][:12]
        if not tokens:
            return []
        rows = self.db.fetch_all("SELECT relative_path,filename,content,modified_at FROM file_index")
        results: list[tuple[int, dict[str, str]]] = []
        for row in rows:
            content = (row["content"] or "").lower()
            filename = (row["filename"] or "").lower()
            score = sum(content.count(token) + 4 * filename.count(token) for token in tokens)
            if score:
                index = min((content.find(token) for token in tokens if content.find(token) >= 0), default=0)
                start = max(0, index - 160)
                excerpt = (row["content"] or "")[start:start + 500].replace("\n", " ")
                results.append((score, {"relative_path": row["relative_path"], "filename": row["filename"], "excerpt": excerpt, "modified_at": row["modified_at"]}))
        results.sort(key=lambda result: result[0], reverse=True)
        return [item for _, item in results[:max(1, min(limit, 50))]]
