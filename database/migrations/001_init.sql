-- Forex Intelligence Lab schema (PostgreSQL / TimescaleDB-compatible)
-- Unique (symbol, timeframe, timestamp) prevents duplicate candles.

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(80) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS symbols (
    id SERIAL PRIMARY KEY,
    name VARCHAR(64) UNIQUE NOT NULL,
    display_name VARCHAR(64) NOT NULL,
    base_code VARCHAR(32) NOT NULL,
    description VARCHAR(255) NOT NULL DEFAULT '',
    digits INTEGER NOT NULL DEFAULT 5,
    point DOUBLE PRECISION NOT NULL DEFAULT 0.00001,
    contract_size DOUBLE PRECISION NOT NULL DEFAULT 100000,
    visible BOOLEAN NOT NULL DEFAULT TRUE,
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS monitored_instruments (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(64) NOT NULL,
    timeframe VARCHAR(8) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_monitored_symbol_tf UNIQUE (symbol, timeframe)
);

CREATE TABLE IF NOT EXISTS market_candles (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(64) NOT NULL,
    timeframe VARCHAR(8) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    bid DOUBLE PRECISION,
    ask DOUBLE PRECISION,
    spread DOUBLE PRECISION,
    tick_volume INTEGER NOT NULL DEFAULT 0,
    real_volume INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_candle_symbol_tf_ts UNIQUE (symbol, timeframe, timestamp)
);

CREATE INDEX IF NOT EXISTS ix_candles_symbol_tf_ts
    ON market_candles (symbol, timeframe, timestamp);

-- Optional TimescaleDB hypertable. Safe to skip if the extension is absent.
-- SELECT create_hypertable('market_candles', 'timestamp', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS features (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(64) NOT NULL,
    timeframe VARCHAR(8) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    values JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_feature_symbol_tf_ts UNIQUE (symbol, timeframe, timestamp)
);

CREATE TABLE IF NOT EXISTS model_versions (
    id SERIAL PRIMARY KEY,
    name VARCHAR(80) NOT NULL,
    version VARCHAR(40) UNIQUE NOT NULL,
    algorithm VARCHAR(64) NOT NULL,
    symbol VARCHAR(64) NOT NULL,
    timeframe VARCHAR(8) NOT NULL,
    feature_list JSONB NOT NULL DEFAULT '[]',
    training_start TIMESTAMPTZ,
    training_end TIMESTAMPTZ,
    train_samples INTEGER NOT NULL DEFAULT 0,
    validation_samples INTEGER NOT NULL DEFAULT 0,
    accuracy DOUBLE PRECISION,
    precision DOUBLE PRECISION,
    recall DOUBLE PRECISION,
    f1 DOUBLE PRECISION,
    roc_auc DOUBLE PRECISION,
    log_loss DOUBLE PRECISION,
    confusion_matrix JSONB,
    strategy_metrics JSONB,
    artifact_path TEXT NOT NULL DEFAULT '',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS model_predictions (
    id SERIAL PRIMARY KEY,
    model_version_id INTEGER REFERENCES model_versions(id),
    model_version VARCHAR(40) NOT NULL,
    symbol VARCHAR(64) NOT NULL,
    timeframe VARCHAR(8) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    probability_up DOUBLE PRECISION NOT NULL,
    probability_down DOUBLE PRECISION NOT NULL,
    prediction VARCHAR(8) NOT NULL,
    actual_outcome INTEGER,
    correct BOOLEAN,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_pred_symbol_tf_ts
    ON model_predictions (symbol, timeframe, timestamp);

CREATE TABLE IF NOT EXISTS collection_jobs (
    id SERIAL PRIMARY KEY,
    kind VARCHAR(32) NOT NULL DEFAULT 'historical_import',
    symbol VARCHAR(64) NOT NULL,
    timeframe VARCHAR(8) NOT NULL,
    start_date TIMESTAMPTZ,
    end_date TIMESTAMPTZ,
    status VARCHAR(24) NOT NULL DEFAULT 'pending',
    candles_imported INTEGER NOT NULL DEFAULT 0,
    candles_requested INTEGER NOT NULL DEFAULT 0,
    duplicate_candles INTEGER NOT NULL DEFAULT 0,
    missing_candles INTEGER NOT NULL DEFAULT 0,
    first_timestamp TIMESTAMPTZ,
    last_timestamp TIMESTAMPTZ,
    duration_seconds DOUBLE PRECISION NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS collection_status (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(64) NOT NULL,
    timeframe VARCHAR(8) NOT NULL,
    last_candle TIMESTAMPTZ,
    candles_collected INTEGER NOT NULL DEFAULT 0,
    collection_rate VARCHAR(32) NOT NULL DEFAULT '',
    status VARCHAR(24) NOT NULL DEFAULT 'IDLE',
    last_error TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_status_symbol_tf UNIQUE (symbol, timeframe)
);

CREATE TABLE IF NOT EXISTS system_events (
    id SERIAL PRIMARY KEY,
    level VARCHAR(16) NOT NULL,
    category VARCHAR(40) NOT NULL,
    message TEXT NOT NULL,
    details JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS alerts (
    id SERIAL PRIMARY KEY,
    kind VARCHAR(40) NOT NULL,
    symbol VARCHAR(64) NOT NULL DEFAULT '',
    timeframe VARCHAR(8) NOT NULL DEFAULT '',
    message TEXT NOT NULL,
    acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
