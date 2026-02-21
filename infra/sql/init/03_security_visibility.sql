ALTER TABLE ledger.session_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE ledger.session_summaries ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS session_ledger_visibility_read ON ledger.session_ledger;
CREATE POLICY session_ledger_visibility_read
  ON ledger.session_ledger
  FOR SELECT
  USING (
    current_setting('app.principal_id', true) <> ''
    AND current_setting('app.principal_id', true)::uuid = ANY(visible_to)
  );

DROP POLICY IF EXISTS session_summaries_visibility_read ON ledger.session_summaries;
CREATE POLICY session_summaries_visibility_read
  ON ledger.session_summaries
  FOR SELECT
  USING (
    current_setting('app.principal_id', true) <> ''
    AND current_setting('app.principal_id', true)::uuid = ANY(visible_to)
  );

DROP POLICY IF EXISTS session_ledger_service_write ON ledger.session_ledger;
CREATE POLICY session_ledger_service_write
  ON ledger.session_ledger
  FOR INSERT
  WITH CHECK (array_length(visible_to, 1) >= 1);

DROP POLICY IF EXISTS session_summaries_service_write ON ledger.session_summaries;
CREATE POLICY session_summaries_service_write
  ON ledger.session_summaries
  FOR INSERT
  WITH CHECK (array_length(visible_to, 1) >= 1);
