from __future__ import annotations

from domains.tabletop.combat import command_definition as combat
from domains.tabletop.dialogue import command_definition as dialogue
from domains.tabletop.divine import command_definition as divine
from domains.tabletop.economy import command_definition as economy
from domains.tabletop.entities import command_definition as entities
from domains.tabletop.factions import command_definition as factions
from domains.tabletop.magic import command_definition as magic
from domains.tabletop.onboarding import command_definition as onboarding
from domains.tabletop.quests import command_definition as quests
from domains.tabletop.spatial import command_definition as spatial
from kernel.command_bus import CommandBus, CommandDefinition


def command_definitions() -> tuple[CommandDefinition, ...]:
    return (
        onboarding(),
        dialogue(),
        entities(),
        spatial(),
        combat(),
        magic(),
        economy(),
        factions(),
        divine(),
        quests(),
    )


def register_tabletop(bus: CommandBus) -> CommandBus:
    for definition in command_definitions():
        bus.register(definition)
    return bus
