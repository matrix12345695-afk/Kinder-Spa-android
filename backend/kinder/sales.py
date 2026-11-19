"""Own cash desk: sales (a cart of subscriptions paid in one or several ways) and cash shifts.
Imported at the end of kinder.app to register routes."""
from decimal import Decimal

from .app import (PAYMENT_METHODS, ApiError, api, day, found, ident, insert_subscription, lock_client_for_sale, money,
                  notify_sub_created, now, open_shift_id, record_payment, text, today)

ZERO = Decimal('0')


def parse_payments(raw):
    if raw in (None, ''):
        return []
    if not isinstance(raw, list) or len(raw) > 6:
        raise ApiError(400, 'invalid_field', 'payments')
    out = []
    for p in raw:
        if not isinstance(p, dict) or p.get('method') not in PAYMENT_METHODS:
            raise ApiError(400, 'invalid_field', 'method')
        amount = money(p.get('amount'), 'amount')
        if amount:
            out.append((p['method'], amount))
    return out


@api('/sales', ('POST',))
def sale_create(x):
    cid = ident(x.body.get('client_id'), 'client_id')
    items = x.body.get('items')
    if not isinstance(items, list) or not items:
        raise ApiError(400, 'items_required')
    if len(items) > 20 or not all(isinstance(i, dict) for i in items):
        raise ApiError(400, 'invalid_field', 'items')
    pays = parse_payments(x.body.get('payments'))
    note = text(x.body, 'note', max_len=300)
    with x.c.transaction():
        lock_client_for_sale(x, cid)
        sale_id = x.one('INSERT INTO sales(client_id, staff_id, shift_id, created_at, note) VALUES (%s,%s,%s,%s,%s) RETURNING id',
                        (cid, x.user['id'], open_shift_id(x), now(), note))['id']
        subs = [insert_subscription(x, cid, item, sale_id) for item in items]
        total = sum((s['price'] for s in subs), ZERO)
        paid_total = sum((a for _, a in pays), ZERO)
        if paid_total > total:
            raise ApiError(409, 'overpayment', {'debt': total})
        # Each payment fills the subscriptions in cart order; one payment may be split across several of them.
        paid = {s['id']: ZERO for s in subs}
        queue = list(pays)
        for s in subs:
            while queue and paid[s['id']] < s['price']:
                method, amount = queue[0]
                piece = min(amount, s['price'] - paid[s['id']])
                record_payment(x, s['id'], s['price'], paid[s['id']], piece, method, '', sale_id)
                paid[s['id']] += piece
                queue[0] = (method, amount - piece)
                if queue[0][1] == 0:
                    queue.pop(0)
        x.audit('sale', 'sale', sale_id, client_id=cid, total=total, paid=paid_total, subscriptions=[s['id'] for s in subs])
        for s in subs:
            notify_sub_created(x, cid, s, s['price'] - paid[s['id']])
    return {'id': sale_id, 'total': total, 'paid': paid_total, 'debt': total - paid_total}


def sale_items(x, sale_id):
    return x.all('''SELECT s.id, s.name, s.price, s.starts_on, s.ends_on, ch.full_name AS child_name, sp.full_name AS seller_name
        FROM subscriptions s LEFT JOIN children ch ON ch.id=s.child_id LEFT JOIN specialists sp ON sp.id=s.seller_id
        WHERE s.sale_id=%s ORDER BY s.id''', (sale_id,))


@api('/sales/{id}')
def sale_get(x):
    sale = found(x.one('''SELECT sa.id, sa.created_at, sa.note, sa.shift_id, sa.client_id, c.full_name AS client_name, c.phone AS client_phone,
            u.full_name AS staff_name FROM sales sa JOIN clients c ON c.id=sa.client_id JOIN users u ON u.id=sa.staff_id
        WHERE sa.id=%s''', (ident(x.params['id']),)))
    sale['items'] = sale_items(x, sale['id'])
    sale['payments'] = x.all('''SELECT method, sum(amount) AS amount FROM payments
        WHERE sale_id=%s AND voided_at IS NULL GROUP BY method ORDER BY 2 DESC''', (sale['id'],))
    sale['total'] = sum((i['price'] for i in sale['items']), ZERO)
    sale['paid'] = sum((p['amount'] for p in sale['payments']), ZERO)
    sale['debt'] = max(ZERO, sale['total'] - sale['paid'])
    sale['center'] = {r['key']: r['value'] for r in x.all("SELECT key, value FROM center_settings WHERE key IN ('phone','address')")}
    return sale


@api('/sales')
def sales_list(x):
    start = day(x.query.get('from'), 'from') or today()
    end = day(x.query.get('to'), 'to') or start
    if end < start or (end - start).days > 366:
        raise ApiError(400, 'invalid_period')
    return x.all('''SELECT sa.id, sa.created_at, sa.client_id, c.full_name AS client_name, u.full_name AS staff_name,
            (SELECT coalesce(sum(price),0) FROM subscriptions WHERE sale_id=sa.id) AS total,
            (SELECT coalesce(sum(amount),0) FROM payments WHERE sale_id=sa.id AND voided_at IS NULL) AS paid,
            (SELECT string_agg(name, ', ' ORDER BY id) FROM subscriptions WHERE sale_id=sa.id) AS items
        FROM sales sa JOIN clients c ON c.id=sa.client_id JOIN users u ON u.id=sa.staff_id
        WHERE (sa.created_at AT TIME ZONE 'Asia/Tashkent')::date BETWEEN %s AND %s ORDER BY sa.id DESC LIMIT 1000''', (start, end))


# ---------------------------------------------------------------- cash shifts

def shift_summary(x, shift):
    by_method = {m: ZERO for m in PAYMENT_METHODS}
    for r in x.all('''SELECT method, sum(amount) AS amount FROM payments WHERE shift_id=%s AND voided_at IS NULL
                      GROUP BY method''', (shift['id'],)):
        by_method[r['method']] = r['amount']
    ops = x.all('''SELECT o.id, o.kind, o.amount, o.reason, o.at, u.full_name AS staff_name FROM cash_ops o
        JOIN users u ON u.id=o.staff_id WHERE o.shift_id=%s ORDER BY o.id''', (shift['id'],))
    cash_in = sum((o['amount'] for o in ops if o['kind'] == 'in'), ZERO)
    cash_out = sum((o['amount'] for o in ops if o['kind'] == 'out'), ZERO)
    shift.update(by_method=by_method, total=sum(by_method.values()), ops=ops, cash_in=cash_in, cash_out=cash_out,
                 cash_now=shift['opening_cash'] + by_method['cash'] + cash_in - cash_out,
                 sales=x.one('SELECT count(*) AS n FROM sales WHERE shift_id=%s', (shift['id'],))['n'])
    if shift['closed_at']:
        shift['difference'] = shift['closing_cash'] - shift['expected_cash']
    return shift


SHIFT_SQL = '''SELECT sh.*, ou.full_name AS opened_by_name, cu.full_name AS closed_by_name FROM cash_shifts sh
    JOIN users ou ON ou.id=sh.opened_by LEFT JOIN users cu ON cu.id=sh.closed_by'''


@api('/shifts/current')
def shift_current(x):
    row = x.one(SHIFT_SQL + ' WHERE sh.closed_at IS NULL')
    return {'shift': shift_summary(x, row) if row else None}


@api('/shifts/open', ('POST',))
def shift_open(x):
    opening = money(x.body.get('opening_cash'), 'opening_cash') or ZERO
    with x.c.transaction():
        x.c.execute('LOCK TABLE cash_shifts IN SHARE ROW EXCLUSIVE MODE')
        if open_shift_id(x):
            raise ApiError(409, 'shift_already_open')
        sid = x.one('INSERT INTO cash_shifts(opened_by, opened_at, opening_cash) VALUES (%s,%s,%s) RETURNING id',
                    (x.user['id'], now(), opening))['id']
        x.audit('open_shift', 'shift', sid, opening_cash=opening)
    return {'id': sid}


@api('/shifts/current/ops', ('POST',))
def shift_op(x):
    kind = x.body.get('kind')
    if kind not in ('in', 'out'):
        raise ApiError(400, 'invalid_field', 'kind')
    amount = money(x.body.get('amount'), 'amount')
    if not amount:
        raise ApiError(400, 'invalid_field', 'amount')
    why = text(x.body, 'reason', required=True, max_len=300)
    if len(why) < 3:
        raise ApiError(400, 'reason_required')
    with x.c.transaction():
        shift = x.one(SHIFT_SQL + ' WHERE sh.closed_at IS NULL FOR UPDATE OF sh')
        if not shift:
            raise ApiError(409, 'no_open_shift')
        if kind == 'out' and amount > shift_summary(x, shift)['cash_now']:
            raise ApiError(409, 'not_enough_cash')
        oid = x.one('INSERT INTO cash_ops(shift_id, kind, amount, reason, staff_id, at) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id',
                    (shift['id'], kind, amount, why, x.user['id'], now()))['id']
        x.audit('cash_' + kind, 'shift', shift['id'], amount=amount, reason=why)
    return {'id': oid}


@api('/shifts/close', ('POST',))
def shift_close(x):
    counted = money(x.body.get('closing_cash'), 'closing_cash')
    if counted is None:
        raise ApiError(400, 'field_required', 'closing_cash')
    note = text(x.body, 'note', max_len=500)
    with x.c.transaction():
        shift = x.one(SHIFT_SQL + ' WHERE sh.closed_at IS NULL FOR UPDATE OF sh')
        if not shift:
            raise ApiError(409, 'no_open_shift')
        expected = shift_summary(x, shift)['cash_now']
        x.c.execute('UPDATE cash_shifts SET closed_by=%s, closed_at=%s, closing_cash=%s, expected_cash=%s, note=%s WHERE id=%s',
                    (x.user['id'], now(), counted, expected, note, shift['id']))
        x.audit('close_shift', 'shift', shift['id'], closing_cash=counted, expected_cash=expected, note=note)
    return {'id': shift['id'], 'expected_cash': expected, 'difference': counted - expected}


@api('/shifts')
def shifts_list(x):
    return [shift_summary(x, r) for r in x.all(SHIFT_SQL + ' ORDER BY sh.id DESC LIMIT 60')]


@api('/shifts/{id}')
def shift_get(x):
    return shift_summary(x, found(x.one(SHIFT_SQL + ' WHERE sh.id=%s', (ident(x.params['id']),))))
