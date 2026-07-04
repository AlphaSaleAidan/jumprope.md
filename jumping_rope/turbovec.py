"""TurboVec: embedded local vector store for demoted rope content.

Backend is a single SQLite file. When the ``sqlite-vec`` loadable extension is
available, cosine distance is computed in SQL via ``vec_distance_cosine``;
otherwise a pure-SQLite brute-force path computes cosine in Python. Both paths
share the same table and serialization (little-endian float32), so databases
are interchangeable.
"""

from __future__ import annotations

import hashlib
import math
import sqlite3
import struct
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .tokens import count_tokens


class Embedder(Protocol):
    """Pluggable embedding backend."""

    @property
    def dim(self) -> int: ...

    def embed(self, text: str) -> list[float]: ...


class HashEmbedder:
    """Deterministic, dependency-free feature-hashing embedder.

    Hashes word unigrams/bigrams and character trigrams into a fixed-size
    vector (signed feature hashing), then L2-normalizes. Good enough for
    top-k retrieval of demoted rope lines in tests and CPU-only deployments.
    """

    def __init__(self, dim: int = 256) -> None:
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def _features(self, text: str) -> list[str]:
        lowered = text.lower()
        words = [w for w in "".join(c if c.isalnum() else " " for c in lowered).split() if w]
        feats = list(words)
        feats.extend(f"{a}_{b}" for a, b in zip(words, words[1:], strict=False))
        compact = "".join(words)
        feats.extend(compact[i : i + 3] for i in range(len(compact) - 2))
        return feats

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        for feat in self._features(text):
            digest = hashlib.md5(feat.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "little") % self._dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec


class SentenceTransformerEmbedder:
    """Real-model embedder (optional extra ``[st]``). Lazily imports."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ImportError(
                "sentence-transformers is not installed; "
                "install jumping-rope[st] to use SentenceTransformerEmbedder"
            ) from exc
        self._model = SentenceTransformer(model_name)
        self._dim = int(self._model.get_sentence_embedding_dimension())

    @property
    def dim(self) -> int:  # pragma: no cover - optional dependency
        return self._dim

    def embed(self, text: str) -> list[float]:  # pragma: no cover - optional dependency
        vec = self._model.encode([text], normalize_embeddings=True)[0]
        return [float(v) for v in vec]


@dataclass
class VecRecord:
    id: str
    session_id: str
    jump_index: int
    section: str
    key: str
    content: str
    tokens: int
    created_at: str
    turn: int = -1  # provenance: session turn that produced this record


def _serialize(vec: list[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def _deserialize(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class TurboVec:
    """Tier-2 store: everything demoted out of the rope lands here."""

    def __init__(
        self,
        db_path: str | Path,
        embedder: Embedder | None = None,
        force_fallback: bool = False,
    ) -> None:
        self.db_path = Path(db_path)
        self.embedder: Embedder = embedder if embedder is not None else HashEmbedder()
        # check_same_thread=False + an RLock: one connection may be driven
        # from several threads (ASGI test clients, thread pools); sqlite's
        # serialized mode does not protect interleaved cursor use.
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._vec_extension = False if force_fallback else self._try_load_extension()
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                jump_index INTEGER NOT NULL,
                section TEXT NOT NULL,
                key TEXT NOT NULL UNIQUE,
                content TEXT NOT NULL,
                tokens INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                embedding BLOB NOT NULL,
                turn INTEGER NOT NULL DEFAULT -1
            )
            """
        )
        try:  # migrate pre-provenance databases in place
            self._conn.execute(
                "ALTER TABLE records ADD COLUMN turn INTEGER NOT NULL DEFAULT -1"
            )
        except sqlite3.OperationalError:
            pass  # column already exists
        self._conn.commit()

    def _try_load_extension(self) -> bool:
        try:
            import sqlite_vec

            self._conn.enable_load_extension(True)
            sqlite_vec.load(self._conn)
            self._conn.enable_load_extension(False)
            return True
        except Exception:
            return False

    @property
    def using_vec_extension(self) -> bool:
        return self._vec_extension

    # -- API ----------------------------------------------------------------

    @staticmethod
    def content_key(session_id: str, section: str, content: str) -> str:
        """The deterministic key put() assigns to this exact content."""
        digest = hashlib.sha1(
            f"{session_id}\x1f{section}\x1f{content}".encode()
        ).hexdigest()
        return f"tv-{digest[:16]}"

    def put(
        self,
        *,
        session_id: str,
        jump_index: int,
        section: str,
        content: str,
        key: str | None = None,
        created_at: str = "",
        turn: int = -1,
    ) -> str:
        """Store content; returns the retrieval key.

        Keys are content-addressed: the same (session_id, section, content)
        always maps to the same key and is stored at most once, so crash-retry
        re-demotion can never duplicate records (adversarial findings A9/A10).
        """
        rec_id = uuid.uuid4().hex
        rec_key = key if key is not None else self.content_key(session_id, section, content)
        embedding = self.embedder.embed(content)
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rec_id,
                    session_id,
                    jump_index,
                    section,
                    rec_key,
                    content,
                    count_tokens(content),
                    created_at,
                    _serialize(embedding),
                    turn,
                ),
            )
            self._conn.commit()
        return rec_key

    def get(self, key: str) -> VecRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, session_id, jump_index, section, key, content, tokens, "
                "created_at, turn FROM records WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return VecRecord(*row)

    def search(
        self, query: str, k: int = 5, session_id: str | None = None
    ) -> list[VecRecord]:
        qvec = self.embedder.embed(query)
        if self._vec_extension:
            return self._search_ext(qvec, k, session_id)
        return self._search_fallback(qvec, k, session_id)

    def _search_ext(
        self, qvec: list[float], k: int, session_id: str | None
    ) -> list[VecRecord]:
        where = "WHERE session_id = ?" if session_id is not None else ""
        params: list[object] = [_serialize(qvec)]
        if session_id is not None:
            params.append(session_id)
        params.append(k)
        with self._lock:
            rows = self._conn.execute(
                f"""
            SELECT id, session_id, jump_index, section, key, content, tokens,
                   created_at, turn, vec_distance_cosine(embedding, ?) AS d
            FROM records {where}
            ORDER BY d ASC, key ASC LIMIT ?
            """,
            params,
        ).fetchall()
        return [VecRecord(*row[:9]) for row in rows]

    def _search_fallback(
        self, qvec: list[float], k: int, session_id: str | None
    ) -> list[VecRecord]:
        where = "WHERE session_id = ?" if session_id is not None else ""
        params: tuple[str, ...] = (session_id,) if session_id is not None else ()
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, session_id, jump_index, section, key, content, tokens, "
                f"created_at, turn, embedding FROM records {where}",
                params,
            ).fetchall()
        scored = [
            (-_cosine(qvec, _deserialize(row[9])), row[4], VecRecord(*row[:9]))
            for row in rows
        ]
        scored.sort(key=lambda t: (t[0], t[1]))
        return [rec for _, _, rec in scored[:k]]

    def dump(self, session_id: str | None = None) -> list[VecRecord]:
        """All records (optionally one session), insertion order."""
        where = "WHERE session_id = ?" if session_id is not None else ""
        params: tuple[str, ...] = (session_id,) if session_id is not None else ()
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, session_id, jump_index, section, key, content, tokens, "
                f"created_at, turn FROM records {where} ORDER BY rowid",
                params,
            ).fetchall()
        return [VecRecord(*row) for row in rows]

    def stats(self) -> dict[str, object]:
        with self._lock:
            total, tokens = self._conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(tokens), 0) FROM records"
            ).fetchone()
            sessions = self._conn.execute(
                "SELECT COUNT(DISTINCT session_id) FROM records"
            ).fetchone()[0]
        return {
            "records": int(total),
            "tokens": int(tokens),
            "sessions": int(sessions),
            "backend": "sqlite-vec" if self._vec_extension else "brute-force",
            "embedder": type(self.embedder).__name__,
            "db_path": str(self.db_path),
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def format_retrieved(key: str, content: str) -> str:
    """Wrap retrieved content in a compact context-injection block."""
    return f"RETRIEVED|{key}|{content}"
