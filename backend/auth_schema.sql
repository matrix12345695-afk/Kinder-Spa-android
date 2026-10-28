-- Explicit prototype migration AFTER schema.sql. Never auto-applied by the API.
CREATE TABLE credentials (
    account_id bigint PRIMARY KEY REFERENCES accounts(id),
    login text NOT NULL UNIQUE CHECK (login ~ '^[a-z0-9][a-z0-9_.-]{2,63}$'),
    salt bytea NOT NULL CHECK (octet_length(salt) = 16),
    verifier bytea NOT NULL CHECK (octet_length(verifier) = 32),
    version bigint NOT NULL DEFAULT 1 CHECK (version > 0)
);
CREATE TABLE auth_sessions (
    token_hash char(64) PRIMARY KEY,
    account_id bigint NOT NULL REFERENCES credentials(account_id),
    credential_version bigint NOT NULL,
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL CHECK (expires_at > created_at),
    revoked boolean NOT NULL DEFAULT false
);
CREATE INDEX sessions_by_account ON auth_sessions(account_id,created_at);
CREATE TABLE login_buckets (
    scope_hash char(64) NOT NULL,
    window_start bigint NOT NULL,
    attempts integer NOT NULL CHECK (attempts >= 0),
    PRIMARY KEY (scope_hash,window_start)
);
