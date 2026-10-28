"""Explicitly enabled standalone Kinder polling worker; no schema/token discovery."""
import argparse
import os
from pathlib import Path
import re
import signal
import stat
import threading

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from .telegram_bot import Bot
from .telegram_delivery import TelegramAPI,TelegramFailure,Sender,poll_once


def token_file(path):
    candidate=Path(path)
    if not candidate.is_absolute() or any('inventory' in p.lower() or 'ultimate' in p.lower() for p in candidate.parts):
        raise ValueError('dedicated_kinder_token_file_required')
    resolved=candidate.resolve(strict=True)
    if resolved!=candidate or any('inventory' in p.lower() or 'ultimate' in p.lower() for p in resolved.parts):
        raise ValueError('dedicated_kinder_token_file_required')
    descriptor=os.open(candidate,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_size>1024 or info.st_nlink!=1:
            raise ValueError('private_token_file_required')
        return os.read(descriptor,1025).decode('ascii').strip()
    finally:os.close(descriptor)


def connection_factory(dsn, database, schema):
    parsed=conninfo_to_dict(dsn)
    if (not re.fullmatch(r'kinder_[a-z0-9_]{1,40}',database) or database=='kinder_test' or parsed.get('dbname')!=database
            or any(k in parsed for k in ('service','hostaddr','options')) or not re.fullmatch(r'[a-z][a-z0-9_]{0,50}',schema)):
        raise ValueError('dedicated_reviewed_kinder_database_required')
    if parsed.get('host') not in ('127.0.0.1','localhost') and not parsed.get('host','').startswith('/') and parsed.get('sslmode')!='verify-full':
        raise ValueError('verified_database_tls_required')
    def factory():
        conn=psycopg.connect(dsn,autocommit=True,connect_timeout=5)
        try:
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
    parser=argparse.ArgumentParser(description='Dedicated Kinder Telegram worker; no auto install or migrations')
    parser.add_argument('--run',action='store_true');parser.add_argument('--once',action='store_true')
    args=parser.parse_args(argv)
    if not (args.run or args.once) or os.environ.get('KINDER_TELEGRAM_LIVE')!='approved':
        print('kinder_telegram=disabled; explicit reviewed configuration and release approval required')
        return 2
    try:
        expected=int(os.environ['KINDER_TELEGRAM_BOT_ID'])
        factory=connection_factory(os.environ['KINDER_DATABASE_URL'],os.environ['KINDER_DATABASE_NAME'],os.environ['KINDER_DATABASE_SCHEMA'])
        # Existing Inventory/ULTIMATE token paths are denied BEFORE any file read.
        api=TelegramAPI(token_file(os.environ['KINDER_TELEGRAM_TOKEN_FILE']))
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
