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
-- These identity columns support a column-scoped UPDATE permission only for
-- SELECT ... FOR SHARE row locks. No actual identity mutation is permitted.
CREATE TRIGGER credentials_account_immutable BEFORE UPDATE OF account_id ON credentials
FOR EACH ROW EXECUTE FUNCTION immutable_identifier();
CREATE TRIGGER sessions_token_immutable BEFORE UPDATE OF token_hash ON auth_sessions
FOR EACH ROW EXECUTE FUNCTION immutable_identifier();
CREATE TABLE login_buckets (
    scope_hash char(64) NOT NULL,
    window_start bigint NOT NULL,
    attempts integer NOT NULL CHECK (attempts >= 0),
    PRIMARY KEY (scope_hash,window_start)
);
