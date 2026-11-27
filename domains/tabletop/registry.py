from __future__ import annotations

from dataclasses import replace

from domains.tabletop.action_time import with_action_time
from domains.tabletop.activities import command_definitions as activities
from domains.tabletop.battlefield import command_definitions as battlefield
from domains.tabletop.body_configuration import command_definitions as body_configuration
from domains.tabletop.combat import command_definition as combat
from domains.tabletop.combat.tactics import command_definition as guard
from domains.tabletop.dialogue import command_definitions as dialogue
from domains.tabletop.divine import command_definition as divine
from domains.tabletop.economy import command_definitions as economy
from domains.tabletop.effects import command_definition as conditions
from domains.tabletop.entities import command_definition as entities
from domains.tabletop.entities.control import command_definition as entity_controllers
from domains.tabletop.factions import command_definition as factions
from domains.tabletop.initiative import command_definitions as initiative
from domains.tabletop.magic import command_definition as magic
from domains.tabletop.magic.tactical import command_definition as invoke
from domains.tabletop.onboarding import command_definition as onboarding
from domains.tabletop.parties import command_definitions as parties
from domains.tabletop.party_coordination import command_definitions as party_coordination
from domains.tabletop.quests import command_definitions as quests
from domains.tabletop.quests.evidence import EVIDENCE_COMMANDS, with_quest_evidence
from domains.tabletop.recovery import command_definition as stabilize
from domains.tabletop.recovery import with_recovery
from domains.tabletop.rest import command_definitions as rest
from domains.tabletop.rest import with_rest_interruptions
from domains.tabletop.spatial import command_definition as spatial
from domains.tabletop.spatial.perception import GridSpatialPerceptionResolver
from domains.tabletop.spatial.presentation import command_definition as map_presentation
from domains.tabletop.world_time import command_definitions as world_time
from kernel.command_bus import CommandBus, CommandDefinition, CommandHandler
from population.life import command_definitions as life
from population.motivation import GoalInputReader, with_motivation
from population.routines import command_definitions as routines
from population.runtime import command_definitions as population


def command_definitions(
    motivation_reader: GoalInputReader | None = None,
) -> tuple[CommandDefinition, ...]:
    definitions = (
        *world_time(),
        *activities(),
        *population(),
        *routines(),
        *life(),
        *battlefield(),
        *body_configuration(),
        onboarding(),
        *dialogue(),
        entities(),
        entity_controllers(),
        conditions(),
        spatial(),
        map_presentation(),
        combat(),
        stabilize(),
        *rest(),
        *initiative(),
        guard(),
        magic(),
        invoke(),
        *economy(),
        factions(),
        divine(),
        *quests(),
        *parties(),
        *party_coordination(),
    )
    wrapped = tuple(
        replace(definition, version=f"{definition.version}+presentation.1")
        if definition.command_type == "tabletop.battlefield.set_control_mode"
        else replace(
            definition,
            version=f"{definition.version}+voluntary-body.2.action-time.1.recovery.1.rest.1.initiative.1",
            handler=with_action_time(
                with_wakeup(with_rest_interruptions(with_recovery(definition.handler)))
            ),
        )
        if definition.requires_controlled_entity
        else replace(definition, handler=with_motivation(definition.handler, motivation_reader))
        if definition.command_type
        in {"tabletop.clock.tick", "tabletop.clock.advance", "tabletop.routine.configure"}
        else definition
        for definition in definitions
    )
    return tuple(
        replace(
            definition,
            version=f"{definition.version}+quest-evidence.1",
            handler=with_quest_evidence(definition.handler),
        )
        if definition.command_type in EVIDENCE_COMMANDS
        else definition
        for definition in wrapped
    )


def with_wakeup(handler: CommandHandler) -> CommandHandler:
    from population.life import wake_after_action

    def execute(proposal, state):
        return wake_after_action(proposal, state, handler)

    return execute


def register_tabletop(
    bus: CommandBus, motivation_reader: GoalInputReader | None = None
) -> CommandBus:
    bus.event_factory.resolver = GridSpatialPerceptionResolver()
    for definition in command_definitions(motivation_reader):
        bus.register(definition)
    return bus
