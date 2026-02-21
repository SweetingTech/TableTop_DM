ALTER TABLE ledger.session_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE ledger.session_summaries ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS session_ledger_visibility_read ON ledger.session_ledger;
CREATE POLICY session_ledger_visibility_read
  ON ledger.session_ledger
  FOR SELECT
  USING (
    visible_to::text[] @> ARRAY[current_setting('app.principal_id', true)]
  );

DROP POLICY IF EXISTS session_summaries_visibility_read ON ledger.session_summaries;
CREATE POLICY session_summaries_visibility_read
  ON ledger.session_summaries
  FOR SELECT
  USING (
    visible_to::text[] @> ARRAY[current_setting('app.principal_id', true)]
  );

DROP POLICY IF EXISTS session_ledger_service_write ON ledger.session_ledger;
CREATE POLICY session_ledger_service_write
  ON ledger.session_ledger
  FOR INSERT
  WITH CHECK (cardinality(visible_to) > 0);

DROP POLICY IF EXISTS session_summaries_service_write ON ledger.session_summaries;
CREATE POLICY session_summaries_service_write
  ON ledger.session_summaries
  FOR INSERT
  WITH CHECK (cardinality(visible_to) > 0);
