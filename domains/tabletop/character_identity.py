"""Player-authored fiction. These claims are neither canonical truth nor learned evidence."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

IdentityEntry = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=500)
]
IdentityEntries = Annotated[tuple[IdentityEntry, ...], Field(max_length=20)]
IDENTITY_SHEET_KEY = "_authored_identity_v1"


class CharacterIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    backstory: Annotated[
        str, StringConstraints(strict=True, strip_whitespace=True, max_length=12000)
    ] = ""
    motives: IdentityEntries = ()
    values: IdentityEntries = ()
    bonds: IdentityEntries = ()
    secrets: IdentityEntries = ()
    # Author assertions about starting knowledge, awaiting the trusted knowledge boundary.
    initial_known_facts: IdentityEntries = ()
