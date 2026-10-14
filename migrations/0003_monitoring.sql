CREATE TABLE monitoring (
    user_id UUID NOT NULL,
    field_id UUID PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT false,
    generation UUID NOT NULL,
    crop TEXT NOT NULL CHECK (length(crop) BETWEEN 1 AND 80),
    stage TEXT NOT NULL DEFAULT 'vegetative' CHECK (stage IN ('vegetative','reproductive','maturation','harvest')),
    season_start DATE NOT NULL,
    season_end DATE NOT NULL CHECK (season_end >= season_start),
    drop_threshold DOUBLE PRECISION NOT NULL CHECK (drop_threshold BETWEEN 0.05 AND 1),
    next_run TIMESTAMPTZ NOT NULL DEFAULT now(),
    state TEXT NOT NULL DEFAULT 'scheduled',
    FOREIGN KEY (user_id,field_id) REFERENCES fields(user_id,id)
);
ALTER TABLE analyses ADD COLUMN monitor_generation UUID;
ALTER TABLE analyses ADD COLUMN scene_date DATE;
ALTER TABLE analyses ADD CONSTRAINT analyses_owner_id UNIQUE(user_id,id);
CREATE TABLE monitoring_alerts (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    field_id UUID NOT NULL,
    analysis_id UUID NOT NULL UNIQUE,
    previous_id UUID NOT NULL,
    previous_mean DOUBLE PRECISION NOT NULL,
    current_mean DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    read_at TIMESTAMPTZ,
    FOREIGN KEY (user_id,field_id) REFERENCES fields(user_id,id),
    FOREIGN KEY (user_id,analysis_id) REFERENCES analyses(user_id,id),
    FOREIGN KEY (user_id,previous_id) REFERENCES analyses(user_id,id)
);


CREATE INDEX monitoring_due ON monitoring(next_run) WHERE enabled;
CREATE INDEX monitoring_alerts_user ON monitoring_alerts(user_id,created_at);
CREATE INDEX analyses_comparison ON analyses(user_id,field_id,scene_date) WHERE status='completed';
ALTER TABLE monitoring ENABLE ROW LEVEL SECURITY;
ALTER TABLE monitoring FORCE ROW LEVEL SECURITY;
CREATE POLICY monitoring_owner ON monitoring USING (visible_account(user_id)) WITH CHECK (visible_account(user_id));
ALTER TABLE monitoring_alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE monitoring_alerts FORCE ROW LEVEL SECURITY;
CREATE POLICY monitoring_alerts_owner ON monitoring_alerts USING (visible_account(user_id)) WITH CHECK (visible_account(user_id));
