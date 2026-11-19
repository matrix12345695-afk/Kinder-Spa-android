-- Kinder Spa schema, version 7: own cash desk — sales (cart), sellers, cash shifts, single QR payment method.
SET LOCAL search_path TO kinder;

ALTER TABLE payments DROP CONSTRAINT payments_method_check;
ALTER TABLE payments ADD CONSTRAINT payments_method_check
    CHECK (method IN ('cash','card','click','payme','transfer','qr'));

-- One open shift at a time for the whole centre (single reception desk).
CREATE TABLE cash_shifts (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    opened_by      bigint NOT NULL REFERENCES users(id),
    opened_at      timestamptz NOT NULL DEFAULT now(),
    opening_cash   numeric(14,2) NOT NULL DEFAULT 0 CHECK (opening_cash >= 0),
    closed_by      bigint REFERENCES users(id),
    closed_at      timestamptz,
    closing_cash   numeric(14,2) CHECK (closing_cash >= 0),
    expected_cash  numeric(14,2),
    note           text NOT NULL DEFAULT '',
    CHECK ((closed_at IS NULL) = (closed_by IS NULL)),
    CHECK ((closed_at IS NULL) = (closing_cash IS NULL))
);
CREATE UNIQUE INDEX cash_shifts_one_open ON cash_shifts ((true)) WHERE closed_at IS NULL;

-- Cash put into / taken out of the drawer during a shift.
CREATE TABLE cash_ops (
    id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    shift_id  bigint NOT NULL REFERENCES cash_shifts(id),
    kind      text NOT NULL CHECK (kind IN ('in','out')),
    amount    numeric(14,2) NOT NULL CHECK (amount > 0),
    reason    text NOT NULL CHECK (length(btrim(reason)) >= 3),
    staff_id  bigint NOT NULL REFERENCES users(id),
    at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX cash_ops_shift ON cash_ops(shift_id);

-- A sale (receipt) groups the subscriptions sold together and the payments taken for them.
CREATE TABLE sales (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_id   bigint NOT NULL REFERENCES clients(id),
    staff_id    bigint NOT NULL REFERENCES users(id),
    shift_id    bigint REFERENCES cash_shifts(id),
    created_at  timestamptz NOT NULL DEFAULT now(),
    note        text NOT NULL DEFAULT ''
);
CREATE INDEX sales_created ON sales(created_at);

ALTER TABLE subscriptions ADD COLUMN sale_id bigint REFERENCES sales(id);
ALTER TABLE subscriptions ADD COLUMN seller_id bigint REFERENCES specialists(id);
ALTER TABLE payments ADD COLUMN sale_id bigint REFERENCES sales(id);
ALTER TABLE payments ADD COLUMN shift_id bigint REFERENCES cash_shifts(id);
CREATE INDEX payments_shift ON payments(shift_id);
