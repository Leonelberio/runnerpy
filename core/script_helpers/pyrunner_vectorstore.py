"""
PyRunner VectorStore — SQLite-backed vector storage for scripts and AI agents.

Create a store in the UI, embed text with your provider (OpenAI, etc.), then use:

    from pyrunner_vectorstore import VectorStore

    store = VectorStore("agent_memory")

    # CRUD
    chunk_id = store.add("doc-1", "Hello", embedding)
    store.upsert("doc-1", [{"content": "...", "embedding": [...]}])
    hits = store.search(query_embedding, top_k=5)
    doc = store.get_document("doc-1")
    store.delete("doc-1")
    store.clear()

    # Conversation memory (per session_id)
    store.remember("user-42", "user", "What is PyRunner?", embedding)
    store.remember("user-42", "assistant", "A script runner.", embedding)
    transcript = store.history("user-42", limit=20)
    relevant = store.search(query_embedding, top_k=5, session_id="user-42")
    store.clear_session("user-42")
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import struct
import uuid
from typing import Any


class VectorStore:
    """Workspace-scoped vector database backed by SQLite."""

    _SCHEMA_SQL = """
        CREATE TABLE IF NOT EXISTS vector_chunks (
            id TEXT PRIMARY KEY,
            doc_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL DEFAULT 0,
            content TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            embedding BLOB NOT NULL,
            session_id TEXT,
            role TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_vector_chunks_doc_id ON vector_chunks(doc_id);
        CREATE INDEX IF NOT EXISTS idx_vector_chunks_session_id ON vector_chunks(session_id);
    """

    def __init__(self, name: str):
        self.name = name
        self._db_path = os.environ.get("PYRUNNER_DB_PATH")
        self._workspace_id = os.environ.get("PYRUNNER_WORKSPACE_ID")
        self._vectorstores_root = os.environ.get("PYRUNNER_VECTORSTORES_ROOT")

        if not self._db_path:
            raise RuntimeError(
                "PYRUNNER_DB_PATH not set. This module must be run from PyRunner."
            )
        if not self._workspace_id:
            raise RuntimeError(
                "PYRUNNER_WORKSPACE_ID not set. This module must be run from PyRunner."
            )
        if not self._vectorstores_root:
            raise RuntimeError(
                "PYRUNNER_VECTORSTORES_ROOT not set. This module must be run from PyRunner."
            )

        store = self._lookup_store()
        if not store:
            raise ValueError(
                f"Vector store '{name}' does not exist in this workspace. "
                "Create it in the PyRunner UI first."
            )

        self._store_id = store["id"]
        self.dimensions = store["dimensions"]
        self._sqlite_path = os.path.join(
            self._vectorstores_root,
            store["sqlite_filename"],
        )
        if not os.path.exists(self._sqlite_path):
            raise ValueError(
                f"Vector store '{name}' database file is missing on disk."
            )
        self._ensure_schema()

    def _main_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _vector_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._vector_connection() as conn:
            conn.executescript(self._SCHEMA_SQL)
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(vector_chunks)")
            }
            if "session_id" not in columns:
                conn.execute("ALTER TABLE vector_chunks ADD COLUMN session_id TEXT")
            if "role" not in columns:
                conn.execute("ALTER TABLE vector_chunks ADD COLUMN role TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_vector_chunks_doc_id "
                "ON vector_chunks(doc_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_vector_chunks_session_id "
                "ON vector_chunks(session_id)"
            )
            conn.commit()

    def _lookup_store(self) -> dict | None:
        with self._main_connection() as conn:
            row = conn.execute(
                """
                SELECT id, dimensions, sqlite_filename
                FROM vectorstores
                WHERE name = ? AND workspace_id = ?
                """,
                (self.name, self._workspace_id),
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def _pack_embedding(embedding: list[float]) -> bytes:
        return struct.pack(f"{len(embedding)}f", *embedding)

    @staticmethod
    def _unpack_embedding(blob: bytes) -> list[float]:
        count = len(blob) // 4
        return list(struct.unpack(f"{count}f", blob))

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _validate_embedding(self, embedding: list[float]) -> None:
        if len(embedding) != self.dimensions:
            raise ValueError(
                f"Embedding length {len(embedding)} does not match store dimensions "
                f"({self.dimensions})."
            )

    @staticmethod
    def _row_to_hit(row: sqlite3.Row, score: float | None = None) -> dict[str, Any]:
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

    # --- Core vector CRUD ---

    def add(
        self,
        doc_id: str,
        content: str,
        embedding: list[float],
        metadata: dict | None = None,
        *,
        chunk_index: int = 0,
        session_id: str | None = None,
        role: str | None = None,
    ) -> str:
        """Insert one chunk. Returns chunk id."""
        self._validate_embedding(embedding)
        chunk_id = str(uuid.uuid4())
        metadata_json = json.dumps(metadata or {})

        with self._vector_connection() as conn:
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
                    self._pack_embedding(embedding),
                    session_id,
                    role,
                ),
            )
            conn.commit()
        return chunk_id

    def upsert(self, doc_id: str, chunks: list[dict[str, Any]]) -> int:
        """Replace all chunks for a document. Returns number of chunks written."""
        if not chunks:
            raise ValueError("At least one chunk is required.")
        self.delete(doc_id)
        for index, chunk in enumerate(chunks):
            self.add(
                doc_id=doc_id,
                content=chunk.get("content", ""),
                embedding=chunk["embedding"],
                metadata=chunk.get("metadata"),
                chunk_index=chunk.get("chunk_index", index),
                session_id=chunk.get("session_id"),
                role=chunk.get("role"),
            )
        return len(chunks)

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        *,
        min_score: float = 0.0,
        session_id: str | None = None,
        doc_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Similarity search. Optionally scope to a session or document."""
        self._validate_embedding(query_embedding)
        top_k = max(1, min(top_k, 100))

        query = "SELECT * FROM vector_chunks WHERE 1=1"
        params: list[Any] = []
        if session_id is not None:
            query += " AND session_id = ?"
            params.append(session_id)
        if doc_id is not None:
            query += " AND doc_id = ?"
            params.append(doc_id)

        with self._vector_connection() as conn:
            rows = conn.execute(query, params).fetchall()

        results = []
        for row in rows:
            embedding = self._unpack_embedding(row["embedding"])
            score = self._cosine_similarity(query_embedding, embedding)
            if score < min_score:
                continue
            results.append(self._row_to_hit(row, score=score))

        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:top_k]

    def get(self, chunk_id: str) -> dict[str, Any] | None:
        """Fetch a single chunk by id."""
        with self._vector_connection() as conn:
            row = conn.execute(
                "SELECT * FROM vector_chunks WHERE id = ?",
                (chunk_id,),
            ).fetchone()
        return self._row_to_hit(row) if row else None

    def get_document(self, doc_id: str) -> list[dict[str, Any]]:
        """All chunks for a document, in order."""
        with self._vector_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM vector_chunks
                WHERE doc_id = ?
                ORDER BY chunk_index ASC, created_at ASC
                """,
                (doc_id,),
            ).fetchall()
        return [self._row_to_hit(row) for row in rows]

    def list_documents(self) -> list[dict[str, Any]]:
        """Summarize documents in the store."""
        with self._vector_connection() as conn:
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

    def delete(self, doc_id: str) -> int:
        """Delete all chunks for a document."""
        with self._vector_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM vector_chunks WHERE doc_id = ?",
                (doc_id,),
            )
            conn.commit()
            return cursor.rowcount

    def delete_chunk(self, chunk_id: str) -> int:
        """Delete one chunk by id."""
        with self._vector_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM vector_chunks WHERE id = ?",
                (chunk_id,),
            )
            conn.commit()
            return cursor.rowcount

    def clear(self) -> int:
        """Delete every chunk in the store."""
        with self._vector_connection() as conn:
            cursor = conn.execute("DELETE FROM vector_chunks")
            conn.commit()
            return cursor.rowcount

    def count(self) -> int:
        with self._vector_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM vector_chunks"
            ).fetchone()
            return row["count"]

    # --- Conversation memory helpers ---

    def remember(
        self,
        session_id: str,
        role: str,
        content: str,
        embedding: list[float],
        *,
        metadata: dict | None = None,
    ) -> str:
        """Save one chat turn (user/assistant/system) for a session."""
        doc_id = f"{session_id}:{uuid.uuid4()}"
        return self.add(
            doc_id,
            content,
            embedding,
            metadata=metadata,
            session_id=session_id,
            role=role,
        )

    def history(self, session_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """Recent messages for a session, oldest first."""
        limit = max(1, min(limit, 500))
        with self._vector_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM vector_chunks
                WHERE session_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [self._row_to_hit(row) for row in rows]

    def recall(
        self,
        session_id: str,
        query_embedding: list[float],
        *,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Semantic search within one conversation session."""
        return self.search(
            query_embedding,
            top_k=top_k,
            min_score=min_score,
            session_id=session_id,
        )

    def clear_session(self, session_id: str) -> int:
        """Delete all messages for a session."""
        with self._vector_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM vector_chunks WHERE session_id = ?",
                (session_id,),
            )
            conn.commit()
            return cursor.rowcount

    def __len__(self) -> int:
        return self.count()

    def __repr__(self) -> str:
        return f"VectorStore('{self.name}')"
