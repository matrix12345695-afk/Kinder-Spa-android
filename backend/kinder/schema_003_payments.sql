-- Kinder Spa schema, version 3: payments.
SET LOCAL search_path TO kinder;

CREATE TABLE payments (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    subscription_id  bigint NOT NULL REFERENCES subscriptions(id),
    amount           numeric(14,2) NOT NULL CHECK (amount > 0),
    method           text NOT NULL CHECK (method IN ('cash','card','click','payme','transfer')),
    paid_at          timestamptz NOT NULL DEFAULT now(),
    staff_id         bigint NOT NULL REFERENCES users(id),
    note             text NOT NULL DEFAULT '',
    voided_at        timestamptz,
    voided_by        bigint REFERENCES users(id),
    void_reason      text,
    CHECK ((voided_at IS NULL) = (voided_by IS NULL))
);
CREATE INDEX payments_subscription ON payments(subscription_id);
CREATE INDEX payments_paid_at ON payments(paid_at);
