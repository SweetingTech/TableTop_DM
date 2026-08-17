import uuid

import pytest

from kernel.lore import LocalLoreIndex, LoreDocument

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
