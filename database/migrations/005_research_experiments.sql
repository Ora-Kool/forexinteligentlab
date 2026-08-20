-- Reproducible, workspace-scoped strategy research.

CREATE TABLE IF NOT EXISTS research_experiments (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL DEFAULT 0,
    code VARCHAR(80) NOT NULL,
    strategy_name VARCHAR(120) NOT NULL DEFAULT 'Triple barrier logistic',
    symbol VARCHAR(64) NOT NULL,
    timeframe VARCHAR(8) NOT NULL,
    target_version VARCHAR(40) NOT NULL DEFAULT 'triple_barrier_v1',
    feature_version VARCHAR(40) NOT NULL DEFAULT 'causal_features_v1',
    evaluator_version VARCHAR(40) NOT NULL DEFAULT 'purged_walk_forward_v1',
    model_family VARCHAR(64) NOT NULL DEFAULT 'LogisticRegression',
    dataset_version VARCHAR(80) NOT NULL DEFAULT '',
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    parameters JSONB NOT NULL DEFAULT '{}',
    metrics JSONB,
    error TEXT NOT NULL DEFAULT '',
    train_start TIMESTAMPTZ,
    train_end TIMESTAMPTZ,
    holdout_start TIMESTAMPTZ,
    holdout_end TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    CONSTRAINT uq_research_experiment_ws_code UNIQUE (workspace_id, code)
);

CREATE INDEX IF NOT EXISTS ix_research_experiment_symbol_tf
    ON research_experiments (workspace_id, symbol, timeframe);
CREATE INDEX IF NOT EXISTS ix_research_experiment_status
    ON research_experiments (status);

CREATE TABLE IF NOT EXISTS research_folds (
    id SERIAL PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES research_experiments(id) ON DELETE CASCADE,
    fold_index INTEGER NOT NULL,
    train_start TIMESTAMPTZ,
    train_end TIMESTAMPTZ,
    validation_start TIMESTAMPTZ,
    validation_end TIMESTAMPTZ,
    threshold DOUBLE PRECISION,
    train_samples INTEGER NOT NULL DEFAULT 0,
    validation_samples INTEGER NOT NULL DEFAULT 0,
    signals INTEGER NOT NULL DEFAULT 0,
    metrics JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_research_fold_experiment_index UNIQUE (experiment_id, fold_index)
);

CREATE INDEX IF NOT EXISTS ix_research_fold_experiment
    ON research_folds (experiment_id);
