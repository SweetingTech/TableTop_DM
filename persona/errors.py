class PersonaGenerationError(ValueError):
    """Base error for deterministic persona generation failures."""


class FixedFieldFeasibilityError(PersonaGenerationError):
    """A caller-fixed dimension cannot coexist with its dependencies or rules."""


class InfeasibleStratumError(PersonaGenerationError):
    """No valid profile can be generated for the requested stratum."""
