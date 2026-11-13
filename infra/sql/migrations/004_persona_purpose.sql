-- Existing immutable identities represent simulated playtesters. Adding defaults
-- classifies their purpose without rewriting their historical content hashes.
ALTER TABLE persona.blueprints
    ADD COLUMN purpose text NOT NULL DEFAULT 'SIMULATED_PLAYTESTER',
    ADD CONSTRAINT blueprints_purpose_check
        CHECK (purpose IN ('SIMULATED_PLAYTESTER', 'CHARACTER')),
    ADD CONSTRAINT blueprints_identity_purpose_key
        UNIQUE (persona_id, version_id, purpose);

ALTER TABLE persona.compiled_profiles
    ADD COLUMN purpose text NOT NULL DEFAULT 'SIMULATED_PLAYTESTER',
    ADD CONSTRAINT compiled_profiles_purpose_check
        CHECK (purpose IN ('SIMULATED_PLAYTESTER', 'CHARACTER')),
    ADD CONSTRAINT compiled_profiles_identity_purpose_fk
        FOREIGN KEY (persona_id, persona_version_id, purpose)
        REFERENCES persona.blueprints (persona_id, version_id, purpose);
