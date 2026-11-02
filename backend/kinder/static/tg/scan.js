'use strict';
/* Reception QR scanner as a Telegram Mini App. Auth = signed Telegram initData (staff only). */
(function () {
  const tg = window.Telegram && window.Telegram.WebApp;
  const $ = (id) => document.getElementById(id);
  const ERR = {
    unauthorized: 'Нет доступа. Войдите в бота своим логином сотрудника.', forbidden: 'Сканер доступен только сотрудникам ресепшена.',
    qr_unknown: 'QR-код не найден', qr_already_used: 'Этот QR-код уже использован', qr_expired: 'QR-код истёк — попросите клиента обновить',
    invalid_qr: 'Это не QR-код Kinder Spa', qr_other_client: 'QR-код другого клиента', no_visits_left: 'Посещения закончились',
    subscription_frozen: 'Абонемент заморожен', subscription_expired: 'Срок абонемента истёк', subscription_closed: 'Абонемент закрыт',
    subscription_not_started: 'Абонемент ещё не начался', subscription_for_other_child: 'Абонемент оформлен на другого ребёнка',
    service_not_in_subscription: 'Услуга не входит в абонемент', network: 'Нет связи с сервером', internal_error: 'Ошибка сервера',
  };
  const errText = (e) => ERR[e && e.code] || (e && e.code) || 'Ошибка';
  let specialists = [];
  let currentCode = null;

  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (v === null || v === undefined || v === false) return;
      if (k === 'class') el.className = v; else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else if (k === 'value') el.value = v; else el.setAttribute(k, v === true ? '' : v);
    });
    kids.flat(Infinity).forEach((c) => { if (c !== null && c !== undefined && c !== false) el.append(c instanceof Node ? c : document.createTextNode(String(c))); });
    return el;
  }
  function msg(text, kind) { const m = $('msg'); m.textContent = text || ''; m.className = 'msg' + (kind ? ' ' + kind : ''); }
  function haptic(kind) { try { tg.HapticFeedback.notificationOccurred(kind); } catch (_) { /* not in Telegram */ } }
  const fmtDate = (s) => (s ? new Date(s + 'T00:00:00').toLocaleDateString('ru-RU') : '—');
  const fmtTime = (s) => new Date(s).toLocaleTimeString('ru-RU', { timeZone: 'Asia/Tashkent', hour: '2-digit', minute: '2-digit' });

  async function api(method, path, body) {
    let res;
    try {
      res = await fetch('/api' + path, { method, headers: { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': tg ? tg.initData : '' },
        body: body === undefined ? undefined : JSON.stringify(body) });
    } catch (_) { throw { code: 'network' }; }
    let data = null; try { data = await res.json(); } catch (_) { /* empty */ }
    if (!res.ok) throw { code: (data && data.error) || 'internal_error', detail: data && data.detail };
    return data;
  }

  function confirmBox(text) {
    return new Promise((resolve) => { if (tg && tg.showConfirm) tg.showConfirm(text, resolve); else resolve(window.confirm(text)); });
  }

  async function lookup(code) {
    currentCode = code.trim();
    msg('Ищу клиента…');
    $('result').replaceChildren();
    try {
      const r = await api('POST', '/qr/lookup', { code: currentCode });
      msg(''); haptic('success'); showClient(r.client);
    } catch (e) { msg(errText(e), 'bad'); haptic('error'); }
  }

  function showClient(c) {
    const kids = c.children.filter((k) => !k.archived);
    const subs = c.subscriptions.filter((s) => s.state === 'active');
    const cards = subs.map((s) => {
      const usable = s.items.filter((i) => i.remaining > 0);
      const svc = h('select', {}, usable.map((i) => h('option', { value: i.service_id }, `${i.name_ru} (осталось ${i.remaining})`)));
      const spec = h('select', {});
      const fill = () => spec.replaceChildren(h('option', { value: '' }, '— специалист не указан —'),
        ...specialists.filter((p) => p.service_ids.includes(Number(svc.value))).map((p) => h('option', { value: p.id }, p.full_name)));
      svc.addEventListener('change', fill); fill();
      const child = s.child_id ? null : (kids.length > 1 ? h('select', {}, kids.map((k) => h('option', { value: k.id }, k.full_name))) : null);
      const btn = h('button', { class: 'big', disabled: !usable.length }, usable.length ? 'Списать посещение' : 'Посещения закончились');
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        const body = { code: currentCode, subscription_id: s.id, service_id: Number(svc.value),
          child_id: child ? Number(child.value) : null, specialist_id: spec.value ? Number(spec.value) : null };
        try {
          let r;
          try { r = await api('POST', '/qr/redeem', body); } catch (e) {
            if (e.code !== 'already_visited_today') throw e;
            if (!(await confirmBox('Сегодня уже есть такое посещение. Списать ещё одно?'))) { btn.disabled = false; return; }
            r = await api('POST', '/qr/redeem', Object.assign(body, { force: true }));
          }
          haptic('success'); done(c, svc.selectedOptions[0].textContent.split(' (')[0], r.remaining);
        } catch (e) { msg(errText(e), 'bad'); haptic('error'); btn.disabled = false; }
      });
      return h('div', { class: 'card' },
        h('b', {}, s.name), s.child_name ? h('span', { class: 'muted' }, ' · ', s.child_name) : null,
        h('div', { class: 'muted' }, 'до ', fmtDate(s.ends_on)),
        h('div', { class: 'items' }, s.items.map((i) => h('span', { class: 'item' }, i.name_ru, ': ', h('b', {}, i.remaining), ' / ', i.quota))),
        usable.length ? [h('label', {}, 'Услуга', svc), child ? h('label', {}, 'Ребёнок', child) : null, h('label', {}, 'Специалист', spec)] : null,
        h('div', { class: 'row' }, btn));
    });
    $('result').replaceChildren(
      h('div', { class: 'card' }, h('h3', {}, c.full_name), kids.length ? h('div', { class: 'muted' }, 'Дети: ', kids.map((k) => k.full_name).join(', ')) : null,
        c.phone ? h('div', { class: 'muted' }, c.phone) : null),
      ...(cards.length ? cards : [h('div', { class: 'card muted' }, 'Нет активных абонементов. Оформите абонемент в панели администратора.')]),
      h('div', { class: 'row' }, h('button', { class: 'secondary', onclick: reset }, 'Отмена')));
    $('scan-box').classList.add('hidden');
  }

  function done(c, service, left) {
    msg('');
    $('result').replaceChildren(h('div', { class: 'card done' }, h('div', { class: 'icon' }, '✅'), h('div', {}, 'Посещение списано'),
      h('div', {}, c.full_name, ' · ', service), h('div', { class: 'left' }, 'Осталось: ', left),
      left <= 1 ? h('div', { class: 'muted' }, left === 0 ? 'Это было последнее посещение — предложите продлить абонемент.' : 'Осталось одно посещение.') : null),
    h('div', { class: 'row' }, h('button', { class: 'big', onclick: () => { reset(); scan(); } }, '📷 Следующий клиент')));
    loadToday();
  }

  function reset() { currentCode = null; $('result').replaceChildren(); $('scan-box').classList.remove('hidden'); msg(''); }

  function scan() {
    if (tg && tg.showScanQrPopup && tg.isVersionAtLeast && tg.isVersionAtLeast('6.4')) {
      tg.showScanQrPopup({ text: 'Наведите камеру на QR-код клиента' }, (text) => {
        if (text && text.startsWith('KSPA1:')) { lookup(text); return true; }
        return false; // keep scanning, ignore foreign codes
      });
    } else {
      $('manual').open = true; $('manual-code').focus();
      msg('В этой версии Telegram сканер недоступен — обновите Telegram или введите код вручную.', 'bad');
    }
  }

  async function loadToday() {
    try {
      const rows = await api('GET', '/visits');
      $('today-list').replaceChildren(...(rows.length ? rows.slice(0, 30).map((v) => h('div', { class: 'visit' + (v.cancelled_at ? ' cancelled' : '') },
        h('span', {}, fmtTime(v.visited_at), ' ', v.client_name, v.child_name ? ` (${v.child_name})` : ''), h('span', { class: 'muted' }, v.service_name)))
        : [h('div', { class: 'muted' }, 'Сегодня посещений ещё нет')]));
    } catch (e) { $('today-list').textContent = errText(e); }
  }

  async function start() {
    if (!tg || !tg.initData) {
      $('scan-box').classList.add('hidden'); $('today').classList.add('hidden');
      msg('Откройте сканер из Telegram-бота Kinder Spa (кнопка «📷 Сканировать QR»).', 'bad');
      return;
    }
    tg.ready(); tg.expand();
    try { await api('GET', '/me'); } catch (e) {
      $('scan-box').classList.add('hidden'); $('today').classList.add('hidden'); msg(errText(e), 'bad'); return;
    }
    try { specialists = (await api('GET', '/specialists')).filter((p) => p.active); } catch (_) { specialists = []; }
    $('scan-btn').addEventListener('click', scan);
    $('manual-form').addEventListener('submit', (e) => { e.preventDefault(); if ($('manual-code').value.trim()) lookup($('manual-code').value); });
    loadToday();
    scan();
  }
  start();
}());
