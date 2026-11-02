from datetime import datetime, timedelta, timezone

from conftest import Client
from test_api import mk_client, plan_id, service_id

TZ = timezone(timedelta(hours=5))


def test_payments_debts_and_cash(owner, server, clock):
    clock(datetime(2026, 11, 10, 10, 0, tzinfo=TZ))
    cl = mk_client(owner, 'Платёжный Клиент')
    _, r = owner.post('/api/subscriptions', {'client_id': cl['id'], 'plan_id': plan_id(owner, 'Бассейн — 8 занятий'),
                                             'price': '400000', 'paid_amount': '150000', 'paid_method': 'cash'}, expect=200)
    sid = r['id']
    _, sub = owner.get(f'/api/subscriptions/{sid}', expect=200)
    assert sub['paid'] == '150000.00' and sub['debt'] == '250000.00' and len(sub['payments']) == 1
    _, debts = owner.get('/api/subscriptions?state=debt', expect=200)
    assert any(s['id'] == sid for s in debts)

    assert owner.post(f'/api/subscriptions/{sid}/payments', {'amount': '300000', 'method': 'card'})[1]['error'] == 'overpayment'
    assert owner.post(f'/api/subscriptions/{sid}/payments', {'amount': '1000', 'method': 'bitcoin'})[0] == 400
    _, p = owner.post(f'/api/subscriptions/{sid}/payments', {'amount': '200000', 'method': 'click', 'note': 'перевод от папы'}, expect=200)
    assert p['debt'] == '50000.00'
    owner.post(f'/api/subscriptions/{sid}/payments', {'amount': '50000', 'method': 'card'}, expect=200)
    assert owner.get(f'/api/subscriptions/{sid}')[1]['debt'] == '0.00'
    assert all(s['id'] != sid for s in owner.get('/api/subscriptions?state=debt')[1])

    _, cash = owner.get('/api/payments?from=2026-11-10&to=2026-11-10', expect=200)
    assert cash['by_method']['cash'] == '150000.00' and cash['by_method']['click'] == '200000.00'
    assert cash['total'] == '400000.00'
    _, rep = owner.get('/api/reports?from=2026-11-10&to=2026-11-10', expect=200)
    assert rep['received']['total'] == '400000.00'

    # an admin may void only own payments of today; the owner may void any
    _, st = owner.post('/api/staff', {'login': 'cashier1', 'full_name': 'Кассир'}, expect=200)
    cashier = Client(server).login('cashier1', st['password'])
    own = cashier.post(f'/api/subscriptions/{sid}/payments', {'amount': '1', 'method': 'cash'})
    assert own[1]['error'] == 'overpayment'
    owner_payment = owner.get(f'/api/subscriptions/{sid}')[1]['payments'][0]
    assert cashier.post(f"/api/payments/{owner_payment['id']}/void", {'reason': 'ошибка'})[1]['error'] == 'void_needs_superadmin'
    owner.post(f"/api/payments/{owner_payment['id']}/void", {'reason': 'ошибка суммы'}, expect=200)
    assert owner.post(f"/api/payments/{owner_payment['id']}/void", {'reason': 'ещё'})[1]['error'] == 'already_voided'
    _, sub = owner.get(f'/api/subscriptions/{sid}')
    assert sub['debt'] == owner_payment['amount']
    _, newp = cashier.post(f'/api/subscriptions/{sid}/payments', {'amount': sub['debt'], 'method': 'cash'}, expect=200)
    cashier.post(f"/api/payments/{newp['id']}/void", {'reason': 'передумали'}, expect=200)
    clock(datetime(2026, 11, 11, 10, 0, tzinfo=TZ))
    _, again = cashier.post(f'/api/subscriptions/{sid}/payments', {'amount': sub['debt'], 'method': 'cash'}, expect=200)
    clock(datetime(2026, 11, 12, 10, 0, tzinfo=TZ))
    assert cashier.post(f"/api/payments/{again['id']}/void", {'reason': 'поздно'})[1]['error'] == 'void_needs_superadmin'


def test_parent_sees_debt_not_price(owner, server):
    cl = mk_client(owner, 'Долг Родителя')
    owner.post('/api/subscriptions', {'client_id': cl['id'], 'plan_id': plan_id(owner, 'Массаж — 10 сеансов'), 'price': '500000'}, expect=200)
    _, cred = owner.post(f"/api/clients/{cl['id']}/credentials", expect=200)
    parent = Client(server).login(cred['login'], cred['password'])
    sub = parent.get('/api/my/subscriptions', expect=200)[1][0]
    assert sub['debt'] == '500000.00' and 'price' not in sub and 'paid' not in sub
