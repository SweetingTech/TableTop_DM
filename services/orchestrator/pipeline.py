import uuid
from shared.schemas.events import EventEnvelope, ToolCallPayload
from shared.schemas.enums import EventType, GameMode
from shared.schemas.contracts import (
    InterventionProposal,
    validate_proposal,
    ACTION_REGISTRY,
)
from shared.auth.principal import PrincipalContext
from shared.db.connection import get_connection
from services.ledger.writer import LedgerWriter
from services.visibility.filter import VisibilityResolver
from services.orchestrator.state_machine import StateMachine
from services.mechanics.engine import MechanicsEngine
from services.spatial.engine import SpatialEngine


class ValidationError(Exception):
    def __init__(self, reason: str, code: str = "VALIDATION_ERROR"):
        self.reason = reason
        self.code = code
        super().__init__(reason)


class OrchestratorPipeline:
    def __init__(self):
        self.ledger = LedgerWriter()
        self.visibility = VisibilityResolver()
        self.state_machine = StateMachine()
        self.mechanics = MechanicsEngine()
        self.spatial = SpatialEngine()

    def process_proposal(
        self,
        proposal: InterventionProposal,
        principal: PrincipalContext,
        session_id: uuid.UUID,
    ) -> dict:
        valid, reason = validate_proposal(proposal, principal.principal_type)
        if not valid:
            self._log_warning(proposal, principal, session_id, reason)
            raise ValidationError(reason, "SCHEMA_INVALID")

        if not self._check_auth(proposal, principal):
            reason = f"Principal {principal.display_name} not authorized for {proposal.action_type}"
            self._log_warning(proposal, principal, session_id, reason)
            raise ValidationError(reason, "AUTH_DENIED")

        if not self._check_ap(proposal, principal):
            reason = f"Insufficient AP for {proposal.action_type}"
            self._log_warning(proposal, principal, session_id, reason)
            raise ValidationError(reason, "INSUFFICIENT_AP")

        tool_result = self._execute_tool(proposal, principal)

        result = self._commit(proposal, principal, session_id, tool_result)

        return result

    def _check_auth(
        self, proposal: InterventionProposal, principal: PrincipalContext
    ) -> bool:
        entity_id = proposal.params.get("entity_id") or proposal.params.get(
            "attacker_id"
        )
        if entity_id:
            entity_uuid = (
                uuid.UUID(entity_id) if isinstance(entity_id, str) else entity_id
            )
            if not principal.can_control_entity(entity_uuid):
                return False
        return True

    def _check_ap(
        self, proposal: InterventionProposal, principal: PrincipalContext
    ) -> bool:
        entry = ACTION_REGISTRY.get(proposal.action_type, {})
        ap_cost = entry.get("ap_cost", 0)
        if ap_cost == 0:
            return True

        encounter = self.state_machine.get_active_encounter(proposal.campaign_id)
        if not encounter:
            return True

        from shared.db.connection import execute_one

        entity_id = proposal.params.get("entity_id") or proposal.params.get(
            "attacker_id"
        )
        if entity_id:
            slot = execute_one(
                "SELECT ap_current FROM state.encounter_slots WHERE encounter_id = %s AND entity_id = %s",
                (str(encounter["id"]), str(entity_id)),
            )
            if slot and slot["ap_current"] < ap_cost:
                return False

        return True

    def _execute_tool(
        self, proposal: InterventionProposal, principal: PrincipalContext
    ) -> ToolCallPayload:
        action = proposal.action_type
        params = proposal.params

        if action == "ATTACK" or action == "OPPORTUNITY_ATTACK":
            return self._handle_attack(params, proposal.campaign_id)
        elif action == "MOVE":
            return self._handle_move(params, proposal.campaign_id)
        elif action == "APPLY_CONDITION":
            return self.mechanics.apply_condition(
                entity_id=uuid.UUID(params["entity_id"]),
                condition=params["condition"],
                duration_rounds=params.get("duration_rounds", -1),
                source=params.get("source", "unknown"),
                campaign_id=proposal.campaign_id,
                encounter_id=proposal.encounter_id,
            )
        elif action == "REMOVE_CONDITION":
            return self.mechanics.remove_condition(
                entity_id=uuid.UUID(params["entity_id"]),
                condition=params["condition"],
            )
        elif action == "MODIFY_INVENTORY":
            return self.mechanics.modify_inventory(
                entity_id=uuid.UUID(params["entity_id"]),
                item_id=uuid.UUID(params["item_id"]),
                quantity_delta=params.get("quantity_delta", 0),
            )
        elif action == "END_TURN":
            encounter = self.state_machine.get_active_encounter(proposal.campaign_id)
            if encounter:
                result = self.state_machine.advance_turn(encounter["id"])
                return ToolCallPayload(
                    tool_name="end_turn",
                    arguments=params,
                    result=result,
                )
            return ToolCallPayload(
                tool_name="end_turn",
                arguments=params,
                result={"success": False, "reason": "No active encounter"},
            )
        elif action == "SET_MODE":
            new_mode = GameMode(params["new_mode"])
            result = self.state_machine.set_campaign_mode(
                proposal.campaign_id, new_mode
            )
            return ToolCallPayload(
                tool_name="set_game_mode", arguments=params, result=result
            )
        elif action == "TALK":
            return ToolCallPayload(
                tool_name="social_interaction",
                arguments=params,
                result={
                    "speaker_id": params.get("speaker_id"),
                    "message": params.get("message", ""),
                },
            )
        else:
            fallback = ACTION_REGISTRY.get(action, {}).get("tool", action.lower())
            tool_name = str(fallback)
            return ToolCallPayload(
                tool_name=tool_name,
                arguments=params,
                result={"action": action, "params": params},
            )

    def _handle_attack(self, params: dict, campaign_id: uuid.UUID) -> ToolCallPayload:
        from shared.db.connection import execute_one

        attacker = execute_one(
            "SELECT * FROM state.entities WHERE id = %s", (params["attacker_id"],)
        )
        target = execute_one(
            "SELECT * FROM state.entities WHERE id = %s", (params["target_id"],)
        )
        if not attacker or not target:
            return ToolCallPayload(
                tool_name="resolve_attack",
                arguments=params,
                result={"success": False, "reason": "Entity not found"},
            )

        attack_mod = (attacker.get("public_sheet") or {}).get("attack_modifier", 2)
        damage_dice = params.get("damage_dice", "1d8")
        weapon = params.get("weapon", "unarmed")

        return self.mechanics.resolve_attack(
            attacker_id=uuid.UUID(params["attacker_id"]),
            target_id=uuid.UUID(params["target_id"]),
            attack_modifier=attack_mod,
            target_ac=target["ac"] or 10,
            damage_dice=damage_dice,
            weapon=weapon,
            target_hp=target["hp_current"] or 0,
            target_max_hp=target["hp_max"] or 0,
        )

    def _handle_move(self, params: dict, campaign_id: uuid.UUID) -> ToolCallPayload:
        from shared.db.connection import execute_one
        from shared.schemas.events import StateDelta

        entity = execute_one(
            "SELECT * FROM state.entities WHERE id = %s", (params["entity_id"],)
        )
        if not entity:
            return ToolCallPayload(
                tool_name="move_entity",
                arguments=params,
                result={"success": False, "reason": "Entity not found"},
            )

        # Get current position from public_sheet
        public_sheet = entity.get("public_sheet") or {}
        from_x = public_sheet.get("x", 0)
        from_y = public_sheet.get("y", 0)

        to_x = params.get("destination_x")
        to_y = params.get("destination_y")

        if to_x is None or to_y is None:
            return ToolCallPayload(
                tool_name="move_entity",
                arguments=params,
                result={"success": False, "reason": "destination_x and destination_y required"},
            )

        # Get map for pathfinding validation
        map_row = execute_one(
            "SELECT id FROM state.maps WHERE campaign_id = %s LIMIT 1",
            (str(campaign_id),)
        )

        if map_row:
            # Use SpatialEngine for pathfinding and collision validation
            max_speed = entity.get("speed") or 30
            move_result = self.spatial.move_entity(
                entity_id=uuid.UUID(params["entity_id"]),
                map_id=str(map_row["id"]),
                from_x=from_x,
                from_y=from_y,
                to_x=to_x,
                to_y=to_y,
                max_speed=max_speed,
            )

            # If pathfinding failed, return the error
            if not move_result.result.get("success"):
                return move_result

            # Create delta for public_sheet position update
            move_result.deltas = [
                StateDelta(
                    table="state.entities",
                    operation="UPDATE",
                    entity_id=uuid.UUID(params["entity_id"]),
                    changes={
                        "public_sheet_x": to_x,
                        "public_sheet_y": to_y,
                        "previous_x": from_x,
                        "previous_y": from_y,
                    },
                    domain_tags=["movement"],
                )
            ]
            return move_result
        else:
            # No map - allow free movement without pathfinding
            return ToolCallPayload(
                tool_name="move_entity",
                arguments=params,
                result={
                    "success": True,
                    "entity_id": params["entity_id"],
                    "from": {"x": from_x, "y": from_y},
                    "to": {"x": to_x, "y": to_y},
                },
                deltas=[
                    StateDelta(
                        table="state.entities",
                        operation="UPDATE",
                        entity_id=uuid.UUID(params["entity_id"]),
                        changes={
                            "public_sheet_x": to_x,
                            "public_sheet_y": to_y,
                        },
                        domain_tags=["movement"],
                    )
                ],
            )

    def _commit(
        self,
        proposal: InterventionProposal,
        principal: PrincipalContext,
        session_id: uuid.UUID,
        tool_result: ToolCallPayload,
    ) -> dict:
        conn = get_connection()
        try:
            visible_to = self.visibility.resolve_visible_to(
                action_type=proposal.action_type,
                campaign_id=proposal.campaign_id,
                sender_principal_id=principal.principal_id,
                encounter_id=proposal.encounter_id,
            )

            tool_event = EventEnvelope(
                type=EventType.TOOL_CALL,
                campaign_id=proposal.campaign_id,
                session_id=session_id,
                encounter_id=proposal.encounter_id,
                sender_principal_id=principal.principal_id,
                sender_entity_id=proposal.proposer_entity_id,
                payload={
                    "tool_name": tool_result.tool_name,
                    "arguments": tool_result.arguments,
                    "result": tool_result.result,
                    "rolls": [r.model_dump(mode="json") for r in tool_result.rolls],
                },
                visible_to=visible_to,
                domain_tags=proposal.domain_tags,
                idempotency_key=proposal.idempotency_key,
            )
            self.ledger.append_event(tool_event, conn)

            for delta in tool_result.deltas:
                self._apply_delta(delta, conn)

            if tool_result.deltas:
                delta_event = EventEnvelope(
                    type=EventType.STATE_DELTA,
                    campaign_id=proposal.campaign_id,
                    session_id=session_id,
                    encounter_id=proposal.encounter_id,
                    sender_principal_id=principal.principal_id,
                    payload={
                        "deltas": [d.model_dump(mode="json") for d in tool_result.deltas],
                    },
                    visible_to=visible_to,
                    domain_tags=[t for d in tool_result.deltas for t in d.domain_tags],
                    parent_event_id=tool_event.event_id,
                )
                self.ledger.append_event(delta_event, conn)

            entry = ACTION_REGISTRY.get(proposal.action_type, {})
            ap_cost = entry.get("ap_cost", 0)
            if ap_cost > 0:
                self._deduct_ap(proposal, ap_cost, conn)

            conn.commit()

            # Auto-narrate significant events (non-blocking)
            self._auto_narrate_if_significant(
                proposal=proposal,
                principal=principal,
                session_id=session_id,
                tool_result=tool_result,
                visible_to=visible_to,
                parent_event_id=tool_event.event_id,
            )

            return {
                "success": True,
                "event_id": str(tool_event.event_id),
                "tool_result": tool_result.result,
                "rolls": [r.model_dump(mode="json") for r in tool_result.rolls],
                "deltas_applied": len(tool_result.deltas),
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _auto_narrate_if_significant(
        self,
        proposal: InterventionProposal,
        principal: PrincipalContext,
        session_id: uuid.UUID,
        tool_result: ToolCallPayload,
        visible_to: list,
        parent_event_id: uuid.UUID,
    ):
        """Generate automatic narration for significant events."""
        # Only narrate significant combat/story events
        significant_actions = {
            "ATTACK", "OPPORTUNITY_ATTACK", "CAST_SPELL",
            "DIVINE_BLESS", "DIVINE_CURSE", "DIVINE_SMITE",
        }

        if proposal.action_type not in significant_actions:
            return

        # Check if auto-narration is enabled (default: enabled)
        try:
            from shared.db.connection import execute_one

            settings = execute_one(
                "SELECT settings FROM state.campaign_settings WHERE campaign_id = %s",
                (str(proposal.campaign_id),)
            )
            if settings and settings.get("settings"):
                if not settings["settings"].get("auto_narrate", True):
                    return
        except Exception:
            pass  # Default to enabled if settings check fails

        try:
            from services.llm.adapter import DMNarrationAgent

            dm_agent = DMNarrationAgent(campaign_id=proposal.campaign_id)

            # Build context from tool result
            result_data = tool_result.result or {}
            context_parts = []

            if proposal.action_type == "ATTACK":
                if result_data.get("hits"):
                    damage = result_data.get("damage", 0)
                    context_parts.append(f"Attack hit for {damage} damage")
                    if result_data.get("natural_20"):
                        context_parts.append("Critical hit!")
                    if result_data.get("target_down"):
                        context_parts.append("Target is down!")
                else:
                    context_parts.append("Attack missed")
                    if result_data.get("natural_1"):
                        context_parts.append("Critical miss!")

            context = " ".join(context_parts) if context_parts else "Combat action"

            narration = dm_agent.narrate_event(
                tool_result=result_data,
                context=context,
            )

            if narration:
                from shared.schemas.events import EventEnvelope

                narration_event = EventEnvelope(
                    type=EventType.NARRATION,
                    campaign_id=proposal.campaign_id,
                    session_id=session_id,
                    encounter_id=proposal.encounter_id,
                    sender_principal_id=principal.principal_id,
                    payload={
                        "narration": narration,
                        "trigger_action": proposal.action_type,
                    },
                    visible_to=visible_to,
                    domain_tags=["narration", "auto_generated"],
                    parent_event_id=parent_event_id,
                )
                self.ledger.append_event(narration_event)

        except Exception:
            # Don't fail the action if narration fails
            pass

    def _apply_delta(self, delta, conn):
        cur = conn.cursor()
        if delta.table == "state.entities" and delta.operation == "UPDATE":
            changes = delta.changes
            # Handle HP changes
            if "hp_current" in changes and delta.entity_id:
                cur.execute(
                    "UPDATE state.entities SET hp_current = %s, updated_at = now() WHERE id = %s",
                    (changes["hp_current"], str(delta.entity_id)),
                )
            # Handle position changes in public_sheet JSONB
            if ("public_sheet_x" in changes or "public_sheet_y" in changes) and delta.entity_id:
                # Update x and/or y coordinates inside the public_sheet JSONB
                new_x = changes.get("public_sheet_x")
                new_y = changes.get("public_sheet_y")
                if new_x is not None and new_y is not None:
                    cur.execute(
                        """
                        UPDATE state.entities
                        SET public_sheet = jsonb_set(
                            jsonb_set(COALESCE(public_sheet, '{}'::jsonb), '{x}', %s::jsonb),
                            '{y}', %s::jsonb
                        ),
                        updated_at = now()
                        WHERE id = %s
                        """,
                        (str(new_x), str(new_y), str(delta.entity_id)),
                    )
                elif new_x is not None:
                    cur.execute(
                        """
                        UPDATE state.entities
                        SET public_sheet = jsonb_set(COALESCE(public_sheet, '{}'::jsonb), '{x}', %s::jsonb),
                        updated_at = now()
                        WHERE id = %s
                        """,
                        (str(new_x), str(delta.entity_id)),
                    )
                elif new_y is not None:
                    cur.execute(
                        """
                        UPDATE state.entities
                        SET public_sheet = jsonb_set(COALESCE(public_sheet, '{}'::jsonb), '{y}', %s::jsonb),
                        updated_at = now()
                        WHERE id = %s
                        """,
                        (str(new_y), str(delta.entity_id)),
                    )
        elif delta.table == "state.conditions" and delta.operation == "INSERT":
            changes = delta.changes
            cur.execute(
                """
                INSERT INTO state.conditions (entity_id, encounter_id, condition_type, duration_rounds, source)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """,
                (
                    str(delta.entity_id),
                    changes.get("encounter_id"),
                    changes.get("condition_type"),
                    changes.get("duration_rounds", -1),
                    changes.get("source", "unknown"),
                ),
            )
        elif delta.table == "state.conditions" and delta.operation == "DELETE":
            changes = delta.changes
            cur.execute(
                "DELETE FROM state.conditions WHERE entity_id = %s AND condition_type = %s",
                (str(delta.entity_id), changes.get("condition_type")),
            )
        cur.close()

    def _deduct_ap(self, proposal, ap_cost, conn):
        entity_id = proposal.params.get("entity_id") or proposal.params.get(
            "attacker_id"
        )
        if not entity_id:
            return
        encounter = self.state_machine.get_active_encounter(proposal.campaign_id)
        if not encounter:
            return
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE state.encounter_slots
            SET ap_current = GREATEST(0, ap_current - %s)
            WHERE encounter_id = %s AND entity_id = %s
        """,
            (ap_cost, str(encounter["id"]), str(entity_id)),
        )
        cur.close()

    def _log_warning(self, proposal, principal, session_id, reason):
        try:
            from shared.db.connection import execute_query

            rows = execute_query(
                "SELECT principal_id FROM state.campaign_members WHERE campaign_id = %s AND role = 'GM'",
                (str(proposal.campaign_id),),
            )
            visible_to = [r["principal_id"] for r in rows]
            if not visible_to:
                visible_to = [principal.principal_id]

            warning = EventEnvelope(
                type=EventType.SYSTEM_WARNING,
                campaign_id=proposal.campaign_id,
                session_id=session_id,
                sender_principal_id=principal.principal_id,
                payload={
                    "warning": reason,
                    "proposal": {
                        "action_type": proposal.action_type,
                        "proposer": principal.display_name,
                    },
                },
                visible_to=visible_to,
                domain_tags=["validation_failure"],
            )
            self.ledger.append_event(warning)
        except Exception:
            pass
