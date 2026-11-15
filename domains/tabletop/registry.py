from __future__ import annotations

from dataclasses import replace

from domains.tabletop.action_time import with_action_time
from domains.tabletop.activities import command_definitions as activities
from domains.tabletop.battlefield import command_definitions as battlefield
from domains.tabletop.combat import command_definition as combat
from domains.tabletop.combat.tactics import command_definition as guard
from domains.tabletop.dialogue import command_definitions as dialogue
from domains.tabletop.divine import command_definition as divine
from domains.tabletop.economy import command_definition as economy
from domains.tabletop.entities import command_definition as entities
from domains.tabletop.factions import command_definition as factions
from domains.tabletop.magic import command_definition as magic
from domains.tabletop.magic.tactical import command_definition as invoke
from domains.tabletop.onboarding import command_definition as onboarding
from domains.tabletop.quests import command_definition as quests
from domains.tabletop.spatial import command_definition as spatial
from domains.tabletop.spatial.perception import GridSpatialPerceptionResolver
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
        onboarding(),
        *dialogue(),
        entities(),
        spatial(),
        combat(),
        guard(),
        magic(),
        invoke(),
        economy(),
        factions(),
        divine(),
        quests(),
    )
    return tuple(
        replace(definition, version=f"{definition.version}+presentation.1")
        if definition.command_type == "tabletop.battlefield.set_control_mode"
        else replace(
            definition,
            version=f"{definition.version}+voluntary-body.1.action-time.1",
            handler=with_action_time(with_wakeup(definition.handler)),
        )
        if definition.requires_controlled_entity
        else replace(definition, handler=with_motivation(definition.handler, motivation_reader))
        if definition.command_type
        in {"tabletop.clock.tick", "tabletop.clock.advance", "tabletop.routine.configure"}
        else definition
        for definition in definitions
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
