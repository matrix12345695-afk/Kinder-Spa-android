"""Schedule (slots) and bookings. Imported at the end of kinder.app to register routes."""
from datetime import date, datetime, time, timedelta

from . import telegram as tgbot
from .app import (STAFF, ZONE, ApiError, api, boolean, day, found, ident, integer, lock_subscription, now,
                  reason, redeem, text, today)

CLIENT = ('client',)
WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']


def local(dt):
    return dt.astimezone(ZONE)


def when(dt):
    v = local(dt)
    return f"{WEEKDAYS[v.weekday()]} {v.strftime('%d.%m')} в {v.strftime('%H:%M')}"


def late_cutoff(starts_at):
    """Free cancellation ends at 19:00 (Tashkent) the day before the session."""
    d = local(starts_at).date() - timedelta(days=1)
    return datetime.combine(d, time(19, 0), ZONE)


def parse_hhmm(value, key='time'):
    try:
        h, m = str(value).split(':')
        return time(int(h), int(m))
    except (ValueError, TypeError):
        raise ApiError(400, 'invalid_field', key)


# ------------------------------------------------------------------ queries

SLOT_COLS = '''sl.id, sl.service_id, sv.name_ru AS service_name, sv.code AS service_code, sl.specialist_id,
    sp.full_name AS specialist_name, sl.starts_at, sl.ends_at, sl.capacity, sl.note, sl.cancelled_at, sl.cancel_reason,
    (SELECT count(*) FROM bookings b WHERE b.slot_id = sl.id AND b.status IN ('booked','attended')) AS booked'''
SLOT_FROM = 'slots sl JOIN services sv ON sv.id = sl.service_id LEFT JOIN specialists sp ON sp.id = sl.specialist_id'


def bookings_query(x, where, args):
    return x.all(f'''SELECT b.id, b.slot_id, b.subscription_id, s.name AS subscription_name, b.client_id, c.full_name AS client_name,
            c.phone AS client_phone, b.child_id, ch.full_name AS child_name, b.status, b.created_at, b.cancelled_at,
            b.cancel_reason, b.forfeited, b.visit_id, sl.starts_at, sl.ends_at, sv.name_ru AS service_name, sl.service_id,
            sp.full_name AS specialist_name
        FROM bookings b JOIN slots sl ON sl.id = b.slot_id JOIN services sv ON sv.id = sl.service_id
        LEFT JOIN specialists sp ON sp.id = sl.specialist_id JOIN subscriptions s ON s.id = b.subscription_id
        JOIN clients c ON c.id = b.client_id LEFT JOIN children ch ON ch.id = b.child_id
        WHERE {where} ORDER BY sl.starts_at, b.id''', args)


@api('/slots')
def slots_list(x):
    start = day(x.query.get('from'), 'from') or today()
    end = day(x.query.get('to'), 'to') or start
    if end < start or (end - start).days > 62:
        raise ApiError(400, 'invalid_period')
    args = [start, end]
    where = "(sl.starts_at AT TIME ZONE 'Asia/Tashkent')::date BETWEEN %s AND %s"
    if x.query.get('service_id'):
        where += ' AND sl.service_id = %s'
        args.append(ident(x.query.get('service_id'), 'service_id'))
    if x.query.get('cancelled') != '1':
        where += ' AND sl.cancelled_at IS NULL'
    slots = x.all(f'SELECT {SLOT_COLS} FROM {SLOT_FROM} WHERE {where} ORDER BY sl.starts_at, sv.sort, sl.id', args)
    if slots:
        books = bookings_query(x, 'b.slot_id = ANY(%s)', ([s['id'] for s in slots],))
        for s in slots:
            s['bookings'] = [b for b in books if b['slot_id'] == s['id']]
    return slots


def slot_insert(x, service_id, specialist_id, starts_at, minutes, capacity, note=''):
    row = x.one(f'''INSERT INTO slots(service_id, specialist_id, starts_at, ends_at, capacity, note, created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (service_id, coalesce(specialist_id, 0), starts_at) WHERE cancelled_at IS NULL DO NOTHING RETURNING id''',
                (service_id, specialist_id, starts_at, starts_at + timedelta(minutes=minutes), capacity, note, x.user['id']))
    return row['id'] if row else None


def slot_params(x):
    service = found(x.one('SELECT id, duration_min FROM services WHERE id=%s', (ident(x.body.get('service_id'), 'service_id'),)),
                    'service_not_found')
    specialist_id = ident(x.body.get('specialist_id'), 'specialist_id', required=False)
    if specialist_id and not x.one('SELECT 1 FROM specialists WHERE id=%s AND active', (specialist_id,)):
        raise ApiError(400, 'specialist_not_found')
    minutes = integer(x.body.get('duration_min') or service['duration_min'], 'duration_min', lo=5, hi=240)
    capacity = integer(x.body.get('capacity') or 1, 'capacity', lo=1, hi=100)
    return service['id'], specialist_id, minutes, capacity


@api('/slots', ('POST',))
def slot_create(x):
    service_id, specialist_id, minutes, capacity = slot_params(x)
    starts = datetime.combine(day(x.body.get('date'), 'date', required=True), parse_hhmm(x.body.get('time')), ZONE)
    with x.c.transaction():
        sid = slot_insert(x, service_id, specialist_id, starts, minutes, capacity, text(x.body, 'note', max_len=300))
        if not sid:
            raise ApiError(409, 'slot_exists')
        x.audit('create_slot', 'slot', sid, starts_at=starts, capacity=capacity)
    return {'id': sid}


@api('/slots/generate', ('POST',))
def slots_generate(x):
    service_id, specialist_id, minutes, capacity = slot_params(x)
    start = day(x.body.get('from'), 'from', required=True)
    end = day(x.body.get('to'), 'to', required=True)
    if end < start or (end - start).days > 92:
        raise ApiError(400, 'invalid_period')
    weekdays = x.body.get('weekdays') or []
    times = x.body.get('times') or []
    if not isinstance(weekdays, list) or not weekdays or any(type(w) is not int or not 0 <= w <= 6 for w in weekdays):
        raise ApiError(400, 'invalid_field', 'weekdays')
    if not isinstance(times, list) or not 1 <= len(times) <= 30:
        raise ApiError(400, 'invalid_field', 'times')
    hhmm = sorted({parse_hhmm(t) for t in times})
    created = skipped = 0
    with x.c.transaction():
        d = start
        while d <= end:
            if d.weekday() in weekdays:
                for t in hhmm:
                    starts = datetime.combine(d, t, ZONE)
                    if starts <= now():
                        continue
                    if slot_insert(x, service_id, specialist_id, starts, minutes, capacity):
                        created += 1
                    else:
                        skipped += 1
            d += timedelta(days=1)
        x.audit('generate_slots', 'service', service_id, created=created, skipped=skipped,
                period=f'{start}..{end}', weekdays=weekdays, times=[t.strftime('%H:%M') for t in hhmm], capacity=capacity)
    return {'created': created, 'skipped': skipped}


@api('/slots/{id}', ('PATCH',))
def slot_update(x):
    sid = ident(x.params['id'])
    with x.c.transaction():
        sl = found(x.one('SELECT * FROM slots WHERE id=%s AND cancelled_at IS NULL FOR UPDATE', (sid,)))
        capacity = integer(x.body.get('capacity'), 'capacity', lo=1, hi=100) if 'capacity' in x.body else sl['capacity']
        booked = x.one("SELECT count(*) AS n FROM bookings WHERE slot_id=%s AND status IN ('booked','attended')", (sid,))['n']
        if capacity < booked:
            raise ApiError(409, 'capacity_below_bookings')
        note = text(x.body, 'note', max_len=300) if 'note' in x.body else sl['note']
        x.c.execute('UPDATE slots SET capacity=%s, note=%s WHERE id=%s', (capacity, note, sid))
        x.audit('update_slot', 'slot', sid, capacity=capacity)
    return {'ok': True}


@api('/slots/{id}/cancel', ('POST',))
def slot_cancel(x):
    why = reason(x.body)
    sid = ident(x.params['id'])
    with x.c.transaction():
        sl = found(x.one(f'SELECT {SLOT_COLS} FROM {SLOT_FROM} WHERE sl.id=%s AND sl.cancelled_at IS NULL FOR UPDATE OF sl', (sid,)))
        x.c.execute('UPDATE slots SET cancelled_at=%s, cancel_reason=%s WHERE id=%s', (now(), why, sid))
        rows = x.all("""UPDATE bookings SET status='cancelled', cancelled_at=%s, cancelled_by=%s, cancel_reason=%s
            WHERE slot_id=%s AND status='booked' RETURNING client_id""", (now(), x.user['id'], 'Занятие отменено центром: ' + why, sid))
        for r in rows:
            x.notify_client(r['client_id'], f"❗ Занятие <b>{tgbot.e(sl['service_name'])}</b> {when(sl['starts_at'])} отменено центром.\n"
                            f"Причина: {tgbot.e(why)}. Посещение не списано — запишитесь на другое время.")
        x.audit('cancel_slot', 'slot', sid, reason=why, bookings_cancelled=len(rows))
    return {'ok': True, 'bookings_cancelled': len(rows)}


# ------------------------------------------------------------------ booking core

def reserved(x, subscription_id, service_id, exclude_slot=None):
    """Future bookings that will consume visits of this subscription/service."""
    return x.one('''SELECT count(*) AS n FROM bookings b JOIN slots sl ON sl.id = b.slot_id
        WHERE b.subscription_id=%s AND sl.service_id=%s AND b.status='booked' AND sl.cancelled_at IS NULL
          AND (%s::bigint IS NULL OR sl.id <> %s::bigint)''', (subscription_id, service_id, exclude_slot, exclude_slot))['n']


def pick_subscription(x, client_id, service_id, slot_day, child_id, explicit=None):
    """Active subscription of the client that can pay for this session; explicit id wins."""
    rows = x.all('''SELECT s.id FROM subscriptions s JOIN subscription_items si ON si.subscription_id = s.id
        WHERE s.client_id=%s AND si.service_id=%s AND s.status='active' AND s.starts_on <= %s AND s.ends_on >= %s
          AND si.remaining > 0 AND (s.child_id IS NULL OR %s::bigint IS NULL OR s.child_id = %s::bigint)
        ORDER BY (s.child_id IS NULL), s.ends_on, s.id''', (client_id, service_id, slot_day, slot_day, child_id, child_id))
    ids = [r['id'] for r in rows]
    if explicit:
        if explicit not in ids:
            raise ApiError(409, 'subscription_not_usable')
        return explicit
    for sid in ids:
        left = x.one('SELECT remaining FROM subscription_items WHERE subscription_id=%s AND service_id=%s', (sid, service_id))['remaining']
        if left - reserved(x, sid, service_id) > 0:
            return sid
    raise ApiError(409, 'no_subscription_for_booking' if not ids else 'all_visits_reserved')


def create_booking(x, slot_id, client_id, child_id, subscription_id=None, by_staff=False):
    """Caller holds a transaction. Locks slot -> subscription; returns booking id."""
    sl = found(x.one(f'SELECT {SLOT_COLS} FROM {SLOT_FROM} WHERE sl.id=%s FOR UPDATE OF sl', (ident(slot_id, 'slot_id'),)), 'slot_not_found')
    if sl['cancelled_at']:
        raise ApiError(409, 'slot_cancelled')
    if sl['starts_at'] <= now():
        raise ApiError(409, 'slot_in_past')
    if sl['booked'] >= sl['capacity']:
        raise ApiError(409, 'slot_full')
    client = found(x.one('SELECT id, archived FROM clients WHERE id=%s', (client_id,)), 'client_not_found')
    if client['archived']:
        raise ApiError(400, 'client_archived')
    kids = x.all('SELECT id FROM children WHERE client_id=%s AND NOT archived ORDER BY id', (client_id,))
    if child_id and child_id not in [k['id'] for k in kids]:
        raise ApiError(400, 'child_not_of_client')
    slot_day = local(sl['starts_at']).date()
    sid = pick_subscription(x, client_id, sl['service_id'], slot_day, child_id, subscription_id)
    sub = lock_subscription(x, sid)
    if sub['child_id']:
        child_id = sub['child_id']
    elif not child_id and len(kids) == 1:
        child_id = kids[0]['id']
    elif not child_id and len(kids) > 1:
        raise ApiError(400, 'choose_child')
    left = x.one('SELECT remaining FROM subscription_items WHERE subscription_id=%s AND service_id=%s FOR UPDATE',
                 (sid, sl['service_id']))['remaining']
    if left - reserved(x, sid, sl['service_id']) <= 0:
        raise ApiError(409, 'all_visits_reserved')
    if x.one("""SELECT 1 FROM bookings WHERE slot_id=%s AND client_id=%s AND child_id IS NOT DISTINCT FROM %s
                AND status IN ('booked','attended')""", (sl['id'], client_id, child_id)):
        raise ApiError(409, 'already_booked')
    row = x.one('''INSERT INTO bookings(slot_id, subscription_id, client_id, child_id, created_by)
        VALUES (%s,%s,%s,%s,%s) RETURNING id''', (sl['id'], sid, client_id, child_id, x.user['id']))
    x.audit('book', 'subscription', sid, booking_id=row['id'], slot_id=sl['id'], starts_at=sl['starts_at'], child_id=child_id)
    if by_staff:
        x.notify_client(client_id, f"📅 Вы записаны: <b>{tgbot.e(sl['service_name'])}</b> {when(sl['starts_at'])}"
                        + (f" · {tgbot.e(sl['specialist_name'])}" if sl['specialist_name'] else '')
                        + '\nОтменить запись можно в боте: «🗓 Мои записи».')
    return row['id'], sl


def cancel_booking(x, booking_id, by_staff, why=None, confirm_late=False):
    b = found(x.one('SELECT subscription_id FROM bookings WHERE id=%s', (booking_id,)), 'booking_not_found')
    sub = lock_subscription(x, b['subscription_id'])
    b = x.one('''SELECT b.*, sl.starts_at, sl.service_id, sv.name_ru AS service_name, sv.late_cancel_forfeit
        FROM bookings b JOIN slots sl ON sl.id=b.slot_id JOIN services sv ON sv.id=sl.service_id WHERE b.id=%s FOR UPDATE OF b''', (booking_id,))
    if b['status'] != 'booked':
        raise ApiError(409, 'booking_not_active')
    if b['starts_at'] <= now() and not by_staff:
        raise ApiError(409, 'session_started')
    late = (not by_staff) and b['late_cancel_forfeit'] and now() >= late_cutoff(b['starts_at'])
    if late and not confirm_late:
        raise ApiError(409, 'late_cancel_confirm', {'cutoff': late_cutoff(b['starts_at'])})
    forfeited = False
    if late:
        item = x.one('SELECT remaining FROM subscription_items WHERE subscription_id=%s AND service_id=%s FOR UPDATE',
                     (sub['id'], b['service_id']))
        if item['remaining'] > 0:
            x.c.execute('UPDATE subscription_items SET remaining=remaining-1 WHERE subscription_id=%s AND service_id=%s',
                        (sub['id'], b['service_id']))
            v = x.one('''INSERT INTO visits(subscription_id, service_id, child_id, method, visited_at, staff_id)
                VALUES (%s,%s,%s,'late_cancel',%s,%s) RETURNING id''', (sub['id'], b['service_id'], b['child_id'], now(), x.user['id']))
            x.c.execute('UPDATE bookings SET visit_id=%s WHERE id=%s', (v['id'], booking_id))
            forfeited = True
    x.c.execute('''UPDATE bookings SET status='cancelled', cancelled_at=%s, cancelled_by=%s, cancel_reason=%s, forfeited=%s
        WHERE id=%s''', (now(), x.user['id'], why or ('Отменено клиентом' if not by_staff else 'Отменено центром'), forfeited, booking_id))
    x.audit('cancel_booking', 'subscription', sub['id'], booking_id=booking_id, by_staff=by_staff, forfeited=forfeited, reason=why)
    if by_staff:
        x.notify_client(b['client_id'], f"❗ Запись <b>{tgbot.e(b['service_name'])}</b> {when(b['starts_at'])} отменена центром."
                        + (f"\nПричина: {tgbot.e(why)}" if why else '') + '\nПосещение не списано.')
    return {'ok': True, 'forfeited': forfeited}


def link_visit_to_booking(x, sub, service_id, child_id, visit_id):
    """Called by redeem(): mark today's booking of this subscription as attended."""
    row = x.one("""SELECT b.id FROM bookings b JOIN slots sl ON sl.id=b.slot_id
        WHERE b.subscription_id=%s AND sl.service_id=%s AND b.status='booked'
          AND (sl.starts_at AT TIME ZONE 'Asia/Tashkent')::date = %s
          AND (b.child_id IS NULL OR %s::bigint IS NULL OR b.child_id = %s::bigint)
        ORDER BY abs(extract(epoch FROM sl.starts_at - %s)) LIMIT 1 FOR UPDATE OF b""",
                (sub['id'], service_id, today(), child_id, child_id, now()))
    if row:
        x.c.execute("UPDATE bookings SET status='attended', visit_id=%s WHERE id=%s", (visit_id, row['id']))
    return row['id'] if row else None


# ------------------------------------------------------------------ staff endpoints

@api('/bookings', ('POST',))
def booking_create(x):
    with x.c.transaction():
        bid, _ = create_booking(x, x.body.get('slot_id'), ident(x.body.get('client_id'), 'client_id'),
                                ident(x.body.get('child_id'), 'child_id', required=False),
                                ident(x.body.get('subscription_id'), 'subscription_id', required=False), by_staff=True)
    return {'id': bid}


@api('/bookings/{id}/cancel', ('POST',))
def booking_cancel(x):
    why = reason(x.body)
    with x.c.transaction():
        return cancel_booking(x, ident(x.params['id']), by_staff=True, why=why)


@api('/bookings/{id}/attend', ('POST',))
def booking_attend(x):
    bid = ident(x.params['id'])
    with x.c.transaction():
        b = found(x.one('SELECT subscription_id FROM bookings WHERE id=%s', (bid,)), 'booking_not_found')
        sub = lock_subscription(x, b['subscription_id'])
        b = x.one('''SELECT b.*, sl.service_id, sl.specialist_id, sl.starts_at FROM bookings b JOIN slots sl ON sl.id=b.slot_id
            WHERE b.id=%s FOR UPDATE OF b''', (bid,))
        if b['status'] != 'booked':
            raise ApiError(409, 'booking_not_active')
        if local(b['starts_at']).date() != today():
            raise ApiError(409, 'booking_not_today')
        return redeem(x, sub, b['service_id'], b['child_id'], b['specialist_id'], 'manual', force=True, booking_id=bid)


@api('/bookings/{id}/no-show', ('POST',))
def booking_no_show(x):
    bid = ident(x.params['id'])
    with x.c.transaction():
        b = found(x.one('SELECT subscription_id FROM bookings WHERE id=%s', (bid,)), 'booking_not_found')
        sub = lock_subscription(x, b['subscription_id'])
        b = x.one('''SELECT b.*, sl.service_id, sl.starts_at, sv.late_cancel_forfeit, sv.name_ru AS service_name
            FROM bookings b JOIN slots sl ON sl.id=b.slot_id JOIN services sv ON sv.id=sl.service_id WHERE b.id=%s FOR UPDATE OF b''', (bid,))
        if b['status'] != 'booked':
            raise ApiError(409, 'booking_not_active')
        if b['starts_at'] > now():
            raise ApiError(409, 'session_not_started')
        forfeited = False
        if b['late_cancel_forfeit']:
            item = x.one('SELECT remaining FROM subscription_items WHERE subscription_id=%s AND service_id=%s FOR UPDATE',
                         (sub['id'], b['service_id']))
            if item['remaining'] > 0:
                x.c.execute('UPDATE subscription_items SET remaining=remaining-1 WHERE subscription_id=%s AND service_id=%s',
                            (sub['id'], b['service_id']))
                v = x.one('''INSERT INTO visits(subscription_id, service_id, child_id, method, visited_at, staff_id)
                    VALUES (%s,%s,%s,'no_show',%s,%s) RETURNING id''', (sub['id'], b['service_id'], b['child_id'], b['starts_at'], x.user['id']))
                x.c.execute('UPDATE bookings SET visit_id=%s WHERE id=%s', (v['id'], bid))
                forfeited = True
        x.c.execute("UPDATE bookings SET status='no_show', forfeited=%s WHERE id=%s", (forfeited, bid))
        x.audit('no_show', 'subscription', sub['id'], booking_id=bid, forfeited=forfeited)
        if forfeited:
            x.notify_client(b['client_id'], f"😔 Вы не пришли на занятие <b>{tgbot.e(b['service_name'])}</b> {when(b['starts_at'])}. "
                            'По правилам центра посещение списано.')
    return {'ok': True, 'forfeited': forfeited}


@api('/clients/{id}/bookings')
def client_bookings(x):
    return bookings_query(x, "b.client_id=%s AND sl.starts_at > now() - interval '30 days'", (ident(x.params['id']),))


# ------------------------------------------------------------------ parent endpoints (app / bot share this logic)

def my_client_id(x):
    row = found(x.one('SELECT id FROM clients WHERE user_id=%s AND NOT archived', (x.user['id'],)), 'client_not_found')
    return row['id']


def available_slots(x, client_id, service_id=None, days=14):
    """Future, not full slots for services the client can currently pay for."""
    t = now()
    args = [client_id, t, t + timedelta(days=days)]
    extra = ''
    if service_id:
        extra = ' AND sl.service_id = %s'
        args.append(service_id)
    return x.all(f'''SELECT {SLOT_COLS} FROM {SLOT_FROM}
        WHERE sl.cancelled_at IS NULL AND sl.service_id IN (
              SELECT si.service_id FROM subscriptions s JOIN subscription_items si ON si.subscription_id=s.id
              WHERE s.client_id=%s AND s.status='active' AND si.remaining > 0)
          AND sl.starts_at > %s AND sl.starts_at < %s {extra}
          AND (SELECT count(*) FROM bookings b WHERE b.slot_id=sl.id AND b.status IN ('booked','attended')) < sl.capacity
        ORDER BY sl.starts_at, sv.sort LIMIT 300''', args)


@api('/my/slots', roles=CLIENT)
def my_slots(x):
    cid = my_client_id(x)
    rows = available_slots(x, cid, ident(x.query.get('service_id'), 'service_id', required=False))
    for r in rows:
        r['free'] = r['capacity'] - r['booked']
        for k in ('booked', 'capacity', 'note', 'cancelled_at', 'cancel_reason'):
            r.pop(k, None)
    return rows


@api('/my/bookings', roles=CLIENT)
def my_bookings(x):
    rows = bookings_query(x, "b.client_id=%s AND sl.starts_at > now() - interval '1 day' AND b.status='booked'", (my_client_id(x),))
    for r in rows:
        r['free_cancel_until'] = late_cutoff(r['starts_at'])
        r.pop('client_phone', None)
    return rows


@api('/my/bookings', ('POST',), roles=CLIENT)
def my_booking_create(x):
    with x.c.transaction():
        bid, sl = create_booking(x, x.body.get('slot_id'), my_client_id(x), ident(x.body.get('child_id'), 'child_id', required=False))
    return {'id': bid, 'starts_at': sl['starts_at']}


@api('/my/bookings/{id}/cancel', ('POST',), roles=CLIENT)
def my_booking_cancel(x):
    bid = ident(x.params['id'])
    with x.c.transaction():
        if not x.one('SELECT 1 FROM bookings WHERE id=%s AND client_id=%s', (bid, my_client_id(x))):
            raise ApiError(404, 'booking_not_found')
        return cancel_booking(x, bid, by_staff=False, confirm_late=x.body.get('confirm_late') is True)
