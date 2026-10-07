/**
 * api/diagnose.js — Vercel Serverless Function (Node).
 * Діагностика листя винограду: GPT-4o Vision + системний промпт (docs/system_prompt.md).
 *
 * Вхід: POST { "image_base64": "<data URL base64 JPEG>", "grape_variety": "...", "user_notes": "...", "few_shots": [cards...] }
 * Вихід: { "card": {діагностична картка за schema/diagnostic_card.schema.json}, "model": "..." }
 *
 * ENV: OPENAI_API_KEY (обов'язково у налаштуваннях Vercel; інші сумісні
 * провайдери: OPENAI_BASE_URL (за замовчуванням https://api.openai.com/v1)).
 */
const SYSTEM_PROMPT = require('./system_prompt.js');
const crypto = require('crypto');

module.exports = async (req, res) => {
  // CORS для викликів зі сторінок GitHub Pages
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  if (req.method === 'OPTIONS') return res.status(204).end();
  if (req.method !== 'POST') return res.status(405).json({ error: 'Тільки POST' });

  const { image_base64, grape_variety, user_notes, few_shots } = req.body || {};
  if (!image_base64) return res.status(400).json({ error: 'image_base64 обовʼязковий' });

  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey) return res.status(500).json({ error: 'OPENAI_API_KEY не налаштовано у Vercel' });

  const baseUrl = process.env.OPENAI_BASE_URL || 'https://api.openai.com/v1';
  const dataUrl = image_base64.startsWith('data:') ? image_base64 : `data:image/jpeg;base64,${image_base64}`;

  const fewShotText = Array.isArray(few_shots) && few_shots.length
    ? '\n\nПриклади збережених карток з бази (few-shot):\n' + few_shots.map(c => JSON.stringify(c)).join('\n')
    : '';

  const userContent = [
    { type: 'text', text: 'Проаналізуй фото листя винограду й сформуй картку діагностики валідним JSON.' },
    { type: 'image_url', image_url: { url: dataUrl } },
  ];
  if (grape_variety || user_notes) {
    userContent.push({ type: 'text', text: `Сорт: ${grape_variety || 'Невідомо'}. Спостереження користувача: ${user_notes || '—'}` });
  }

  try {
    const r = await fetch(`${baseUrl}/chat/completions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
      body: JSON.stringify({
        model: process.env.OPENAI_MODEL || 'gpt-4o',
        response_format: { type: 'json_object' },
        max_tokens: 2000,
        messages: [
          { role: 'system', content: SYSTEM_PROMPT + fewShotText },
          { role: 'user', content: userContent },
        ],
      }),
    });
    if (!r.ok) {
      const errText = await r.text();
      return res.status(r.status).json({ error: 'Помилка AI-провайдера', detail: errText.slice(0, 500) });
    }
    const data = await r.json();
    let card;
    try {
      card = JSON.parse(data.choices[0].message.content);
    } catch {
      return res.status(502).json({ error: 'Модель повернула невалідний JSON' });
    }
    // гарантуємо обов'язкові поля схеми
    card.card_id = card.card_id || `vgd-${crypto.randomUUID().slice(0, 8)}`;
    card.timestamp = card.timestamp || new Date().toISOString();
    card.verification_status = card.verification_status || 'ai_draft';
    return res.status(200).json({ card, model: data.model });
  } catch (e) {
    return res.status(500).json({ error: 'Внутрішня помилка', detail: String(e).slice(0, 300) });
  }
};
