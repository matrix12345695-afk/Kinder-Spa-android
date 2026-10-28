"""Explicitly enabled Render-only Kinder worker; no files or schema discovery."""
import argparse
import os
import re
import signal
import threading

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from .telegram_bot import Bot
from .telegram_delivery import TelegramAPI,TelegramFailure,Sender,poll_once


RENDER_DATABASE_HOST='dpg-dbbtkol9fdbs73a7tvqg-a'


def database_transport(environ):
    value=environ.get('KINDER_DATABASE_TRANSPORT','verified-tls')
    if value not in ('verified-tls','render-private-tls'):
        raise ValueError('explicit_database_transport_required')
    return value=='render-private-tls'


def render_configuration(environ):
    """Fail before token access off the approved Render worker.

    Render's documented markers prevent accidental launches under the old VPS
    instructions; they are deployment checks, not cryptographic attestation.
    There is deliberately no fallback to files, BOT_TOKEN, ULTIMATE or Inventory.
    """
    if (environ.get('RENDER')!='true' or environ.get('RENDER_SERVICE_TYPE')!='worker'
            or environ.get('RENDER_SERVICE_NAME')!='kinder-spa-telegram'
            or not re.fullmatch(r'srv-[a-z0-9]{10,40}',environ.get('RENDER_SERVICE_ID',''))
            or environ.get('KINDER_TELEGRAM_LIVE')!='approved'):
        raise ValueError('approved_render_worker_required')
    expected=environ.get('KINDER_TELEGRAM_BOT_ID','')
    if not re.fullmatch(r'[1-9][0-9]{4,18}',expected) or int(expected)>=2**63:
        raise ValueError('exact_bot_identity_required')
    # Validate the dedicated database before retrieving any bot credential.
    factory=connection_factory(environ['KINDER_DATABASE_URL'],environ['KINDER_DATABASE_NAME'],environ['KINDER_DATABASE_SCHEMA'],
                               render_private=database_transport(environ))
    token=environ['KINDER_TELEGRAM_BOT_TOKEN']
    if (not isinstance(token,str) or not re.fullmatch(r'[1-9][0-9]{4,19}:[A-Za-z0-9_-]{30,100}',token)
            or token.split(':',1)[0]!=expected):
        raise ValueError('dedicated_bot_token_required')
    return factory,int(expected),token


def connection_factory(dsn, database, schema, *, render_private=False):
    parsed=conninfo_to_dict(dsn)
    if (not re.fullmatch(r'kinder_[a-z0-9_]{1,40}',database) or database=='kinder_test' or parsed.get('dbname')!=database
            or any(k in parsed for k in ('service','hostaddr','options')) or not re.fullmatch(r'[a-z][a-z0-9_]{0,50}',schema)):
        raise ValueError('dedicated_reviewed_kinder_database_required')
    if type(render_private) is not bool:raise ValueError('explicit_database_transport_required')
    if render_private:
        # Explicit Render-private scope only. Render documents self-signed
        # internal TLS without verify-full support; trust the private network,
        # not an authenticated certificate name. Never generalize this scope.
        if database!='kinder_spa_db' or parsed.get('host')!=RENDER_DATABASE_HOST or parsed.get('sslmode')!='require':
            raise ValueError('pinned_render_private_database_tls_required')
    elif parsed.get('host') not in ('127.0.0.1','localhost') and not parsed.get('host','').startswith('/') and parsed.get('sslmode')!='verify-full':
        raise ValueError('verified_database_tls_required')
    def factory():
        options={'ssl_min_protocol_version':'TLSv1.2','gssencmode':'disable'} if render_private else {}
        conn=psycopg.connect(dsn,autocommit=True,connect_timeout=3,**options)
        try:
            if render_private and not conn.pgconn.ssl_in_use:
                raise ValueError('database_tls_not_negotiated')
            conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
            role=conn.execute('SELECT rolsuper FROM pg_roles WHERE rolname=current_user').fetchone()
            if not role or role[0]:raise ValueError('non_superuser_runtime_role_required')
            return conn
        except Exception:conn.close();raise
    return factory


def verify_identity(api,expected):
    identity=api.call('getMe',{})
    if not isinstance(identity,dict) or identity.get('id')!=expected or identity.get('is_bot') is not True:
        raise ValueError('unexpected_bot_identity')
    if not isinstance(identity.get('username'),str):raise ValueError('bot_username_required')
    webhook=api.call('getWebhookInfo',{})
    if not isinstance(webhook,dict) or webhook.get('url')!='':
        raise ValueError('existing_webhook_not_changed')
    return identity['username']


def main(argv=None):
    parser=argparse.ArgumentParser(description='Render-only Kinder Telegram worker; no auto install or migrations')
    parser.add_argument('--run',action='store_true');parser.add_argument('--once',action='store_true')
    args=parser.parse_args(argv)
    if not (args.run or args.once) or os.environ.get('KINDER_TELEGRAM_LIVE')!='approved':
        print('kinder_telegram=disabled; explicit reviewed configuration and release approval required')
        return 2
    try:
        factory,expected,token=render_configuration(os.environ)
        api=TelegramAPI(token)
        username=verify_identity(api,expected)
        bot=Bot(factory,qr_reader=api.read_photo_qr)
        with factory() as singleton:
            if not singleton.execute('SELECT pg_try_advisory_lock(74192369,%s)',(expected%2147483647,)).fetchone()[0]:
                raise ValueError('another_kinder_poller_active')
            bot.configure(expected,username)
            sender=Sender(bot,api);stop=threading.Event()
            for signum in (signal.SIGTERM,signal.SIGINT):signal.signal(signum,lambda *_:stop.set())
            while not stop.is_set():
                try:poll_once(bot,api,sender)
                except TelegramFailure as error:
                    print('kinder_telegram_api=unconfirmed',flush=True)
                    if error.code in (401,409):return 2
                    if args.once:return 1
                    stop.wait(max(5,error.retry_after))
                except Exception:
                    # No traceback, provider description, request URL, DSN or token.
                    print('kinder_telegram_cycle=unconfirmed',flush=True)
                    if args.once:return 1
                    stop.wait(5)
                if args.once:break
        return 0
    except Exception:
        print('kinder_telegram_start=refused; check dedicated configuration privately',flush=True)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
