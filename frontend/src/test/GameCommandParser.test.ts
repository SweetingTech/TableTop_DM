import { describe, expect, it } from "vitest";
import { demoGameState } from "../core/demo/fixtures";
import { parseCommand } from "../features/game-console/api";
import { entityMapPosition } from "../features/game-console/mapPosition";

describe("typed game command parser", () => {
  it("only submits an equipment intent without supplying stats", () => {
    expect(parseCommand("/equip spear", demoGameState)).toEqual({
      commandType: "tabletop.equipment.equip", parameters: { weapon_id: "SPEAR" } });
    for (const text of ["/equip", "/equip LASER", "/equip SPEAR 100"]) {
      expect(() => parseCommand(text, demoGameState)).toThrow("Use /equip");
    }
  });
  it("only permits server-owned rest choices", () => {
    expect(parseCommand("/rest short", demoGameState)).toEqual({
      commandType: "tabletop.rest.start", parameters: { kind: "SHORT" } });
    expect(parseCommand("/rest LONG", demoGameState)).toEqual({
      commandType: "tabletop.rest.start", parameters: { kind: "LONG" } });
    for (const input of ["/rest", "/rest 1", "/rest long 1", "/rest short 999"]) {
      expect(() => parseCommand(input, demoGameState)).toThrow("Use /rest short|long");
    }
  });
  it("uses server-owned guard and spell invocation contracts", () => {
    expect(parseCommand("/guard", demoGameState)).toEqual({ commandType: "tabletop.combat.guard", parameters: {} });
    expect(parseCommand("/stabilize Dockmaster Vale", demoGameState)).toEqual({
      commandType: "tabletop.combat.stabilize", parameters: { target_id: demoGameState.entities[1].entity_id } });
    expect(() => parseCommand("/stabilize", demoGameState)).toThrow(/perceived target/);
    expect(() => parseCommand("/stabilize Nobody", demoGameState)).toThrow(/Unknown target/);
    expect(parseCommand("/invoke ARCANE_BOLT Dockmaster Vale", demoGameState)).toEqual({
      commandType: "tabletop.magic.invoke", parameters: { spell_id: "ARCANE_BOLT", target_id: demoGameState.entities[1].entity_id } });
    expect(() => parseCommand("/guard 999", demoGameState)).toThrow();
    expect(() => parseCommand("/invoke UNKNOWN Dockmaster Vale", demoGameState)).toThrow();
    expect(parseCommand("/cast MEND Dockmaster Vale", demoGameState)).toEqual({
      commandType: "tabletop.magic.cast", parameters: { spell_id: "MEND", target_id: demoGameState.entities[1].entity_id } });
    expect(() => parseCommand("/cast Dockmaster damage 10000 0 Fireball", demoGameState)).toThrow();
  });
  it("maps movement and attacks to typed deterministic proposals", () => {
    expect(parseCommand("/move north", demoGameState)).toEqual({
      commandType: "tabletop.spatial.move",
      parameters: { dx: 0, dy: -1 },
    });
    const first = parseCommand("/attack Dockmaster Vale", demoGameState);
    const repeated = parseCommand("/attack Dockmaster Vale", demoGameState);
    expect(first.commandType).toBe("tabletop.combat.attack");
    expect(first.parameters.target_id).toBe(demoGameState.entities[1].entity_id);
    expect(first.seed).toBe(repeated.seed);
  });

  it("keeps natural dialogue typed and rejects malformed mechanics", () => {
    expect(parseCommand("We should parley.", demoGameState)).toEqual({
      commandType: "tabletop.dialogue.speak",
      parameters: { text: "We should parley.", volume: "NORMAL", language: "common" },
    });
    expect(() => parseCommand("/move 9 0", demoGameState)).toThrow(/-1\.\.1/);
    expect(() => parseCommand("/attack Nobody", demoGameState)).toThrow(/Unknown target/);
  });

  it("rejects unsupported slash commands with the supported actions", () => {
    for (const command of ["/teleport moon", "/", "  /dance wildly  "]) {
      expect(() => parseCommand(command, demoGameState)).toThrow(
        "Unsupported command. Use /move, /attack, /guard, /stabilize, /rest, /equip, /cast, /invoke, or type dialogue.",
      );
    }
  });

  it("maps tokens from canonical public grid coordinates", () => {
    const bounds = { min_x: -2, max_x: 7, min_y: 0, max_y: 9 };
    expect(entityMapPosition({ public_state: { x: 2, y: 3 } }, bounds)).toEqual({
      left: "45%",
      top: "35%",
    });
    expect(entityMapPosition({ public_state: { x: 4, y: 1 } }, bounds)).not.toEqual(
      entityMapPosition({ public_state: { x: 2, y: 3 } }, bounds),
    );
    expect(entityMapPosition({ public_state: {} }, bounds)).toBeNull();
    expect(entityMapPosition({ public_state: { x: 50, y: 3 } }, bounds)).toBeNull();
  });
});
