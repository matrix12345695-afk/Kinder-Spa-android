"""Chromium acceptance for the synthetic, static Kinder Spa review page.

No real accounts, API, network services or PostgreSQL. The page must function
completely offline and clearly label every operation as a demo.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / 'preview' / 'index.html').resolve()


def main():
    text = PAGE.read_text(encoding='utf-8')
    if not all(mark in text for mark in (
        'Только вымышленные данные', 'Oʻzgarishlar serverda saqlanmaydi',
        'window.prompt', "const clients=[", "const bookings=[")):
        raise AssertionError('demo safety or sample state missing')
    if any(mark in text for mark in ('KINDER_DATABASE_URL', 'access_token', 'bot_token',
                                    'https://api.telegram.org', 'localStorage.setItem(')):
        raise AssertionError('preview must not contain production credentials or persistence')
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=['--disable-background-networking'])
        try:
            context = browser.new_context(viewport={'width': 1280, 'height': 840},
                                          service_workers='block')
            page = context.new_page()
            exceptions, network_requests = [], []
            page.on('pageerror', lambda error: exceptions.append(str(error)))
            page.on('request', lambda request: network_requests.append(request.url)
                    if request.url.startswith(('http:', 'https:', 'ws:', 'wss:')) else None)
            page.goto(PAGE.as_uri())
            expect(page.locator('#heading')).to_have_text('Обзор')
            expect(page.locator('.banner')).to_contain_text('ДЕМОНСТРАЦИЯ')
            page.locator('#uz').click()
            expect(page.locator('#heading')).to_have_text('Umumiy')
            expect(page.locator('html')).to_have_attribute('lang', 'uz')
            page.locator('[data-tab="subscriptions"]').click()
            expect(page.locator('#subscriptionCards .item')).to_have_count(3)
            expect(page.locator('#subscriptionCards')).to_contain_text('Basseyn')
            page.locator('#ru').click()
            page.locator('[data-tab="bookings"]').click()
            expect(page.locator('#bookingList')).to_contain_text('Сеанс сгорел')
            page.on('dialog', lambda dialog: dialog.accept('fixture operational reason'))
            page.get_by_role('button', name='Восстановить (демо)').click()
            expect(page.locator('#bookingList')).to_contain_text('Восстановлен')
            expect(page.locator('#message')).to_contain_text('Telegram ничего не отправлено')
            page.locator('[data-tab="audit"]').click()
            expect(page.locator('#auditList')).to_contain_text('Восстановлен тестовый сеанс')
            page.locator('[data-tab="clients"]').click()
            expect(page.locator('#clientCards .item')).to_have_count(3)
            page.set_viewport_size({'width': 390, 'height': 844})
            expect(page.locator('.menu')).to_be_visible()
            expect(page.locator('#clientCards .item')).to_have_count(3)
            assert not exceptions, exceptions
            assert not network_requests, network_requests
            context.close()
        finally:
            browser.close()
    print('PASS: Kinder Spa static RU/UZ preview, 5 tabs, mock restoration, mobile, no network')


if __name__ == '__main__':
    main()
