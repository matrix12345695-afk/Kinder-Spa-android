-- Explicit additive migration AFTER schema.sql and auth_schema.sql.
-- Apply only to a reviewed dedicated Kinder database, never on API startup.
CREATE TABLE telegram_link_codes (
    code_hash char(64) PRIMARY KEY,
    account_id bigint NOT NULL REFERENCES credentials(account_id),
    credential_version bigint NOT NULL,
    expires_at timestamptz NOT NULL,
    used_peer bigint,
    used_update bigint,
    revoked boolean NOT NULL DEFAULT false
);
CREATE TABLE telegram_bindings (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id bigint NOT NULL REFERENCES credentials(account_id),
    credential_version bigint NOT NULL,
    peer_id bigint NOT NULL CHECK(peer_id>0),
    language text NOT NULL DEFAULT 'ru' CHECK(language IN ('ru','uz')),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL
);
CREATE UNIQUE INDEX telegram_one_account ON telegram_bindings(account_id) WHERE active;
CREATE UNIQUE INDEX telegram_one_peer ON telegram_bindings(peer_id) WHERE active;
CREATE TABLE telegram_updates (
    update_id bigint PRIMARY KEY CHECK(update_id>=0),
    peer_id bigint NOT NULL CHECK(peer_id>0),
    done boolean NOT NULL DEFAULT true
);
CREATE TABLE telegram_runtime (
    singleton integer PRIMARY KEY CHECK(singleton=1),
    bot_id bigint CHECK(bot_id>0),
    username text,
    next_offset bigint NOT NULL DEFAULT 0 CHECK(next_offset>=0)
);
INSERT INTO telegram_runtime VALUES(1,NULL,NULL,0);
CREATE TABLE telegram_actions (
    id uuid PRIMARY KEY,
    binding_id bigint NOT NULL REFERENCES telegram_bindings(id),
    update_id bigint NOT NULL UNIQUE,
    kind text NOT NULL CHECK(kind IN ('cancel','restore','redeem','unlink')),
    booking_id bigint,
    reason text,
    qr_hash char(64) REFERENCES qr_tokens(token_hash),
    expires_at timestamptz NOT NULL,
    state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','applied','rejected'))
);
CREATE TABLE telegram_notification_batches (
    outbox_id bigint PRIMARY KEY REFERENCES notification_outbox(id),
    created_at timestamptz NOT NULL
);
CREATE TABLE telegram_jobs (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dedup text NOT NULL UNIQUE,
    peer_id bigint NOT NULL CHECK(peer_id>0),
    binding_id bigint REFERENCES telegram_bindings(id),
    outbox_id bigint REFERENCES notification_outbox(id),
    kind text NOT NULL CHECK(kind IN ('text','qr','link')),
    payload jsonb NOT NULL,
    state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','leased','delivered','failed','blocked')),
    attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 8),
    next_at timestamptz NOT NULL,
    lease_id uuid,
    lease_until timestamptz,
    message_id bigint,
    error_code integer,
    CHECK(binding_id IS NOT NULL OR (kind='text' AND payload->>'public'='true'))
);
CREATE INDEX telegram_ready ON telegram_jobs(state,next_at,id);
CREATE TABLE telegram_qr_cleanup (
    peer_id bigint NOT NULL,
    message_id bigint NOT NULL,
    delete_at timestamptz NOT NULL,
    attempts integer NOT NULL DEFAULT 0,
    done boolean NOT NULL DEFAULT false,
    PRIMARY KEY(peer_id,message_id)
);
