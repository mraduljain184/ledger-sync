CREATE TABLE IF NOT EXISTS events (
    server_seq    BIGSERIAL PRIMARY KEY,
    event_id      TEXT    NOT NULL UNIQUE,
    merchant      TEXT    NOT NULL,
    device        TEXT    NOT NULL,
    hlc_wall      BIGINT  NOT NULL,
    hlc_counter   INTEGER NOT NULL,
    hlc_device    TEXT    NOT NULL,
    entry         TEXT    NOT NULL,
    op            TEXT    NOT NULL,
    party         TEXT    NOT NULL DEFAULT '',
    amount        BIGINT  NOT NULL DEFAULT 0,
    note          TEXT    NOT NULL DEFAULT '',
    base          TEXT,
    clock_suspect BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS events_merchant_seq ON events (merchant, server_seq);

CREATE TABLE IF NOT EXISTS batches (
    batch_id TEXT  PRIMARY KEY,
    response JSONB NOT NULL
);