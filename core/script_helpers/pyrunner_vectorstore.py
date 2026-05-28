"""
PyRunner VectorStore API for scripts and AI agents.

Each vector store is backed by its own SQLite database file with cosine
similarity search. Create stores in the PyRunner UI, then embed text in
your script (OpenAI, local model, etc.) and store/search vectors here.

Usage:
    from pyrunner_vectorstore import VectorStore

    kb = VectorStore("agent_memory")

    # Add a document chunk (embedding from your provider)
    kb.add(
        doc_id="doc-1",
        content="PyRunner runs scheduled Python scripts.",
        embedding=[0.01, -0.02, ...],  # length must match store dimensions
        metadata={"source": "docs"},
    )

    # Replace all chunks for a document
    kb.upsert("doc-1", [
        {"content": "chunk one", "embedding": [...], "metadata": {"page": 1}},
        {"content": "chunk two", "embedding": [...], "metadata": {"page": 2}},
    ])

    # Similarity search for RAG
    results = kb.search(query_embedding, top_k=5)
    for hit in results:
        print(hit["score"], hit["content"], hit["metadata"])

    kb.delete("doc-1")
    kb.clear()
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

    def _main_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _vector_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn

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

    def add(
        self,
        doc_id: str,
        content: str,
        embedding: list[float],
        metadata: dict | None = None,
        *,
        chunk_index: int = 0,
    ) -> str:
        self._validate_embedding(embedding)
        chunk_id = str(uuid.uuid4())
        metadata_json = json.dumps(metadata or {})

        with self._vector_connection() as conn:
            conn.execute(
                """
                INSERT INTO vector_chunks
                    (id, doc_id, chunk_index, content, metadata_json, embedding, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (
                    chunk_id,
                    doc_id,
                    chunk_index,
                    content,
                    metadata_json,
                    self._pack_embedding(embedding),
                ),
            )
            conn.commit()
        return chunk_id

    def upsert(self, doc_id: str, chunks: list[dict[str, Any]]) -> int:
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
            )
        return len(chunks)

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        *,
        min_score: float = 0.0,
    ) -> list[dict[str, Any]]:
        self._validate_embedding(query_embedding)
        top_k = max(1, min(top_k, 100))

        with self._vector_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, doc_id, chunk_index, content, metadata_json, embedding
                FROM vector_chunks
                """
            ).fetchall()

        results = []
        for row in rows:
            embedding = self._unpack_embedding(row["embedding"])
            score = self._cosine_similarity(query_embedding, embedding)
            if score < min_score:
                continue
            results.append(
                {
                    "id": row["id"],
                    "doc_id": row["doc_id"],
                    "chunk_index": row["chunk_index"],
                    "content": row["content"],
                    "metadata": json.loads(row["metadata_json"] or "{}"),
                    "score": score,
                }
            )

        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:top_k]

    def delete(self, doc_id: str) -> int:
        with self._vector_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM vector_chunks WHERE doc_id = ?",
                (doc_id,),
            )
            conn.commit()
            return cursor.rowcount

    def clear(self) -> int:
        with self._vector_connection() as conn:
            cursor = conn.execute("DELETE FROM vector_chunks")
            conn.commit()
            return cursor.rowcount

    def count(self) -> int:
        with self._vector_connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM vector_chunks").fetchone()
            return row["count"]

    def __len__(self) -> int:
        return self.count()

    def __repr__(self) -> str:
        return f"VectorStore('{self.name}')"
