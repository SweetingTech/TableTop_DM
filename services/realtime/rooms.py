"""Socket.IO room naming for realtime delivery."""


def campaign_public_room(campaign_id: str) -> str:
    return f"campaign:{campaign_id}:public"


def session_room(session_id: str) -> str:
    return f"session:{session_id}"


def principal_room(principal_id: str) -> str:
    return f"principal:{principal_id}"


def dm_room(campaign_id: str) -> str:
    return f"dm:{campaign_id}"


def legacy_campaign_room(campaign_id: str) -> str:
    """Old broad campaign room. Keep only for leave/backcompat cleanup."""
    return str(campaign_id)
