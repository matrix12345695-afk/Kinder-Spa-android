"""End-to-end check of the admin panel in real Chromium (skipped if Playwright is unavailable)."""
import os
from pathlib import Path

import pytest

from conftest import Client

sync_api = pytest.importorskip('playwright.sync_api')
SHOTS = Path(os.environ.get('KINDER_SCREENSHOTS', '/tmp/kinder-shots'))


@pytest.fixture
def page(server):
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # browser binary missing
            pytest.skip(f'chromium unavailable: {e}')
        pg = browser.new_page(viewport={'width': 1366, 'height': 860}, locale='ru-RU', timezone_id='Asia/Tashkent')
        errors = []
        pg.on('pageerror', lambda e: errors.append(str(e)))
        pg.on('console', lambda m: m.type == 'error' and 'Failed to load resource' not in m.text and errors.append(m.text))
        pg.errors = errors
        yield pg
        browser.close()


def shot(pg, name):
    pg.screenshot(path=str(SHOTS / f'{name}.png'), full_page=True)


def test_reception_workflow(page, server):
    pg = page
    pg.goto(server + '/admin/')
    pg.fill('input[name=login]', 'owner')
    pg.fill('input[name=password]', 'wrong-password')
    pg.click('button[type=submit]')
    pg.wait_for_selector('text=Неверный логин или пароль')
    pg.fill('input[name=password]', 'owner-pass-123')
    pg.click('button[type=submit]')
    pg.wait_for_selector('h1:has-text("Сегодня")')
    shot(pg, '01-today')

    # new client with a child
    pg.click('nav >> text=Клиенты')
    pg.click('text=+ Новый клиент')
    pg.fill('.modal input[name=full_name]', 'Браузерова Мадина')
    pg.fill('.modal input[name=phone]', '+998 90 777 66 55')
    pg.fill('.modal [data-kid=name]', 'Амир')
    pg.click('.modal button[type=submit]')
    pg.wait_for_selector('h1:has-text("Браузерова Мадина")')
    assert pg.inner_text('h1').strip() == 'Браузерова Мадина'
    assert '+998 90 777 66 55' in pg.inner_text('main')

    # subscription from plan
    pg.click('text=+ Абонемент')
    pg.select_option('.modal select[name=plan_id]', label=pg.locator('.modal select[name=plan_id] option', has_text='Бассейн — 8').inner_text())
    pg.fill('.modal input[name=price]', '400000')
    pg.click('.modal button[type=submit]')
    pg.wait_for_selector('.sub:has-text("Бассейн — 8 занятий")')

    # manual visit
    pg.click('text=Отметить посещение')
    pg.click('.modal button[type=submit]')
    pg.wait_for_selector('text=Списано. Осталось: 7')
    pg.wait_for_selector('.item:has-text("7")')

    # duplicate warning, decline
    pg.click('text=Отметить посещение')
    pg.click('.modal button[type=submit]')
    pg.wait_for_selector('h2:has-text("Повторное посещение?")')
    pg.click('.modal button:has-text("Отмена")')

    # freeze / unfreeze
    pg.click('.sub button:has-text("Заморозить")')
    pg.fill('.modal textarea[name=reason]', 'простуда')
    pg.click('.modal button[type=submit]')
    pg.wait_for_selector('.badge.frozen')
    pg.click('.sub button:has-text("Разморозить")')
    pg.wait_for_selector('.sub .badge.active')

    # app credentials
    pg.click('text=Выдать логин и пароль')
    pg.wait_for_selector('.secret')
    login = pg.locator('.secret b').nth(0).inner_text()
    password = pg.locator('.secret b').nth(1).inner_text()
    pg.click('.modal button:has-text("Готово")')
    shot(pg, '02-client-card')

    # parent creates a QR in the app, reception scans it (USB scanner = typing + Enter)
    parent = Client(server).login(login, password)
    _, qr = parent.post('/api/my/qr')
    pg.click('nav >> text=Сканер QR')
    pg.fill('.scan-input', qr['code'])
    pg.press('.scan-input', 'Enter')
    pg.wait_for_selector('h2:has-text("Браузерова Мадина")')
    shot(pg, '03-scan-result')
    pg.click('button:has-text("Списать посещение")')
    # a manual visit for the same child/service was already recorded today -> confirmation
    pg.wait_for_selector('h2:has-text("Повторное посещение?")')
    pg.click('.modal button:has-text("Да, отметить")')
    pg.wait_for_selector('h2:has-text("Посещение списано")')
    pg.fill('.scan-input', qr['code'])
    pg.press('.scan-input', 'Enter')
    pg.wait_for_selector('text=QR-код уже использован')

    # visits list and cancellation
    pg.click('nav >> text=Посещения')
    pg.wait_for_selector('table >> text=Браузерова Мадина')
    pg.locator('button:has-text("Отменить")').first.click()
    pg.fill('.modal textarea[name=reason]', 'ошибочная отметка')
    pg.click('.modal button[type=submit]')
    pg.wait_for_selector('tr.cancelled')
    shot(pg, '04-visits')

    # catalogue pages
    pg.click('nav >> text=Специалисты')
    pg.click('text=+ Специалист')
    pg.fill('.modal input[name=full_name]', 'Инструктор Камила')
    pg.locator('.modal label:has-text("Бассейн") input').check()
    pg.click('.modal button[type=submit]')
    pg.wait_for_selector('td:has-text("Инструктор Камила")')
    pg.click('nav >> text=Услуги')
    try:
        pg.wait_for_selector('h2:has-text("Детский массаж")', timeout=5000)
    except Exception:
        shot(pg, 'fail-services'); print('ERRORS', pg.errors); raise
    shot(pg, '05-services')
    pg.click('nav >> text=Тарифы')
    pg.wait_for_selector('td:has-text("Бассейн — 12 занятий")')
    pg.click('nav >> text=Отчёты')
    pg.wait_for_selector('h2:has-text("По услугам")')
    shot(pg, '06-reports')
    pg.click('nav >> text=Абонементы')
    pg.wait_for_selector('h1:has-text("Абонементы")')
    pg.click('nav >> text=Сотрудники')
    pg.click('text=+ Сотрудник')
    pg.fill('.modal input[name=full_name]', 'Ресепшен Утро')
    pg.fill('.modal input[name=login]', 'morning')
    pg.click('.modal button[type=submit]')
    pg.wait_for_selector('.secret')
    pg.click('.modal button:has-text("Готово")')
    pg.wait_for_selector('td:has-text("morning")')
    pg.click('nav >> text=Журнал')
    pg.wait_for_selector('td:has-text("Отмена посещения")')
    shot(pg, '07-audit')

    # mobile layout
    pg.set_viewport_size({'width': 390, 'height': 800})
    pg.click('nav >> text=Сегодня') if pg.locator('nav').is_visible() else pg.click('.topbar button')
    pg.wait_for_timeout(200)
    shot(pg, '08-mobile')
    assert not pg.errors, pg.errors


def test_admin_rejects_parent_login(page, server, owner):
    _, r = owner.post('/api/clients', {'full_name': 'Родитель Входа'})
    _, cred = owner.post(f"/api/clients/{r['id']}/credentials")
    page.goto(server + '/admin/')
    page.fill('input[name=login]', cred['login'])
    page.fill('input[name=password]', cred['password'])
    page.click('button[type=submit]')
    page.wait_for_selector('text=Это вход для сотрудников')


def test_payments_ui(page, server, owner):
    _, r = owner.post('/api/clients', {'full_name': 'Касса Браузер', 'children': [{'full_name': 'Сара'}]}, expect=200)
    pg = page
    pg.goto(server + '/admin/')
    pg.fill('input[name=login]', 'owner')
    pg.fill('input[name=password]', 'owner-pass-123')
    pg.click('button[type=submit]')
    pg.wait_for_selector('h1:has-text("Сегодня")')
    pg.goto(server + f"/admin/#client/{r['id']}")
    pg.wait_for_selector('h1:has-text("Касса Браузер")')
    pg.click('text=+ Абонемент')
    pg.fill('.modal input[name=price]', '300000')
    pg.fill('.modal input[name=paid_amount]', '100000')
    pg.select_option('.modal select[name=paid_method]', 'card')
    pg.click('.modal button[type=submit]')
    pg.wait_for_selector('.sub .badge.bad:has-text("долг")')
    pg.click('.sub button:has-text("Принять оплату")')
    assert pg.input_value('.modal input[name=amount]') == '200000.00'
    pg.select_option('.modal select[name=method]', 'payme')
    pg.click('.modal button[type=submit]')
    pg.wait_for_selector('.sub .badge.active:has-text("оплачен")')
    pg.click('nav >> text=Касса')
    pg.wait_for_selector('td:has-text("Касса Браузер")')
    shot(pg, '10-cash')
    pg.locator('button:has-text("Отменить")').first.click()
    pg.fill('.modal textarea[name=reason]', 'неверный способ')
    pg.click('.modal button[type=submit]')
    pg.wait_for_selector('tr.cancelled')
    pg.click('nav >> text=Абонементы')
    pg.click('button:has-text("С долгом")')
    pg.wait_for_selector('td:has-text("Касса Браузер")')
    assert not pg.errors, pg.errors
