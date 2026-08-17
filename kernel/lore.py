from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field


class LoreDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: uuid.UUID
    world_id: uuid.UUID
    title: str
    text: str
    visibility: str = "PUBLIC"
    tags: tuple[str, ...] = ()
    provenance: dict[str, Any] = Field(default_factory=dict)


class LoreHit(BaseModel):
    model_config = ConfigDict(frozen=True)

    document: LoreDocument
    score: float


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.casefold()))


class LocalLoreIndex:
    """Deterministic lexical reference adapter used offline and in tests."""

    def __init__(self) -> None:
        self._documents: dict[uuid.UUID, LoreDocument] = {}

    def upsert(self, documents: tuple[LoreDocument, ...]) -> None:
        for document in documents:
            self._documents[document.document_id] = document

    def search(
        self,
        world_id: uuid.UUID,
        query: str,
        *,
        limit: int = 5,
        visibility: frozenset[str] = frozenset({"PUBLIC"}),
    ) -> tuple[LoreHit, ...]:
        query_tokens = _tokens(query)
        scored: list[LoreHit] = []
        for document in self._documents.values():
            if document.world_id != world_id or document.visibility not in visibility:
                continue
            document_tokens = _tokens(f"{document.title} {document.text} {' '.join(document.tags)}")
            union = query_tokens | document_tokens
            score = len(query_tokens & document_tokens) / len(union) if union else 0.0
            if score:
                scored.append(LoreHit(document=document, score=round(score, 6)))
        return tuple(
            sorted(scored, key=lambda hit: (-hit.score, str(hit.document.document_id)))[:limit]
        )


Vectorizer = Callable[[str], list[float]]


@dataclass(frozen=True)
class QdrantLoreIndex:
    """Thin Qdrant REST adapter; embeddings remain an injected, versioned concern."""

    base_url: str
    collection: str
    vectorizer: Vectorizer
    vector_size: int

    def ensure_collection(self) -> None:
        body = {
            "vectors": {"size": self.vector_size, "distance": "Cosine"},
            "on_disk_payload": True,
        }
        self._request("PUT", f"/collections/{self.collection}", body)

    def upsert(self, documents: tuple[LoreDocument, ...]) -> None:
        points = []
        for document in documents:
            vector = self.vectorizer(f"{document.title}\n{document.text}")
            if len(vector) != self.vector_size:
                raise ValueError("vectorizer output does not match collection size")
            points.append(
                {
                    "id": str(document.document_id),
                    "vector": vector,
                    "payload": document.model_dump(mode="json"),
                }
            )
        self._request("PUT", f"/collections/{self.collection}/points?wait=true", {"points": points})

    def search(self, world_id: uuid.UUID, query: str, limit: int = 5) -> tuple[LoreHit, ...]:
        vector = self.vectorizer(query)
        result = self._request(
            "POST",
            f"/collections/{self.collection}/points/search",
            {
                "vector": vector,
                "limit": limit,
                "with_payload": True,
                "filter": {"must": [{"key": "world_id", "match": {"value": str(world_id)}}]},
            },
        )
        return tuple(
            LoreHit(
                document=LoreDocument.model_validate(item["payload"]),
                score=float(item["score"]),
            )
            for item in result.get("result", [])
        )

    def _request(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            self.base_url.rstrip("/") + path,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method=method,
        )
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
