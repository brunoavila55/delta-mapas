CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE accounts (
    id UUID PRIMARY KEY,
    email TEXT UNIQUE NOT NULL CHECK (email = lower(email)),
    password_hash TEXT NOT NULL,
    analysis_limit INTEGER NOT NULL DEFAULT 10 CHECK (analysis_limit >= 0),
    used INTEGER NOT NULL DEFAULT 0 CHECK (used >= 0),
    reserved INTEGER NOT NULL DEFAULT 0 CHECK (reserved >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (used + reserved <= analysis_limit)
);
CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    csrf_token TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL DEFAULT now() + interval '14 days'
);
CREATE INDEX sessions_user ON sessions(user_id);
CREATE INDEX sessions_expiry ON sessions(expires_at);
CREATE TABLE auth_limits (
    key_hash TEXT PRIMARY KEY,
    attempts INTEGER NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX auth_limits_expiry ON auth_limits(expires_at);

CREATE TABLE properties (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES accounts(id),
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, id)
);
CREATE TABLE fields (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES accounts(id),
    property_id UUID NOT NULL,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    revision UUID NOT NULL,
    geometry JSONB NOT NULL,
    shape geometry(MultiPolygon, 4326) NOT NULL,
    area_ha DOUBLE PRECISION NOT NULL CHECK (area_ha > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, id),
    FOREIGN KEY (user_id, property_id) REFERENCES properties(user_id, id),
    CHECK (ST_IsValid(shape) AND NOT ST_IsEmpty(shape))
);
CREATE INDEX fields_shape ON fields USING gist(shape);
CREATE TABLE analyses (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES accounts(id),
    field_id UUID NOT NULL,
    field_revision UUID NOT NULL,
    geometry JSONB NOT NULL,
    date_from DATE NOT NULL,
    date_to DATE NOT NULL CHECK (date_to >= date_from),
    max_cloud DOUBLE PRECISION NOT NULL CHECK (max_cloud BETWEEN 0 AND 100),
    origin TEXT NOT NULL CHECK (origin IN ('manual', 'automatic')),
    mode TEXT NOT NULL CHECK (mode IN ('satellite', 'synthetic')),
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 100),
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_token UUID,
    lease_until TIMESTAMPTZ,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    artifact_attempt UUID,
    statistics JSONB,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    UNIQUE (user_id, idempotency_key),
    FOREIGN KEY (user_id, field_id) REFERENCES fields(user_id, id)
);
CREATE INDEX analyses_queue ON analyses(status, lease_until, created_at);
CREATE INDEX properties_user ON properties(user_id);
CREATE INDEX fields_user ON fields(user_id);
CREATE INDEX analyses_user ON analyses(user_id, created_at);

-- FORCE makes the rules apply even when the normal application role owns tables.
-- Server startup rejects SUPERUSER/BYPASSRLS roles. Worker context is internal only.
CREATE FUNCTION visible_account(owner_id UUID) RETURNS BOOLEAN LANGUAGE SQL STABLE AS $$
    SELECT owner_id = nullif(current_setting('delta.user_id', true), '')::uuid
        OR coalesce(current_setting('delta.worker', true), '') = 'on'
$$;
ALTER TABLE properties ENABLE ROW LEVEL SECURITY;
ALTER TABLE properties FORCE ROW LEVEL SECURITY;
CREATE POLICY properties_owner ON properties USING (visible_account(user_id)) WITH CHECK (visible_account(user_id));
ALTER TABLE fields ENABLE ROW LEVEL SECURITY;
ALTER TABLE fields FORCE ROW LEVEL SECURITY;
CREATE POLICY fields_owner ON fields USING (visible_account(user_id)) WITH CHECK (visible_account(user_id));
ALTER TABLE analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE analyses FORCE ROW LEVEL SECURITY;
CREATE POLICY analyses_owner ON analyses USING (visible_account(user_id)) WITH CHECK (visible_account(user_id));
