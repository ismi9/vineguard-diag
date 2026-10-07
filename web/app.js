'use strict';
/**
 * VineGuard Diag — клієнтська логіка.
 * Mobile-first: ручна кнопка «Сканувати» (без автозйомки), фолбек камери → файл.
 * Режими: офлайн-демо (few-shot картки) або AI через endpoint (api/diagnose.js на Vercel).
 * База карток: localStorage (MVP), статуси ai_draft → user_edited → confirmed_by_user.
 */
(function () {
  const $ = (id) => document.getElementById(id);
  const DB_KEY = 'vineguard-diag-cards-v1';
  let currentCard = null;

  // ---------- База карток (localStorage) ----------
  function loadDb() { try { return JSON.parse(localStorage.getItem(DB_KEY)) || []; } catch { return []; } }
  function saveDb(db) { localStorage.setItem(DB_KEY, JSON.stringify(db)); renderDb(); }
  window.save_card_to_database = function (card) { // інтеграційна точка VineMind AI
    const db = loadDb();
    db.unshift(card);
    saveDb(db);
    return { ok: true, card_id: card.card_id, count: db.length };
  };

  // ---------- Фото: ручна кнопка ----------
  $('btn-scan').addEventListener('click', () => $('file-input').click());
  $('btn-retake').addEventListener('click', () => { $('photo-preview').hidden = true; $('file-input').click(); });
  $('file-input').addEventListener('change', (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      $('photo-img').src = reader.result;
      $('photo-preview').hidden = false;
      $('step-diag').hidden = false;
      setStatus('');
    };
    reader.readAsDataURL(file); // камера через capture=environment; фолбек — галерея
  });

  // ---------- Статус ----------
  function setStatus(text, err) {
    const el = $('status');
    el.hidden = !text && !err;
    el.textContent = text || err || '';
    el.className = 'status' + (err ? ' err' : '');
  }

  // ---------- Рендер картки ----------
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  function renderCard(card) {
    currentCard = card;
    const dis = card.diagnosis || {};
    const rows = [];
    (dis.diseases || []).forEach((d) => rows.push(`<div class="diag-item"><span>${esc(d.name)}<div class="stage">${esc(d.stage || '')}</div></span><span class="conf ${d.confidence_score < 0.7 ? 'warn' : ''}">${Math.round((d.confidence_score || 0) * 100)}%</span></div>`));
    (dis.nutrient_deficiencies || []).forEach((d) => rows.push(`<div class="diag-item"><span>${esc(d.element)}<div class="stage">${esc(d.severity || '')}</div></span><span class="conf ${d.confidence_score < 0.7 ? 'warn' : ''}">${Math.round((d.confidence_score || 0) * 100)}%</span></div>`));
    if (!rows.length) rows.push('<div class="diag-item"><span>Патологій не виявлено</span></div>');
    const rec = card.recommendations || {};
    const list = (arr) => arr && arr.length ? `<ul>${arr.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : '<div class="stage">—</div>';
    $('card-view').innerHTML = `
      <div class="diag-block"><b>${esc(card.grape_variety || 'Невідомо')}</b> · ${esc((card.timestamp || '').slice(0, 10))}
      <span class="status-tag">${esc(card.verification_status)}</span></div>
      <div class="diag-block">${rows.join('')}</div>
      <div class="diag-block"><b>Агротехніка</b>${list(rec.agrotechnical)}
      <b>Обробка</b>${list(rec.chemical_or_biological_treatment)}
      <b>Підживлення</b>${list(rec.fertilization)}</div>
      <div class="hint">Дотримуйтесь інструкцій виробників ЗЗР, строків очікування до збору врожаю та використовуйте ЗІЗ.</div>`;
    $('step-card').hidden = false;
    $('card-json').value = JSON.stringify(card, null, 2);
    $('step-card').scrollIntoView({ behavior: 'smooth' });
  }

  // ---------- Аналіз ----------
  $('btn-analyze').addEventListener('click', async () => {
    const url = $('endpoint').value.trim();
    if (!url) { setStatus('Вкажіть endpoint або скористайтесь демо.', true); return; }
    const img = $('photo-img').src;
    if (!img) { setStatus('Спершу зробіть фото листка.', true); return; }
    setStatus('Аналізую фото…');
    try {
      const r = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image_base64: img,
          grape_variety: $('variety').value.trim() || 'Невідомо',
          user_notes: $('notes').value.trim(),
          few_shots: window.FEW_SHOTS.slice(0, 3),
        }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error + (data.detail ? ': ' + data.detail : ''));
      setStatus('Готово (модель: ' + (data.model || 'ai') + '). Картка — чернетка; скоригуйте за потреби.');
      renderCard(data.card);
    } catch (e) {
      setStatus('Помилка: ' + e.message, true);
    }
  });

  // ---------- Демо (офлайн): обертає few-shot картку ----------
  $('btn-demo').addEventListener('click', () => {
    const pool = window.FEW_SHOTS;
    const base = JSON.parse(JSON.stringify(pool[Math.floor(Math.random() * pool.length)]));
    base.card_id = 'demo-' + Date.now().toString(36);
    base.timestamp = new Date().toISOString();
    base.grape_variety = $('variety').value.trim() || base.grape_variety;
    if ($('notes').value.trim()) base.user_notes = $('notes').value.trim();
    renderCard(base);
    setStatus('Демо-режим (без AI): показано приклад картки зі збереженої бази. Підключіть endpoint для реального аналізу.');
  });

  // ---------- Корекція й збереження ----------
  $('btn-edit-json').addEventListener('click', () => {
    const ta = $('card-json');
    ta.hidden = !ta.hidden;
    if (!ta.hidden) ta.scrollIntoView({ behavior: 'smooth' });
  });
  $('card-json').addEventListener('change', () => {
    try {
      currentCard = JSON.parse($('card-json').value);
      currentCard.verification_status = 'user_edited';
      renderCard(currentCard);
    } catch { setStatus('JSON невалідний', true); }
  });
  $('btn-user-edit').addEventListener('click', () => {
    if (currentCard) { currentCard.verification_status = 'user_edited'; renderCard(currentCard); }
  });
  $('btn-save').addEventListener('click', () => {
    if (!currentCard) return;
    const reply = confirm('Зберегти цю картку до бази діагностики для покращення майбутнього розпізнавання?');
    if (!reply) return;
    currentCard.verification_status = currentCard.verification_status === 'user_edited' ? 'user_edited' : 'confirmed_by_user';
    const res = save_card_to_database(currentCard);
    setStatus('Збережено: ' + res.card_id + ' (усього в базі: ' + res.count + ')');
  });

  // ---------- База ----------
  function renderDb() {
    const db = loadDb();
    $('db-count').textContent = db.length;
    $('db-view').innerHTML = db.length
      ? db.map((c) => {
          const names = ((c.diagnosis && (c.diagnosis.diseases || []).map((d) => d.name).concat((c.diagnosis.nutrient_deficiencies || []).map((d) => d.element))) || []).join(', ') || 'без патологій';
          return `<div class="db-item"><b>${esc(c.grape_variety || 'Невідомо')}</b> · ${esc(names)}<span class="status-tag">${esc(c.verification_status)}</span><div class="stage">${esc((c.timestamp || '').slice(0, 16).replace('T', ' '))} · id: ${esc(c.card_id)}</div></div>`;
        }).join('')
      : '<p class="hint">Поки що порожньо. Проаналізуйте фото та збережіть картку.</p>';
  }
  $('btn-export').addEventListener('click', () => {
    const blob = new Blob([JSON.stringify(loadDb(), null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'vineguard-diag-cards.json';
    a.click();
  });
  $('btn-clear').addEventListener('click', () => {
    if (confirm('Очистити локальну базу карток?')) saveDb([]);
  });

  renderDb();
})();
