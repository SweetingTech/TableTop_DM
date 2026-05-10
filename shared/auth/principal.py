import uuid
from typing import Optional
from pydantic import BaseModel

from shared.schemas.enums import PrincipalType, CampaignRole


class PrincipalContext(BaseModel):
    principal_id: uuid.UUID
    principal_type: PrincipalType
    display_name: str
    campaign_id: Optional[uuid.UUID] = None
    role: Optional[CampaignRole] = None
    controlled_entity_ids: list[uuid.UUID] = []

    def is_gm(self) -> bool:
        return self.role == CampaignRole.GM

    def is_player(self) -> bool:
        return self.role == CampaignRole.PLAYER

    def is_system(self) -> bool:
        return self.principal_type == PrincipalType.SYSTEM

    def can_control_entity(self, entity_id: uuid.UUID) -> bool:
        return (
            self.is_gm() or self.is_system() or entity_id in self.controlled_entity_ids
        )


def load_principal(
    principal_id: uuid.UUID, campaign_id: uuid.UUID = None
) -> Optional[PrincipalContext]:
    from shared.db.connection import execute_one

    row = execute_one(
        "SELECT id, principal_type, display_name FROM state.principals WHERE id = %s AND is_active = true",
        (str(principal_id),),
    )
    if not row:
        return None

    ctx = PrincipalContext(
        principal_id=row["id"],
        principal_type=row["principal_type"],
        display_name=row["display_name"],
        campaign_id=campaign_id,
    )

    if campaign_id:
        member = execute_one(
            "SELECT role FROM state.campaign_members WHERE campaign_id = %s AND principal_id = %s",
            (str(campaign_id), str(principal_id)),
        )
        if member:
            ctx.role = member["role"]

        from shared.db.connection import execute_query

        entities = execute_query(
            "SELECT id FROM state.entities WHERE controller_principal_id = %s AND campaign_id = %s",
            (str(principal_id), str(campaign_id)),
        )
        ctx.controlled_entity_ids = [
            e["id"] if isinstance(e["id"], uuid.UUID) else uuid.UUID(e["id"])
            for e in entities
        ]

    return ctx
