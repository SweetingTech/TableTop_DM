import { ApiError, apiRequest, unpackItems } from "../../core/api/client";
import { withDemoFallback } from "../../core/api/fallback";
import type { CompiledPersona, PersonaBlueprint, PersonaSchema, Sourced } from "../../core/api/types";
import { demoPersona, demoPersonaSchema } from "../../core/demo/fixtures";

export type PersonaStudioData = { schema: PersonaSchema; personas: PersonaBlueprint[] };

async function loadSchema(): Promise<PersonaSchema> {
  try {
    return await apiRequest<PersonaSchema>("/personas/schema");
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 404) throw error;
    return apiRequest<PersonaSchema>("/contracts/persona-schema");
  }
}

export async function loadPersonaStudio(): Promise<Sourced<PersonaStudioData>> {
  return withDemoFallback(
    async () => {
      const [schema, personasPayload] = await Promise.all([
        loadSchema(),
        apiRequest<PersonaBlueprint[] | { items?: PersonaBlueprint[] }>("/personas"),
      ]);
      return { schema, personas: unpackItems(personasPayload) };
    },
    () => ({ schema: demoPersonaSchema, personas: [demoPersona(4815162342), demoPersona(1138)] }),
    "Persona studio",
  );
}

export async function generatePersona(seed: number, fixed: Record<string, unknown>): Promise<Sourced<PersonaBlueprint>> {
  return withDemoFallback(
    () => apiRequest<PersonaBlueprint>("/personas/generate", { method: "POST", body: JSON.stringify({ seed, fixed }) }),
    () => {
      const persona = demoPersona(seed);
      return { ...persona, dimensions: { ...persona.dimensions, ...fixed }, provenance: { ...persona.provenance, ...Object.fromEntries(Object.keys(fixed).map((name) => [name, { source: "fixed_demo_assignment", seed }])) } };
    },
    "Persona generation",
  );
}

export async function compilePersona(persona: PersonaBlueprint): Promise<Sourced<CompiledPersona>> {
  return withDemoFallback(
    async () => {
      try {
        return await apiRequest<CompiledPersona>(`/personas/${persona.persona_id}/compile`, { method: "POST" });
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 404) throw error;
        return apiRequest<CompiledPersona>("/personas/compile", { method: "POST", body: JSON.stringify({ persona }) });
      }
    },
    () => ({
      persona_id: persona.persona_id,
      persona_version: persona.schema_version,
      compiler_version: "persona-compiler-demo-1.0.0",
      identity_summary: `A ${String(persona.dimensions.decision_style ?? "deliberative").toLowerCase()} ${String(persona.dimensions.occupation_sector ?? persona.dimensions.occupation ?? "citizen").toLowerCase()} from ${String(persona.dimensions.region ?? "the local region").toLowerCase()}, with ${String(persona.dimensions.risk_tolerance ?? "medium").toLowerCase()} risk tolerance.`,
      policy_weights: { risk_penalty: persona.dimensions.risk_tolerance === "LOW" ? 1.65 : 1, planning_depth: persona.dimensions.decision_style === "DELIBERATIVE" ? 3 : 1, curiosity_weight: persona.dimensions.curiosity === "HIGH" ? 1.45 : 1 },
      starting_goals: ["Maintain personal security", "Understand the immediate situation"],
      retrieval_filters: ["identity", "current-goals", "social-context"],
    }),
    "Persona compilation",
  );
}
