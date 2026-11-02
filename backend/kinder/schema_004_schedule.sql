-- Kinder Spa schema, version 4: schedule and bookings.
SET LOCAL search_path TO kinder;

-- Late cancellation (after 19:00 the day before) or no-show burns a visit for these services.
ALTER TABLE services ADD COLUMN late_cancel_forfeit boolean NOT NULL DEFAULT false;
UPDATE services SET late_cancel_forfeit = true WHERE code = 'pool';

ALTER TABLE visits DROP CONSTRAINT IF EXISTS visits_method_check;
ALTER TABLE visits ADD CONSTRAINT visits_method_check CHECK (method IN ('qr','manual','late_cancel','no_show'));

CREATE TABLE slots (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    service_id     bigint NOT NULL REFERENCES services(id),
    specialist_id  bigint REFERENCES specialists(id),
    starts_at      timestamptz NOT NULL,
    ends_at        timestamptz NOT NULL CHECK (ends_at > starts_at),
    capacity       integer NOT NULL CHECK (capacity BETWEEN 1 AND 100),
    note           text NOT NULL DEFAULT '',
    created_by     bigint NOT NULL REFERENCES users(id),
    cancelled_at   timestamptz,
    cancel_reason  text
);
CREATE UNIQUE INDEX slots_unique_live ON slots(service_id, coalesce(specialist_id, 0), starts_at) WHERE cancelled_at IS NULL;
CREATE INDEX slots_starts ON slots(starts_at);

CREATE TABLE bookings (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slot_id          bigint NOT NULL REFERENCES slots(id),
    subscription_id  bigint NOT NULL REFERENCES subscriptions(id),
    client_id        bigint NOT NULL REFERENCES clients(id),
    child_id         bigint REFERENCES children(id),
    status           text NOT NULL DEFAULT 'booked' CHECK (status IN ('booked','cancelled','attended','no_show')),
    created_at       timestamptz NOT NULL DEFAULT now(),
    created_by       bigint NOT NULL REFERENCES users(id),
    cancelled_at     timestamptz,
    cancelled_by     bigint REFERENCES users(id),
    cancel_reason    text,
    forfeited        boolean NOT NULL DEFAULT false,
    visit_id         bigint REFERENCES visits(id)
);
CREATE UNIQUE INDEX bookings_one_per_child ON bookings(slot_id, client_id, coalesce(child_id, 0)) WHERE status IN ('booked','attended');
CREATE INDEX bookings_slot ON bookings(slot_id);
CREATE INDEX bookings_subscription ON bookings(subscription_id);
