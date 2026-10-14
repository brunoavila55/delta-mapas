ALTER TABLE analyses ADD COLUMN report_context JSONB NOT NULL DEFAULT '{}'::jsonb;
