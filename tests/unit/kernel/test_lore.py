import uuid

import pytest

from kernel.lore import LocalLoreIndex, LoreDocument, QdrantLoreIndex

pytestmark = pytest.mark.unit


def test_lore_retrieval_is_world_scoped_visible_and_deterministic():
    world, other = uuid.uuid4(), uuid.uuid4()
    index = LocalLoreIndex()
    public = LoreDocument(
        document_id=uuid.uuid4(),
        world_id=world,
        title="Eclipse Keep",
        text="The brass gate opens at moonrise.",
        tags=("gate",),
    )
    secret = LoreDocument(
        document_id=uuid.uuid4(),
        world_id=world,
        title="Hidden oath",
        text="The gatekeeper serves the ash court.",
        visibility="GM",
    )
    index.upsert(
        (
            public,
            secret,
            LoreDocument(
                document_id=uuid.uuid4(), world_id=other, title="Other gate", text="Moonrise gate"
            ),
        )
    )
    assert index.search(world, "moonrise gate") == index.search(world, "moonrise gate")
    assert [hit.document.document_id for hit in index.search(world, "moonrise gate")] == [
        public.document_id
    ]
    assert {
        hit.document.document_id
        for hit in index.search(world, "gatekeeper ash", visibility=frozenset({"PUBLIC", "GM"}))
    } == {secret.document_id}


def test_vector_index_filters_visibility_and_revalidates_returned_scope(monkeypatch):
    world = uuid.uuid4()
    public = LoreDocument(document_id=uuid.uuid4(), world_id=world, title="Gate", text="Moonrise")
    secret = public.model_copy(update={"document_id": uuid.uuid4(), "visibility": "GM"})
    foreign = public.model_copy(update={"document_id": uuid.uuid4(), "world_id": uuid.uuid4()})
    sent = []

    def request(self, method, path, body):
        sent.append(body)
        return {
            "result": [
                {"payload": row.model_dump(mode="json"), "score": 1}
                for row in (public, secret, foreign)
            ]
        }

    monkeypatch.setattr(QdrantLoreIndex, "_request", request)
    index = QdrantLoreIndex("http://fixture.invalid", "lore", lambda text: [1.0], 1)
    assert [hit.document for hit in index.search(world, "moonrise")] == [public]
    assert sent[-1]["filter"]["must"] == [
        {"key": "world_id", "match": {"value": str(world)}},
        {"key": "visibility", "match": {"any": ["PUBLIC"]}},
    ]
    assert {
        hit.document.document_id
        for hit in index.search(world, "moonrise", visibility=frozenset({"GM", "PUBLIC"}))
    } == {public.document_id, secret.document_id}
