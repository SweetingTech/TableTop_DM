import { describe, expect, it } from "vitest";
import { demoGameState } from "../core/demo/fixtures";
import { parseCommand } from "../features/game-console/api";
import { entityMapPosition } from "../features/game-console/mapPosition";

describe("typed game command parser", () => {
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
      commandType: "tabletop.console.submit",
      parameters: { text: "We should parley." },
    });
    expect(() => parseCommand("/move 9 0", demoGameState)).toThrow(/-1\.\.1/);
    expect(() => parseCommand("/attack Nobody", demoGameState)).toThrow(/Unknown target/);
  });

  it("maps tokens from canonical public grid coordinates", () => {
    expect(entityMapPosition({ public_state: { x: 2, y: 3 } })).toEqual({
      left: "42%",
      top: "57%",
    });
    expect(entityMapPosition({ public_state: { x: 4, y: 1 } })).not.toEqual(
      entityMapPosition({ public_state: { x: 2, y: 3 } }),
    );
  });
});
