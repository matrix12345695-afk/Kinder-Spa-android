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
from urllib.parse import urlsplit

from .api import App, BadRequest
from .telegram_runner import connection_factory, database_transport


TABLES = {
    'accounts': 'SELECT,INSERT,UPDATE',
    'subscriptions': 'SELECT,INSERT',
    'allowances': 'SELECT,INSERT,UPDATE',
    'bookings': 'SELECT,INSERT,UPDATE',
    'qr_tokens': 'SELECT,INSERT,UPDATE',
    'operations': 'SELECT,INSERT,UPDATE',
    'audit_events': 'SELECT,INSERT',
    'notification_outbox': 'SELECT,INSERT',
    'credentials': 'SELECT,INSERT,UPDATE',
    'auth_sessions': 'SELECT,INSERT,UPDATE',
    'login_buckets': 'SELECT,INSERT,UPDATE,DELETE',
}
TELEGRAM_TABLES = (
    'telegram_link_codes', 'telegram_bindings', 'telegram_updates',
    'telegram_runtime', 'telegram_actions', 'telegram_notification_batches',
    'telegram_jobs', 'telegram_qr_cleanup',
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
    factory = connection_factory(environ['KINDER_DATABASE_URL'], environ['KINDER_DATABASE_NAME'], schema,
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
        required['telegram_link_codes'] = 'SELECT,INSERT,UPDATE'
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
            if name == 'audit_events' and conn.execute(
                    "SELECT has_table_privilege(current_user,%s,'UPDATE,DELETE,TRUNCATE')", (relation[0],)).fetchone()[0]:
                denied.append('audit_events:mutable')
        schema_usage = present and conn.execute('SELECT has_schema_privilege(current_user,%s,\'USAGE\')', (schema,)).fetchone()[0]
        result = {'postgres_major': major, 'schema_present': present,
                  'schema_usage': bool(schema_usage), 'runtime_role_safe': not unsafe and not owned,
                  'missing_tables': missing, 'insufficient_privileges': denied,
                  'metadata_only': True, 'read_only': True}
        result['ready'] = bool(major == 18 and present and schema_usage and not unsafe and not owned and not missing and not denied)
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
    args = parser.parse_args(argv)
    try:
        settings = configuration(os.environ, inspection=args.inspect)
        report = inspect_database(settings.factory, settings.schema, telegram_links=settings.telegram_links)
        if args.inspect:
            print(json.dumps(report, sort_keys=True))
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
