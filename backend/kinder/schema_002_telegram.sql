-- Kinder Spa schema, version 2: Telegram bot.
SET LOCAL search_path TO kinder;

-- One row per Telegram private chat. A chat is "linked" while user_id is set and
-- cred_version still matches users.cred_version (password reset unlinks it).
CREATE TABLE telegram_chats (
    chat_id       bigint PRIMARY KEY,
    user_id       bigint REFERENCES users(id),
    cred_version  integer,
    state         text NOT NULL DEFAULT 'idle',
    state_data    jsonb NOT NULL DEFAULT '{}'::jsonb,
    first_name    text NOT NULL DEFAULT '',
    linked_at     timestamptz,
    updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX telegram_chats_user ON telegram_chats(user_id);

-- Telegram retries webhooks; remember processed update ids.
CREATE TABLE telegram_updates (
    update_id    bigint PRIMARY KEY,
    received_at  timestamptz NOT NULL DEFAULT now()
);

-- Durable notification queue, filled inside business transactions.
CREATE TABLE telegram_outbox (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chat_id     bigint NOT NULL,
    text        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    sent_at     timestamptz,
    attempts    integer NOT NULL DEFAULT 0,
    last_error  text
);
CREATE INDEX telegram_outbox_pending ON telegram_outbox(id) WHERE sent_at IS NULL;

-- Daily reminders are sent once per subscription and kind.
CREATE TABLE reminders_sent (
    subscription_id  bigint NOT NULL REFERENCES subscriptions(id),
    kind             text NOT NULL,
    sent_on          date NOT NULL,
    PRIMARY KEY (subscription_id, kind)
);

-- Once-a-day jobs (e.g. staff digest) record their run date here.
CREATE TABLE job_runs (
    job     text NOT NULL,
    run_on  date NOT NULL,
    PRIMARY KEY (job, run_on)
);
