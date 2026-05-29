"""
Vector store service — per-store SQLite files with embedding search.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import struct
import uuid
from pathlib import Path
from typing import Any

from django.conf import settings

from core.models import VectorStore
from core.services import DatastoreService


class VectorstoreError(Exception):
    """Raised when vector store operations fail."""


class VectorstoreService:
    """Manage vector store SQLite databases and similarity search."""

    # Base table matches the original schema; session_id/role are added via ALTER
    # so existing SQLite files upgrade without failing on CREATE INDEX.
    BASE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS vector_chunks (
            id TEXT PRIMARY KEY,
            doc_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL DEFAULT 0,
            content TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            embedding BLOB NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """

    @classmethod
    def root_dir(cls) -> Path:
        path = Path(settings.BASE_DIR) / "data" / "vectorstores"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def sqlite_path(cls, vectorstore: VectorStore) -> Path:
        if not vectorstore.sqlite_filename:
            raise VectorstoreError("Vector store SQLite file is not initialized.")
        return cls.root_dir() / vectorstore.sqlite_filename

    @classmethod
    def connect(cls, vectorstore: VectorStore) -> sqlite3.Connection:
        conn = sqlite3.connect(str(cls.sqlite_path(vectorstore)))
        conn.row_factory = sqlite3.Row
        cls._ensure_schema(conn)
        return conn

    @classmethod
    def _ensure_schema(cls, conn: sqlite3.Connection) -> None:
        """Apply schema for new installs and upgrade older SQLite files."""
        conn.executescript(cls.BASE_TABLE_SQL)
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(vector_chunks)")
        }
        if "session_id" not in columns:
            conn.execute("ALTER TABLE vector_chunks ADD COLUMN session_id TEXT")
        if "role" not in columns:
            conn.execute("ALTER TABLE vector_chunks ADD COLUMN role TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_vector_chunks_doc_id ON vector_chunks(doc_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_vector_chunks_session_id "
            "ON vector_chunks(session_id)"
        )
        conn.commit()

    @classmethod
    def _row_to_hit(cls, row: sqlite3.Row, score: float | None = None) -> dict[str, Any]:
        hit = {
            "id": row["id"],
            "doc_id": row["doc_id"],
            "chunk_index": row["chunk_index"],
            "content": row["content"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
            "session_id": row["session_id"],
            "role": row["role"],
            "created_at": row["created_at"],
        }
        if score is not None:
            hit["score"] = score
        return hit

    @classmethod
    def initialize_store(cls, vectorstore: VectorStore) -> None:
        """Create the SQLite file and schema for a new vector store."""
        if not vectorstore.sqlite_filename:
            vectorstore.sqlite_filename = f"{vectorstore.pk}.sqlite"
            vectorstore.save(update_fields=["sqlite_filename", "updated_at"])

        db_path = cls.sqlite_path(vectorstore)
        with cls.connect(vectorstore) as conn:
            cls._ensure_schema(conn)

    @classmethod
    def delete_store_file(cls, vectorstore: VectorStore) -> None:
        if vectorstore.sqlite_filename:
            path = cls.root_dir() / vectorstore.sqlite_filename
            if path.exists():
                path.unlink()

    @classmethod
    def _pack_embedding(cls, embedding: list[float]) -> bytes:
        return struct.pack(f"{len(embedding)}f", *embedding)

    @classmethod
    def _unpack_embedding(cls, blob: bytes) -> list[float]:
        count = len(blob) // 4
        return list(struct.unpack(f"{count}f", blob))

    @classmethod
    def _validate_embedding(cls, vectorstore: VectorStore, embedding: list[float]) -> None:
        if len(embedding) != vectorstore.dimensions:
            raise VectorstoreError(
                f"Embedding length {len(embedding)} does not match store dimensions "
                f"({vectorstore.dimensions})."
            )

    @classmethod
    def _cosine_similarity(cls, a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    @classmethod
    def get_stats(cls, vectorstore: VectorStore) -> dict[str, int]:
        if not vectorstore.sqlite_filename:
            return {"chunk_count": 0, "doc_count": 0, "size_bytes": 0}

        path = cls.sqlite_path(vectorstore)
        if not path.exists():
            return {"chunk_count": 0, "doc_count": 0, "size_bytes": 0}

        with cls.connect(vectorstore) as conn:
            chunk_count = conn.execute(
                "SELECT COUNT(*) AS count FROM vector_chunks"
            ).fetchone()["count"]
            doc_count = conn.execute(
                "SELECT COUNT(DISTINCT doc_id) AS count FROM vector_chunks"
            ).fetchone()["count"]

        return {
            "chunk_count": chunk_count,
            "doc_count": doc_count,
            "size_bytes": path.stat().st_size,
        }

    @classmethod
    def get_vectorstores_with_stats(cls, workspace=None):
        qs = VectorStore.objects.all().order_by("name")
        if workspace is not None:
            qs = qs.filter(workspace=workspace)

        stores = list(qs)
        for store in stores:
            stats = cls.get_stats(store)
            store.chunk_count = stats["chunk_count"]
            store.doc_count = stats["doc_count"]
            store.size_bytes = stats["size_bytes"]
        return stores

    @classmethod
    def format_size(cls, size_bytes: int) -> str:
        return DatastoreService.format_size(size_bytes)

    @classmethod
    def list_documents(cls, vectorstore: VectorStore) -> list[dict[str, Any]]:
        with cls.connect(vectorstore) as conn:
            rows = conn.execute(
                """
                SELECT doc_id,
                       COUNT(*) AS chunk_count,
                       MAX(updated_at) AS updated_at,
                       MIN(content) AS preview
                FROM vector_chunks
                GROUP BY doc_id
                ORDER BY updated_at DESC
                """
            ).fetchall()

        return [
            {
                "doc_id": row["doc_id"],
                "chunk_count": row["chunk_count"],
                "updated_at": row["updated_at"],
                "preview": (row["preview"] or "")[:120],
            }
            for row in rows
        ]

    @classmethod
    def add_chunk(
        cls,
        vectorstore: VectorStore,
        doc_id: str,
        content: str,
        embedding: list[float],
        *,
        metadata: dict | None = None,
        chunk_index: int = 0,
        session_id: str | None = None,
        role: str | None = None,
    ) -> str:
        cls._validate_embedding(vectorstore, embedding)
        chunk_id = str(uuid.uuid4())
        metadata_json = json.dumps(metadata or {})

        with cls.connect(vectorstore) as conn:
            conn.execute(
                """
                INSERT INTO vector_chunks
                    (id, doc_id, chunk_index, content, metadata_json, embedding,
                     session_id, role, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (
                    chunk_id,
                    doc_id,
                    chunk_index,
                    content,
                    metadata_json,
                    cls._pack_embedding(embedding),
                    session_id,
                    role,
                ),
            )
            conn.commit()
        return chunk_id

    @classmethod
    def get_chunk(cls, vectorstore: VectorStore, chunk_id: str) -> dict[str, Any] | None:
        with cls.connect(vectorstore) as conn:
            row = conn.execute(
                "SELECT * FROM vector_chunks WHERE id = ?",
                (chunk_id,),
            ).fetchone()
        return cls._row_to_hit(row) if row else None

    @classmethod
    def get_document(
        cls, vectorstore: VectorStore, doc_id: str
    ) -> list[dict[str, Any]]:
        with cls.connect(vectorstore) as conn:
            rows = conn.execute(
                """
                SELECT * FROM vector_chunks
                WHERE doc_id = ?
                ORDER BY chunk_index ASC, created_at ASC
                """,
                (doc_id,),
            ).fetchall()
        return [cls._row_to_hit(row) for row in rows]

    @classmethod
    def delete_chunk(cls, vectorstore: VectorStore, chunk_id: str) -> int:
        with cls.connect(vectorstore) as conn:
            cursor = conn.execute(
                "DELETE FROM vector_chunks WHERE id = ?",
                (chunk_id,),
            )
            conn.commit()
            return cursor.rowcount

    @classmethod
    def upsert_document(
        cls,
        vectorstore: VectorStore,
        doc_id: str,
        chunks: list[dict[str, Any]],
    ) -> int:
        """Replace all chunks for a document. Returns number of chunks written."""
        if not chunks:
            raise VectorstoreError("At least one chunk is required.")

        cls.delete_document(vectorstore, doc_id)

        for index, chunk in enumerate(chunks):
            cls.add_chunk(
                vectorstore,
                doc_id,
                chunk.get("content", ""),
                chunk["embedding"],
                metadata=chunk.get("metadata"),
                chunk_index=chunk.get("chunk_index", index),
            )
        return len(chunks)

    @classmethod
    def delete_document(cls, vectorstore: VectorStore, doc_id: str) -> int:
        with cls.connect(vectorstore) as conn:
            cursor = conn.execute(
                "DELETE FROM vector_chunks WHERE doc_id = ?",
                (doc_id,),
            )
            conn.commit()
            return cursor.rowcount

    @classmethod
    def clear(cls, vectorstore: VectorStore) -> int:
        with cls.connect(vectorstore) as conn:
            cursor = conn.execute("DELETE FROM vector_chunks")
            conn.commit()
            return cursor.rowcount

    @classmethod
    def search(
        cls,
        vectorstore: VectorStore,
        query_embedding: list[float],
        *,
        top_k: int = 5,
        min_score: float = 0.0,
        session_id: str | None = None,
        doc_id: str | None = None,
    ) -> list[dict[str, Any]]:
        cls._validate_embedding(vectorstore, query_embedding)
        top_k = max(1, min(top_k, 100))

        query = "SELECT * FROM vector_chunks WHERE 1=1"
        params: list[Any] = []
        if session_id is not None:
            query += " AND session_id = ?"
            params.append(session_id)
        if doc_id is not None:
            query += " AND doc_id = ?"
            params.append(doc_id)

        with cls.connect(vectorstore) as conn:
            rows = conn.execute(query, params).fetchall()

        results = []
        for row in rows:
            embedding = cls._unpack_embedding(row["embedding"])
            score = cls._cosine_similarity(query_embedding, embedding)
            if score < min_score:
                continue
            results.append(cls._row_to_hit(row, score=score))

        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:top_k]

    # --- Agent conversation memory (same SQLite store) ---

    @classmethod
    def remember(
        cls,
        vectorstore: VectorStore,
        session_id: str,
        role: str,
        content: str,
        embedding: list[float],
        *,
        metadata: dict | None = None,
    ) -> str:
        """Save one conversation turn for later search or history replay."""
        doc_id = f"{session_id}:{uuid.uuid4()}"
        return cls.add_chunk(
            vectorstore,
            doc_id,
            content,
            embedding,
            metadata=metadata,
            session_id=session_id,
            role=role,
        )

    @classmethod
    def history(
        cls,
        vectorstore: VectorStore,
        session_id: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return recent messages for a session, oldest first."""
        limit = max(1, min(limit, 500))
        with cls.connect(vectorstore) as conn:
            rows = conn.execute(
                """
                SELECT * FROM vector_chunks
                WHERE session_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [cls._row_to_hit(row) for row in rows]

    @classmethod
    def clear_session(cls, vectorstore: VectorStore, session_id: str) -> int:
        with cls.connect(vectorstore) as conn:
            cursor = conn.execute(
                "DELETE FROM vector_chunks WHERE session_id = ?",
                (session_id,),
            )
            conn.commit()
            return cursor.rowcount
