-- Kinder Spa schema, version 1. Applied once by kinder.migrate inside a transaction.
CREATE SCHEMA IF NOT EXISTS kinder;
SET LOCAL search_path TO kinder;

CREATE TABLE users (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    role          text NOT NULL CHECK (role IN ('superadmin','admin','client')),
    login         text NOT NULL UNIQUE CHECK (login ~ '^[a-z0-9][a-z0-9_.-]{2,63}$'),
    salt          bytea NOT NULL,
    verifier      bytea NOT NULL,
    cred_version  integer NOT NULL DEFAULT 1,
    full_name     text NOT NULL DEFAULT '',
    enabled       boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
    token_hash    char(64) PRIMARY KEY,
    user_id       bigint NOT NULL REFERENCES users(id),
    cred_version  integer NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz NOT NULL,
    revoked       boolean NOT NULL DEFAULT false
);
CREATE INDEX sessions_user ON sessions(user_id);

CREATE TABLE login_attempts (
    id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    scope   text NOT NULL,
    at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX login_attempts_scope ON login_attempts(scope, at);

-- Parents / guardians. A client may get an app login (users.role = 'client').
CREATE TABLE clients (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     bigint UNIQUE REFERENCES users(id),
    full_name   text NOT NULL CHECK (length(btrim(full_name)) BETWEEN 2 AND 200),
    phone       text NOT NULL DEFAULT '',
    note        text NOT NULL DEFAULT '',
    archived    boolean NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX clients_phone ON clients(phone);

CREATE TABLE children (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_id   bigint NOT NULL REFERENCES clients(id),
    full_name   text NOT NULL CHECK (length(btrim(full_name)) BETWEEN 2 AND 200),
    birth_date  date,
    note        text NOT NULL DEFAULT '',
    archived    boolean NOT NULL DEFAULT false
);
CREATE INDEX children_client ON children(client_id);

CREATE TABLE services (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code            text NOT NULL UNIQUE CHECK (code ~ '^[a-z][a-z0-9_]{1,30}$'),
    name_ru         text NOT NULL,
    name_uz         text NOT NULL DEFAULT '',
    description_ru  text NOT NULL DEFAULT '',
    description_uz  text NOT NULL DEFAULT '',
    duration_min    integer NOT NULL CHECK (duration_min BETWEEN 5 AND 240),
    active          boolean NOT NULL DEFAULT true,
    sort            integer NOT NULL DEFAULT 0
);

CREATE TABLE service_photos (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    service_id    bigint NOT NULL REFERENCES services(id),
    content_type  text NOT NULL CHECK (content_type IN ('image/jpeg','image/png','image/webp')),
    data          bytea NOT NULL CHECK (octet_length(data) <= 2097152),
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX service_photos_service ON service_photos(service_id);

CREATE TABLE specialists (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    full_name   text NOT NULL CHECK (length(btrim(full_name)) BETWEEN 2 AND 200),
    phone       text NOT NULL DEFAULT '',
    bio         text NOT NULL DEFAULT '',
    active      boolean NOT NULL DEFAULT true
);
CREATE TABLE specialist_services (
    specialist_id  bigint NOT NULL REFERENCES specialists(id),
    service_id     bigint NOT NULL REFERENCES services(id),
    PRIMARY KEY (specialist_id, service_id)
);

-- Tariffs: a plan grants visits per service (one or several services).
CREATE TABLE plans (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name           text NOT NULL CHECK (length(btrim(name)) BETWEEN 2 AND 200),
    validity_days  integer NOT NULL CHECK (validity_days BETWEEN 1 AND 730),
    price          numeric(14,2) NOT NULL DEFAULT 0 CHECK (price >= 0),
    active         boolean NOT NULL DEFAULT true
);
CREATE TABLE plan_items (
    plan_id     bigint NOT NULL REFERENCES plans(id),
    service_id  bigint NOT NULL REFERENCES services(id),
    visits      integer NOT NULL CHECK (visits BETWEEN 1 AND 500),
    PRIMARY KEY (plan_id, service_id)
);

CREATE TABLE subscriptions (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_id     bigint NOT NULL REFERENCES clients(id),
    child_id      bigint REFERENCES children(id),
    plan_id       bigint REFERENCES plans(id),
    name          text NOT NULL,
    price         numeric(14,2) NOT NULL DEFAULT 0 CHECK (price >= 0),
    status        text NOT NULL DEFAULT 'active' CHECK (status IN ('active','frozen','closed')),
    starts_on     date NOT NULL,
    ends_on       date NOT NULL CHECK (ends_on >= starts_on),
    frozen_since  date,
    created_by    bigint NOT NULL REFERENCES users(id),
    created_at    timestamptz NOT NULL DEFAULT now(),
    CHECK ((status = 'frozen') = (frozen_since IS NOT NULL))
);
CREATE INDEX subscriptions_client ON subscriptions(client_id);
CREATE INDEX subscriptions_ends ON subscriptions(ends_on) WHERE status <> 'closed';

CREATE TABLE subscription_items (
    subscription_id  bigint NOT NULL REFERENCES subscriptions(id),
    service_id       bigint NOT NULL REFERENCES services(id),
    quota            integer NOT NULL CHECK (quota >= 0),
    remaining        integer NOT NULL CHECK (remaining >= 0),
    PRIMARY KEY (subscription_id, service_id)
);

CREATE TABLE visits (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    subscription_id  bigint NOT NULL,
    service_id       bigint NOT NULL,
    child_id         bigint REFERENCES children(id),
    specialist_id    bigint REFERENCES specialists(id),
    method           text NOT NULL CHECK (method IN ('qr','manual')),
    visited_at       timestamptz NOT NULL DEFAULT now(),
    staff_id         bigint NOT NULL REFERENCES users(id),
    cancelled_at     timestamptz,
    cancelled_by     bigint REFERENCES users(id),
    cancel_reason    text,
    FOREIGN KEY (subscription_id, service_id) REFERENCES subscription_items(subscription_id, service_id),
    CHECK ((cancelled_at IS NULL) = (cancelled_by IS NULL))
);
CREATE INDEX visits_at ON visits(visited_at);
CREATE INDEX visits_subscription ON visits(subscription_id);

CREATE TABLE qr_tokens (
    token_hash  char(64) PRIMARY KEY,
    client_id   bigint NOT NULL REFERENCES clients(id),
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL,
    used_at     timestamptz
);
CREATE INDEX qr_tokens_client ON qr_tokens(client_id);

CREATE TABLE audit_log (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at         timestamptz NOT NULL DEFAULT now(),
    actor_id   bigint REFERENCES users(id),
    action     text NOT NULL,
    entity     text NOT NULL,
    entity_id  bigint,
    details    jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX audit_log_entity ON audit_log(entity, entity_id);

CREATE FUNCTION audit_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'audit_log is append-only'; END;
$$;
CREATE TRIGGER audit_log_immutable BEFORE UPDATE OR DELETE ON audit_log
FOR EACH ROW EXECUTE FUNCTION audit_append_only();

-- Default catalogue matching the approved scope.
INSERT INTO services(code, name_ru, name_uz, description_ru, duration_min, sort) VALUES
 ('massage', 'Детский массаж', 'Bolalar massaji', 'Оздоровительный массаж для детей.', 30, 1),
 ('hydromassage', 'Гидромассаж', 'Gidromassaj', 'Гидромассажная ванна для детей.', 20, 2),
 ('pool', 'Бассейн', 'Basseyn', 'Занятие в бассейне с инструктором.', 45, 3);

INSERT INTO plans(name, validity_days) VALUES
 ('Массаж — 10 сеансов', 60), ('Гидромассаж — 10 сеансов', 60),
 ('Бассейн — 4 занятия', 30), ('Бассейн — 8 занятий', 30), ('Бассейн — 12 занятий', 45);
INSERT INTO plan_items(plan_id, service_id, visits)
SELECT p.id, s.id, v.visits FROM (VALUES
 ('Массаж — 10 сеансов','massage',10), ('Гидромассаж — 10 сеансов','hydromassage',10),
 ('Бассейн — 4 занятия','pool',4), ('Бассейн — 8 занятий','pool',8), ('Бассейн — 12 занятий','pool',12)
) AS v(plan, code, visits) JOIN plans p ON p.name = v.plan JOIN services s ON s.code = v.code;
