from test_api import mk_client, plan_id


def n(v):
    return float(v)


def close_any_shift(owner):
    if owner.get('/api/shifts/current')[1]['shift']:
        owner.post('/api/shifts/close', {'closing_cash': 0}, expect=200)


def specialist(owner, name):
    _, r = owner.post('/api/specialists', {'full_name': name, 'service_ids': []}, expect=200)
    return r['id']


def test_cart_sale_split_payment_seller_and_receipt(owner):
    close_any_shift(owner)
    cl = mk_client(owner, 'Продажа Корзина', children=('Ваня', 'Катя'))
    kid = cl['children'][0]['id']
    seller = specialist(owner, 'Феруза массажист')
    body = {'client_id': cl['id'], 'items': [
        {'plan_id': plan_id(owner, 'Бассейн — 4 занятия'), 'price': 600000, 'child_id': kid, 'seller_id': seller},
        {'plan_id': plan_id(owner, 'Массаж — 10 сеансов'), 'price': 400000}],
        'payments': [{'method': 'cash', 'amount': 700000}, {'method': 'qr', 'amount': 200000}]}
    _, sale = owner.post('/api/sales', body, expect=200)
    assert (n(sale['total']), n(sale['paid']), n(sale['debt'])) == (1000000, 900000, 100000)

    _, r = owner.get(f"/api/sales/{sale['id']}", expect=200)
    assert [i['seller_name'] for i in r['items']] == ['Феруза массажист', None]
    assert r['items'][0]['child_name'] == 'Ваня'
    assert {p['method']: n(p['amount']) for p in r['payments']} == {'cash': 700000, 'qr': 200000}
    # cash 700k fills the pool (600k) and 100k of massage; QR pays 200k more of massage, 100k stays as debt
    _, c = owner.get(f"/api/clients/{cl['id']}", expect=200)
    debts = sorted(n(s['debt']) for s in c['subscriptions'])
    assert debts == [0, 100000]

    _, rep = owner.get('/api/reports', expect=200)
    names = {s['name']: n(s['revenue']) for s in rep['sellers']}
    assert names['Феруза массажист'] >= 600000
    assert n(rep['received']['by_method']['qr']) >= 200000
    assert any(s['id'] == sale['id'] for s in owner.get('/api/sales', expect=200)[1])


def test_sale_rejects_overpayment_and_rolls_back(owner):
    cl = mk_client(owner, 'Продажа Переплата')
    body = {'client_id': cl['id'], 'items': [{'plan_id': plan_id(owner, 'Массаж — 10 сеансов'), 'price': 100000}],
            'payments': [{'method': 'card', 'amount': 150000}]}
    assert owner.post('/api/sales', body)[1]['error'] == 'overpayment'
    _, c = owner.get(f"/api/clients/{cl['id']}", expect=200)
    assert c['subscriptions'] == []
    assert owner.post('/api/sales', {'client_id': cl['id'], 'items': []})[1]['error'] == 'items_required'
    bad = dict(body, payments=[{'method': 'bitcoin', 'amount': 1}])
    assert owner.post('/api/sales', bad)[1]['error'] == 'invalid_field'


def test_cash_shift_open_ops_close(owner):
    close_any_shift(owner)
    assert owner.post('/api/shifts/close', {'closing_cash': 0})[1]['error'] == 'no_open_shift'
    owner.post('/api/shifts/open', {'opening_cash': 50000}, expect=200)
    assert owner.post('/api/shifts/open', {'opening_cash': 0})[1]['error'] == 'shift_already_open'

    cl = mk_client(owner, 'Продажа Смена')
    owner.post('/api/sales', {'client_id': cl['id'], 'items': [{'plan_id': plan_id(owner, 'Массаж — 10 сеансов'), 'price': 300000}],
                              'payments': [{'method': 'cash', 'amount': 200000}, {'method': 'card', 'amount': 100000}]}, expect=200)
    owner.post('/api/shifts/current/ops', {'kind': 'out', 'amount': 30000, 'reason': 'Хозтовары'}, expect=200)
    assert owner.post('/api/shifts/current/ops', {'kind': 'out', 'amount': 10**7, 'reason': 'Слишком много'})[1]['error'] == 'not_enough_cash'

    _, cur = owner.get('/api/shifts/current', expect=200)
    sh = cur['shift']
    assert n(sh['by_method']['cash']) == 200000 and n(sh['by_method']['card']) == 100000 and sh['sales'] == 1
    assert n(sh['cash_now']) == 50000 + 200000 - 30000

    _, closed = owner.post('/api/shifts/close', {'closing_cash': 215000, 'note': 'недостача'}, expect=200)
    assert n(closed['expected_cash']) == 220000 and n(closed['difference']) == -5000
    assert owner.get('/api/shifts/current', expect=200)[1]['shift'] is None
    _, hist = owner.get('/api/shifts', expect=200)
    assert n(hist[0]['difference']) == -5000 and n(hist[0]['closing_cash']) == 215000
