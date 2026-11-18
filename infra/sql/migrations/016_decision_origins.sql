-- Keep all original input origins. New labels describe trusted decision sources,
-- independently of the actor and controller authority used to execute a command.
ALTER TABLE sim.command_log
  DROP CONSTRAINT command_log_input_origin_check,
  ADD CONSTRAINT command_log_input_origin_check CHECK (
    input_origin IN (
      'UNSPECIFIED', 'HUMAN_INPUT', 'POLICY_ADVICE', 'OPERATOR',
      'STAND_IN', 'NPC_POLICY', 'NPC_MODEL', 'DIRECTOR'
    )
  ),
  ADD CONSTRAINT command_log_character_origin_check CHECK (
    input_origin NOT IN ('STAND_IN', 'NPC_POLICY', 'NPC_MODEL') OR (
      decision_authorship = 'CHARACTER_POLICY' AND embodied_entity_id IS NOT NULL
      AND control_epoch IS NOT NULL AND control_step IS NOT NULL
    )
  );
