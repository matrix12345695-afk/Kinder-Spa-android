"""Explicit Render API adapter and read-only readiness. No migrations or bootstrap.

The public HTTPS boundary is Render's edge, which redirects HTTP and terminates
TLS before forwarding HTTP to PORT. Internal Render callers share that trusted
workspace boundary. This adapter does not infer a client IP or TLS from headers.
"""
import argparse
from dataclasses import dataclass
import json
import os
import re
import signal
import threading
from urllib.parse import urlsplit

from .api import App, BadRequest
from .telegram_runner import connection_factory, database_transport


TABLES = {
    'accounts': 'SELECT,INSERT',
    'subscriptions': 'SELECT,INSERT',
    'allowances': 'SELECT,INSERT',
    'bookings': 'SELECT,INSERT',
    'qr_tokens': 'SELECT,INSERT',
    'operations': 'SELECT,INSERT',
    'audit_events': 'SELECT,INSERT',
    'notification_outbox': 'SELECT,INSERT',
    'credentials': 'SELECT,INSERT',
    'auth_sessions': 'SELECT,INSERT',
    'login_buckets': 'SELECT,INSERT,DELETE',
}
# Required column-granular UPDATE, including specific row-lock-only identifiers.
# A whole-table UPDATE is deliberately NOT accepted for any table.
UPDATE_COLUMNS = {
    'accounts': ('id',),
    'subscriptions': ('id',),
    'allowances': ('remaining',),
    'bookings': ('state',),
    'qr_tokens': ('used_at', 'revoked'),
    'operations': ('result',),
    'credentials': ('account_id', 'salt', 'verifier', 'version'),
    'auth_sessions': ('token_hash', 'revoked'),
    'login_buckets': ('attempts',),
}
# Exact expected, normalized PostgreSQL PL/pgSQL trigger bodies. A trigger
# pointing to a function with the right name but a no-op body is NOT safe.
IMMUTABLE_FUNCTION_BODIES = {
    'immutable_audit': "BEGIN RAISE EXCEPTION 'audit is append-only'; END;",
    'immutable_identifier': "BEGIN RAISE EXCEPTION 'identity column is immutable'; END;",
}

TELEGRAM_TABLES = (
    'telegram_link_codes', 'telegram_bindings', 'telegram_updates',
    'telegram_runtime', 'telegram_actions', 'telegram_notification_batches',
    'telegram_jobs', 'telegram_qr_cleanup',
)


# Structural launch checks, never a substitute for a verified backup.
# PostgreSQL pg_trigger.tgtype: ROW=1, BEFORE=2, DELETE=8, UPDATE=16.
SAFETY_TRIGGERS = {
    'audit_events': ('audit_no_update', 'immutable_audit', 27, None),
    'notification_outbox': ('notification_outbox_no_update', 'immutable_audit', 27, None),
    'accounts': ('accounts_id_immutable', 'immutable_identifier', 19, 'id'),
    'subscriptions': ('subscriptions_id_immutable', 'immutable_identifier', 19, 'id'),
    'credentials': ('credentials_account_immutable', 'immutable_identifier', 19, 'account_id'),
    'auth_sessions': ('sessions_token_immutable', 'immutable_identifier', 19, 'token_hash'),
}
REQUIRED_INDEXES = {'qr_booking': ('qr_tokens', False),
                    'sessions_by_account': ('auth_sessions', False)}
TELEGRAM_REQUIRED_INDEXES = {
    'telegram_one_account': ('telegram_bindings', True),
    'telegram_one_peer': ('telegram_bindings', True),
    'telegram_ready': ('telegram_jobs', False),
}

# Schema integrity gates for the accounting and authentication relationships.
# Each tuple is (table, constraint, kind, columns, referenced_table,
#                referenced_columns). 'p'=PK, 'u'=UNIQUE, 'f'=FOREIGN KEY.
# Names and columns are from the reviewed first-install migrations.
SAFETY_CONSTRAINTS = (
    ('allowances', 'allowances_pkey', 'p',
     ('subscription_id', 'category'), None, ()),
    ('bookings', 'bookings_subscription_id_category_fkey', 'f',
     ('subscription_id', 'category'), 'allowances', ('subscription_id', 'category')),
    ('bookings', 'bookings_subscription_id_starts_at_key', 'u',
     ('subscription_id', 'starts_at'), None, ()),
    ('qr_tokens', 'qr_tokens_booking_id_fkey', 'f',
     ('booking_id',), 'bookings', ('id',)),
    ('audit_events', 'audit_events_actor_id_fkey', 'f',
     ('actor_id',), 'accounts', ('id',)),
    ('notification_outbox', 'notification_outbox_event_id_fkey', 'f',
     ('event_id',), 'audit_events', ('id',)),
    ('credentials', 'credentials_account_id_fkey', 'f',
     ('account_id',), 'accounts', ('id',)),
    ('auth_sessions', 'auth_sessions_account_id_fkey', 'f',
     ('account_id',), 'credentials', ('account_id',)),
)


@dataclass(frozen=True)
class Configuration:
    factory: object
    schema: str
    origin: str
    port: int
    telegram_links: bool


def configuration(environ, *, inspection=False):
    # These are accidental-deployment guards, not host attestation.
    api_service = (environ.get('RENDER_SERVICE_TYPE') == 'web'
                   and environ.get('RENDER_SERVICE_NAME') == 'kinder-spa-api')
    audit_worker = (inspection and environ.get('RENDER_SERVICE_TYPE') == 'worker'
                    and environ.get('RENDER_SERVICE_NAME') == 'kinder-spa-telegram')
    if (environ.get('RENDER') != 'true'
            or not (api_service or audit_worker)
            or not re.fullmatch(r'srv-[a-z0-9]{10,40}', environ.get('RENDER_SERVICE_ID', ''))):
        raise ValueError('dedicated_render_api_required')
    if not inspection and environ.get('KINDER_API_LIVE') != 'approved':
        raise ValueError('reviewed_api_release_required')
    origin = environ.get('RENDER_EXTERNAL_URL', '')
    hostname = environ.get('RENDER_EXTERNAL_HOSTNAME', '')
    if api_service and (not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,62}\.onrender\.com', hostname)
            or origin != 'https://' + hostname or urlsplit(origin).netloc != hostname):
        raise ValueError('canonical_render_origin_required')
    if audit_worker:
        origin = ''  # Inspection never starts a web server on the worker.
    port = environ.get('PORT', '10000')
    if not re.fullmatch(r'[1-9][0-9]{0,4}', port) or not 1024 <= int(port) <= 65535 or int(port) in (18012, 18013, 19099):
        raise ValueError('valid_render_port_required')
    flag = environ.get('KINDER_API_TELEGRAM_LINKS', 'disabled')
    if flag not in ('disabled', 'enabled'):
        raise ValueError('explicit_telegram_links_flag_required')
    schema = environ['KINDER_DATABASE_SCHEMA']
    dsn = environ.get('KINDER_INSPECTION_DATABASE_URL') if inspection else None
    factory = connection_factory(dsn or environ['KINDER_DATABASE_URL'], environ['KINDER_DATABASE_NAME'], schema,
                                 render_private=database_transport(environ))
    return Configuration(factory, schema, origin, int(port), flag == 'enabled')


def inspect_database(factory, schema, *, telegram_links=False):
    """Read metadata in a read-only transaction, without reading customer rows.

    Presence/role/privilege checks do NOT certify the complete migration schema,
    backup, constraints or production data. Those require a separate review.
    """
    if not isinstance(schema, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,50}', schema):
        raise ValueError('exact_schema_required')
    required = dict(TABLES)
    if telegram_links:
        required.update({name: 'SELECT' for name in TELEGRAM_TABLES})
        required['telegram_link_codes'] = 'SELECT,INSERT'
    with factory() as conn, conn.transaction():
        conn.execute('SET TRANSACTION READ ONLY')
        conn.execute("SET LOCAL statement_timeout TO '1500ms'")
        conn.execute("SET LOCAL lock_timeout TO '500ms'")
        major, present, unsafe = conn.execute('''SELECT current_setting('server_version_num')::int / 10000,
            EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=%s),
            r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication OR r.rolbypassrls
              OR EXISTS(SELECT 1 FROM pg_roles inherited WHERE inherited.rolname<>current_user
                  AND pg_has_role(current_user,inherited.oid,'MEMBER'))
              OR pg_has_role(current_user,d.datdba,'MEMBER')
              OR has_database_privilege(current_user,current_database(),'CREATE')
              OR EXISTS(SELECT 1 FROM pg_namespace n WHERE n.nspname=%s
                  AND (pg_has_role(current_user,n.nspowner,'MEMBER')
                       OR has_schema_privilege(current_user,n.oid,'CREATE')))
            FROM pg_roles r, pg_database d WHERE r.rolname=current_user AND d.datname=current_database()''',
            (schema, schema)).fetchone()
        missing, denied, owned = [], [], []
        for name, privileges in required.items():
            relation = conn.execute('''SELECT c.oid,c.relowner,c.relkind FROM pg_class c
                JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname=%s''',
                (schema, name)).fetchone()
            if not relation or relation[2] != 'r':
                missing.append(name)
                continue
            if conn.execute("SELECT pg_has_role(current_user,%s,'MEMBER')", (relation[1],)).fetchone()[0]:
                owned.append(name)
            for privilege in privileges.split(','):
                if not conn.execute('SELECT has_table_privilege(current_user,%s,%s)', (relation[0], privilege)).fetchone()[0]:
                    denied.append(name + ':' + privilege)
            # Scoped UPDATE can satisfy row locks without broad data mutation.
            # These explicit checks fail closed even if an operator accidentally
            # grants the API role table-wide UPDATE or more than the intended
            # column set. PostgreSQL ownership/role membership is checked above.
            if conn.execute("SELECT has_table_privilege(current_user,%s,'UPDATE')",
                            (relation[0],)).fetchone()[0]:
                denied.append(name + ':UPDATE_ALL')
            allowed_updates = set(UPDATE_COLUMNS.get(name, ()))
            if telegram_links and name == 'telegram_link_codes':
                allowed_updates.add('revoked')
            actual_updates = {row[0] for row in conn.execute(
                """SELECT a.attname FROM pg_attribute a
                   WHERE a.attrelid=%s AND a.attnum>0 AND NOT a.attisdropped
                   AND has_column_privilege(current_user,a.attrelid,a.attnum,'UPDATE')""",
                (relation[0],)).fetchall()}
            for column in sorted(allowed_updates - actual_updates):
                denied.append(name + ':UPDATE(' + column + ')')
            for column in sorted(actual_updates - allowed_updates):
                denied.append(name + ':UPDATE(' + column + '):excess')
            for privilege in ('DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'):
                if privilege == 'DELETE' and name == 'login_buckets':
                    continue
                if conn.execute('SELECT has_table_privilege(current_user,%s,%s)',
                                (relation[0], privilege)).fetchone()[0]:
                    denied.append(name + ':' + privilege + ':excess')
            if name in ('audit_events', 'notification_outbox'):
                if conn.execute("SELECT has_table_privilege(current_user,%s,'UPDATE,DELETE,TRUNCATE')",
                                (relation[0],)).fetchone()[0]:
                    denied.append(name + ':mutable')
                if conn.execute("""SELECT EXISTS (
                      SELECT 1 FROM pg_attribute a
                      WHERE a.attrelid=%s AND a.attnum>0 AND NOT a.attisdropped
                      AND has_column_privilege(current_user,a.attrelid,a.attnum,'UPDATE'))""",
                      (relation[0],)).fetchone()[0]:
                    denied.append(name + ':column_mutable')

        missing_safety = []
        if present:
            for table, (trigger, function, tgtype, column) in SAFETY_TRIGGERS.items():
                row = conn.execute("""SELECT t.tgenabled,t.tgtype,p.proname,pn.nspname,
                        coalesce((SELECT string_agg(a.attname, ',' ORDER BY a.attname)
                            FROM pg_attribute a WHERE a.attrelid=c.oid
                            AND a.attnum=ANY(t.tgattr::int2[])), ''),
                        p.prosrc,l.lanname,p.prosecdef,p.prokind,p.pronargs,
                        p.prorettype='pg_catalog.trigger'::regtype
                    FROM pg_trigger t
                    JOIN pg_class c ON c.oid=t.tgrelid
                    JOIN pg_namespace n ON n.oid=c.relnamespace
                    JOIN pg_proc p ON p.oid=t.tgfoid
                    JOIN pg_namespace pn ON pn.oid=p.pronamespace
                    JOIN pg_language l ON l.oid=p.prolang
                    WHERE n.nspname=%s AND c.relname=%s AND t.tgname=%s
                    AND NOT t.tgisinternal""", (schema, table, trigger)).fetchone()
                body = re.sub(r'\s+', ' ', row[5]).strip() if row else ''
                if (row is None or row[0] not in ('O','A')
                        or row[1] != tgtype or row[2] != function or row[3] != schema
                        or row[4] != (column or '')
                        or body != IMMUTABLE_FUNCTION_BODIES[function]
                        or row[6] != 'plpgsql' or row[7] or row[8] != 'f'
                        or row[9] != 0 or not row[10]):
                    missing_safety.append(table + ':' + trigger)
            for table, name, kind, columns, target_table, target_columns in SAFETY_CONSTRAINTS:
                info = conn.execute("""SELECT co.contype,co.convalidated,co.condeferrable,
                        co.condeferred,co.confupdtype,co.confdeltype,
                        (SELECT array_agg(a.attname ORDER BY k.ordinality)
                         FROM unnest(co.conkey) WITH ORDINALITY AS k(num,ordinality)
                         JOIN pg_attribute a ON a.attrelid=co.conrelid AND a.attnum=k.num),
                        rn.nspname, rt.relname,
                        (SELECT array_agg(a.attname ORDER BY k.ordinality)
                         FROM unnest(co.confkey) WITH ORDINALITY AS k(num,ordinality)
                         JOIN pg_attribute a ON a.attrelid=co.confrelid AND a.attnum=k.num)
                    FROM pg_constraint co
                    JOIN pg_class t ON t.oid=co.conrelid
                    JOIN pg_namespace n ON n.oid=t.relnamespace
                    LEFT JOIN pg_class rt ON rt.oid=co.confrelid
                    LEFT JOIN pg_namespace rn ON rn.oid=rt.relnamespace
                    WHERE n.nspname=%s AND t.relname=%s AND co.conname=%s""",
                    (schema, table, name)).fetchone()
                if (not info or info[0] != kind or not info[1] or info[2] or info[3]
                        or tuple(info[6] or ()) != columns
                        or (kind == 'f' and (
                            info[4:6] != ('a', 'a') or
                            info[7:9] != (schema, target_table) or
                            tuple(info[9] or ()) != target_columns))):
                    missing_safety.append(table + ':' + name)
            indexes = REQUIRED_INDEXES | (TELEGRAM_REQUIRED_INDEXES if telegram_links else {})
            for index, (table, unique) in indexes.items():
                row = conn.execute("""SELECT i.indisvalid,i.indisready,i.indisunique
                    FROM pg_index i
                    JOIN pg_class idx ON idx.oid=i.indexrelid
                    JOIN pg_namespace idxn ON idxn.oid=idx.relnamespace
                    JOIN pg_class t ON t.oid=i.indrelid
                    JOIN pg_namespace tn ON tn.oid=t.relnamespace
                    WHERE idxn.nspname=%s AND tn.nspname=%s
                    AND idx.relname=%s AND t.relname=%s""",
                    (schema, schema, index, table)).fetchone()
                if not row or not row[0] or not row[1] or bool(row[2]) != unique:
                    missing_safety.append(table + ':' + index)
        schema_usage = present and conn.execute('SELECT has_schema_privilege(current_user,%s,\'USAGE\')', (schema,)).fetchone()[0]
        result = {'postgres_major': major, 'schema_present': present,
                  'schema_usage': bool(schema_usage), 'runtime_role_safe': not unsafe and not owned,
                  'missing_tables': missing, 'missing_safety_objects': missing_safety,
                  'insufficient_privileges': denied,
                  'metadata_only': True, 'read_only': True, 'tls_in_use': bool(conn.pgconn.ssl_in_use)}
        result['ready'] = bool(major == 18 and present and schema_usage and not unsafe
                               and not owned and not missing and not missing_safety and not denied)
        return result


class RenderApp(App):
    def __init__(self, settings):
        super().__init__(settings.factory, browser_origin=settings.origin, telegram_enabled=settings.telegram_links)
        self.settings = settings

    def __call__(self, environ, start_response):
        trusted = environ.copy()
        # Render publicly terminates TLS; private callers belong to the trusted
        # workspace. Do not accept forwarding claims as scheme/IP/host inputs.
        trusted['wsgi.url_scheme'] = 'https'
        for key in list(trusted):
            if key == 'HTTP_FORWARDED' or key.startswith('HTTP_X_FORWARDED_'):
                trusted.pop(key)
        return super().__call__(trusted, start_response)

    def dispatch(self, environ):
        if environ.get('REQUEST_METHOD') == 'GET' and environ.get('PATH_INFO') == '/health':
            if (environ.get('QUERY_STRING') or environ.get('CONTENT_LENGTH', '') not in ('', '0')
                    or environ.get('HTTP_TRANSFER_ENCODING')):
                raise BadRequest()
            try:
                report = inspect_database(self.factory, self.settings.schema, telegram_links=self.telegram_enabled)
            except Exception:
                return 503, {'error': 'not_ready'}
            return (200, {'ok': True}) if report['ready'] else (503, {'error': 'not_ready'})
        return super().dispatch(environ)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Render-only Kinder HTTPS-edge API; no automatic migrations')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--run', action='store_true')
    mode.add_argument('--inspect', action='store_true')
    mode.add_argument('--inspect-wait', action='store_true')
    args = parser.parse_args(argv)
    try:
        settings = configuration(os.environ, inspection=args.inspect or args.inspect_wait)
        report = inspect_database(settings.factory, settings.schema, telegram_links=settings.telegram_links)
        if args.inspect or args.inspect_wait:
            print(json.dumps(report, sort_keys=True), flush=True)
            if args.inspect_wait:
                # Keeps only the dedicated paid Render worker available for
                # internal preflight/Shell. No HTTP, Telegram, model or DB writes.
                if os.environ.get('RENDER_SERVICE_TYPE') != 'worker':
                    raise ValueError('inspection_standby_requires_worker')
                print('kinder_worker_mode=inspection; telegram_polling=disabled', flush=True)
                stop = threading.Event()
                for signum in (signal.SIGTERM, signal.SIGINT):
                    signal.signal(signum, lambda *_: stop.set())
                stop.wait()
                return 0
            return 0 if report['ready'] else 1
        if not report['ready']:
            print('kinder_api_start=refused; database preflight not ready')
            return 2
        from .gateway import Server
        Server(RenderApp(settings), settings.port).run()
        return 0
    except Exception:
        # No traceback, DSN, exception text or credentials.
        print('kinder_api_start=refused; review dedicated Render configuration privately')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
