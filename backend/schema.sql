-- Explicit, additive first-install schema for a NEW, dedicated prototype database.
-- Never automatically apply to an existing production database.
CREATE TABLE accounts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    role text NOT NULL CHECK (role IN ('client','admin','superadmin')),
    enabled boolean NOT NULL DEFAULT true
);
CREATE TABLE subscriptions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_id bigint NOT NULL REFERENCES accounts(id)
);
CREATE TABLE allowances (
    subscription_id bigint NOT NULL REFERENCES subscriptions(id),
    category text NOT NULL CHECK (category IN ('massage','hydromassage','pool')),
    quota integer NOT NULL,
    remaining integer NOT NULL CHECK (remaining >= 0 AND remaining <= quota),
    PRIMARY KEY (subscription_id, category),
    CHECK ((category IN ('massage','hydromassage') AND quota = 10) OR
           (category = 'pool' AND quota IN (4,8,12)))
);
CREATE TABLE bookings (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    subscription_id bigint NOT NULL,
    category text NOT NULL,
    starts_at timestamptz NOT NULL,
    ends_at timestamptz NOT NULL CHECK (ends_at > starts_at),
    state text NOT NULL CHECK (state IN ('reserved','consumed','cancelled','forfeited','no_show','restored')),
    FOREIGN KEY (subscription_id, category) REFERENCES allowances(subscription_id, category),
    UNIQUE (subscription_id, starts_at)
);
-- Capacity/instructor scheduling is deliberately not inferred from subscription balance.
CREATE TABLE qr_tokens (
    token_hash char(64) PRIMARY KEY,
    booking_id bigint NOT NULL REFERENCES bookings(id),
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    revoked boolean NOT NULL DEFAULT false
);
CREATE INDEX qr_booking ON qr_tokens(booking_id);
CREATE TABLE operations (
    actor_id bigint NOT NULL REFERENCES accounts(id),
    operation text NOT NULL,
    request_key text NOT NULL,
    request_hash char(64) NOT NULL,
    result jsonb,
    PRIMARY KEY (actor_id, operation, request_key)
);
CREATE TABLE audit_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_id bigint NOT NULL REFERENCES accounts(id),
    operation text NOT NULL,
    entity_id bigint NOT NULL,
    at timestamptz NOT NULL,
    details jsonb NOT NULL
);
CREATE FUNCTION immutable_audit() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'audit is append-only'; END;
$$;
CREATE TRIGGER audit_no_update BEFORE UPDATE OR DELETE ON audit_events
FOR EACH ROW EXECUTE FUNCTION immutable_audit();
-- Recipient is the configured superadministrator role, resolved by a future trusted sender.
-- A pending row proves durable enqueueing, NOT Telegram delivery or owner approval.
CREATE TABLE notification_outbox (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id bigint NOT NULL UNIQUE REFERENCES audit_events(id),
    recipient_role text NOT NULL CHECK (recipient_role = 'superadmin'),
    kind text NOT NULL CHECK (kind = 'session_restored'),
    created_at timestamptz NOT NULL
);

-- The Telegram sender claims rows with FOR UPDATE, which needs UPDATE privilege.
-- Block actual queue-row modification by that runtime role; delivery state lives
-- in telegram_notification_batches and telegram_jobs instead.
CREATE TRIGGER notification_outbox_no_update
BEFORE UPDATE OR DELETE ON notification_outbox
FOR EACH ROW EXECUTE FUNCTION immutable_audit();
