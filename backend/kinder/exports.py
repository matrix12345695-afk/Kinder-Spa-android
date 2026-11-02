"""CSV exports for accounting (Excel-friendly) and a full JSON backup. Imported by kinder.app."""
import base64
import csv
import io
import json
from datetime import date, datetime
from decimal import Decimal

from starlette.responses import Response

from .app import PAYMENT_METHODS, ZONE, ApiError, api, day, now, today


def excel_number(v):
    if isinstance(v, Decimal):
        return str(int(v)) if v == v.to_integral() else format(v, 'f').replace('.', ',')
    return v


def cell(v):
    if v is None:
        return ''
    if isinstance(v, datetime):
        return v.astimezone(ZONE).strftime('%d.%m.%Y %H:%M')
    if isinstance(v, date):
        return v.strftime('%d.%m.%Y')
    if isinstance(v, bool):
        return 'да' if v else 'нет'
    if isinstance(v, Decimal):
        return excel_number(v)
    s = str(v)
    return "'" + s if s[:1] in ('=', '+', '-', '@') and not s.lstrip('+-').replace(' ', '').isdigit() else s  # no formula injection


def csv_response(x, name, header, rows):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=';', lineterminator='\r\n')
    w.writerow(header)
    for r in rows:
        w.writerow([cell(v) for v in r])
    x.audit('export', 'report', None, report=name, rows=len(rows))
    filename = f"kinder-{name}-{today().isoformat()}.csv"
    return Response(('﻿' + buf.getvalue()).encode('utf-8'), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"', 'Cache-Control': 'no-store'})


def period(x):
    start = day(x.query.get('from'), 'from') or today().replace(day=1)
    end = day(x.query.get('to'), 'to') or today()
    if end < start or (end - start).days > 366:
        raise ApiError(400, 'invalid_period')
    return start, end


@api('/export/payments.csv')
def export_payments(x):
    start, end = period(x)
    rows = x.all('''SELECT p.id, p.paid_at, c.full_name, c.phone, s.name, p.amount, p.method, p.note, st.full_name AS staff,
            p.voided_at, p.void_reason
        FROM payments p JOIN subscriptions s ON s.id=p.subscription_id JOIN clients c ON c.id=s.client_id JOIN users st ON st.id=p.staff_id
        WHERE (p.paid_at AT TIME ZONE 'Asia/Tashkent')::date BETWEEN %s AND %s ORDER BY p.paid_at''', (start, end))
    return csv_response(x, f'oplaty-{start}-{end}', ['№', 'Дата', 'Клиент', 'Телефон', 'Абонемент', 'Сумма', 'Способ', 'Комментарий',
                                                     'Принял', 'Отменена', 'Причина отмены'],
                        [(r['id'], r['paid_at'], r['full_name'], r['phone'], r['name'], r['amount'], PAYMENT_METHODS[r['method']],
                          r['note'], r['staff'], r['voided_at'], r['void_reason']) for r in rows])


@api('/export/visits.csv')
def export_visits(x):
    start, end = period(x)
    labels = {'qr': 'QR', 'manual': 'вручную', 'late_cancel': 'поздняя отмена', 'no_show': 'неявка'}
    rows = x.all('''SELECT v.id, v.visited_at, c.full_name, ch.full_name AS child, sv.name_ru AS service, s.name AS subscription,
            sp.full_name AS specialist, v.method, st.full_name AS staff, v.cancelled_at, v.cancel_reason
        FROM visits v JOIN subscriptions s ON s.id=v.subscription_id JOIN clients c ON c.id=s.client_id
        JOIN services sv ON sv.id=v.service_id LEFT JOIN children ch ON ch.id=v.child_id
        LEFT JOIN specialists sp ON sp.id=v.specialist_id JOIN users st ON st.id=v.staff_id
        WHERE (v.visited_at AT TIME ZONE 'Asia/Tashkent')::date BETWEEN %s AND %s ORDER BY v.visited_at''', (start, end))
    return csv_response(x, f'poseshcheniya-{start}-{end}', ['№', 'Дата', 'Клиент', 'Ребёнок', 'Услуга', 'Абонемент', 'Специалист',
                                                           'Способ', 'Отметил', 'Отменено', 'Причина отмены'],
                        [(r['id'], r['visited_at'], r['full_name'], r['child'], r['service'], r['subscription'], r['specialist'],
                          labels.get(r['method'], r['method']), r['staff'], r['cancelled_at'], r['cancel_reason']) for r in rows])


@api('/export/debts.csv')
def export_debts(x):
    rows = x.all('''SELECT s.id, c.full_name, c.phone, s.name, s.created_at, s.starts_on, s.ends_on, s.price,
            coalesce((SELECT sum(p.amount) FROM payments p WHERE p.subscription_id=s.id AND p.voided_at IS NULL), 0) AS paid
        FROM subscriptions s JOIN clients c ON c.id=s.client_id WHERE s.status <> 'closed' ORDER BY c.full_name, s.id''')
    rows = [r for r in rows if r['price'] > r['paid']]
    return csv_response(x, 'dolgi', ['№ абонемента', 'Клиент', 'Телефон', 'Абонемент', 'Оформлен', 'Начало', 'Окончание',
                                     'Цена', 'Оплачено', 'Долг'],
                        [(r['id'], r['full_name'], r['phone'], r['name'], r['created_at'], r['starts_on'], r['ends_on'],
                          r['price'], r['paid'], r['price'] - r['paid']) for r in rows])


@api('/export/clients.csv')
def export_clients(x):
    rows = x.all('''SELECT c.id, c.full_name, c.phone, c.note, c.archived, c.created_at,
            (SELECT string_agg(ch.full_name || coalesce(' (' || to_char(ch.birth_date, 'DD.MM.YYYY') || ')', ''), ', ' ORDER BY ch.id)
               FROM children ch WHERE ch.client_id=c.id AND NOT ch.archived) AS children,
            (SELECT count(*) FROM subscriptions s WHERE s.client_id=c.id AND s.status='active' AND s.ends_on >= %s) AS active_subs,
            u.login, EXISTS (SELECT 1 FROM telegram_chats tc WHERE tc.user_id=c.user_id AND tc.cred_version=u.cred_version) AS telegram
        FROM clients c LEFT JOIN users u ON u.id=c.user_id ORDER BY c.full_name''', (today(),))
    return csv_response(x, 'klienty', ['№', 'Родитель', 'Телефон', 'Дети', 'Активных абонементов', 'Логин', 'Telegram', 'Заметка',
                                       'Архив', 'Создан'],
                        [(r['id'], r['full_name'], r['phone'], r['children'], r['active_subs'], r['login'], r['telegram'],
                          r['note'], r['archived'], r['created_at']) for r in rows])


BACKUP_TABLES = {
    'users': 'id, role, login, full_name, enabled, created_at',      # no password hashes
    'clients': '*', 'children': '*', 'services': '*', 'specialists': '*', 'specialist_services': '*',
    'plans': '*', 'plan_items': '*', 'subscriptions': '*', 'subscription_items': '*', 'payments': '*',
    'visits': '*', 'slots': '*', 'bookings': '*', 'audit_log': '*', 'service_photos': 'id, service_id, content_type, data, created_at',
}


def _json(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return format(v, 'f')
    if isinstance(v, (bytes, memoryview)):
        return base64.b64encode(bytes(v)).decode()
    raise TypeError(type(v).__name__)


@api('/export/backup.json', roles=('superadmin',))
def export_backup(x):
    data = {'format': 'kinder-spa-backup-v1', 'created_at': now(),
            'schema_version': x.one('SELECT max(version) AS v FROM schema_version')['v'], 'tables': {}}
    with x.c.transaction():
        x.c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        for table, cols in BACKUP_TABLES.items():
            data['tables'][table] = x.all(f'SELECT {cols} FROM {table} ORDER BY 1')
    counts = {k: len(v) for k, v in data['tables'].items()}
    x.audit('export_backup', 'system', None, rows=counts)
    body = json.dumps(data, default=_json, ensure_ascii=False).encode('utf-8')
    return Response(body, media_type='application/json', headers={
        'Content-Disposition': f'attachment; filename="kinder-backup-{now().astimezone(ZONE).strftime("%Y-%m-%d-%H%M")}.json"',
        'Cache-Control': 'no-store'})
