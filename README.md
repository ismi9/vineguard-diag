# VineGuard Diag v1.0.0

**AI-діагностика листя винограду: хвороби (мілдью, оїдіум, антракноз…) і дефіцити
елементів (N, K, Mg, Fe, P, B, Zn…) → структуровані картки → база діагностики.**

Проект створено за трьома файлами завдання (`docs/tz-source/`):
системний промпт агронома-фітопатолога (новий-2), інструкція інтеграції в бекенд
(новий-3) і правила безпеки/агрономічні стандарти (новий-4).

## Що вміє

• Діагностика фото листка через GPT-4o Vision з системним промптом
  (`docs/system_prompt.md` → `api/system_prompt.js`)
• Автогенерація структурованої картки за схемою
  (`schema/diagnostic_card.schema.json`): симптоми → діагноз з confidence →
  рекомендації (агротехніка / обробка / підживлення)
• Життєвий цикл картки: `ai_draft` → `user_edited` → `confirmed_by_user`
  (підтвердження перед збереженням, як у завданні)
• Few-shot картки (3 приклади: мілдью, дефіцит Mg, оїдіум+Fe) для підказки моделі
• Локальна база карток (localStorage MVP) + інтеграційна точка
  `save_card_to_database()` для бекенду VineMind AI
• Офлайн-демо без API-ключа: сторінка працює і показує приклади карток
• Mobile-first: <b>ручна кнопка «Сканувати»</b> (без автозйомки), фолбек
  камери → вибір файлу, повна робота на мобільному браузері

## Структура

```
app/main.py                FastAPI-бекенд (Vercel, Python): POST /api/diagnose
app/prompt.py              системний промпт (новий-2 + новий-4)
backend-node/              альтернативний Node-бекенд (web-standard export)
schema/diagnostic_card.schema.json   JSON Schema картки
schema/few_shots/          3 few-shot картки-приклади
web/                       статичне демо (GitHub Pages): index.html, app.js
docs/tz-source/            вихідні 3 файли завдання (архів, без змін)
docs/system_prompt.md      зібраний промпт (новий-2 + новий-4)
docs/INTEGRATION_ANALYSIS.md  аналіз інтеграції з наявними репозиторіями
```

## Запуск

### Демо (офлайн, без ключа)
GitHub Pages: https://ismi9.github.io/vineguard-diag/
або відкрити `web/index.html` локально.

### Реальний AI-аналіз
1. Розгорнути репозиторій на Vercel — FastAPI-застосунок підхоплюється
   автоматично (entrypoint `app/main.py`, інстанс `app`, за документацією
   Vercel «Deploy a FastAPI app»; maxDuration 60 с — у `vercel.json`).
2. В налаштуваннях Vercel задати <b>одну змінну оточення: `OPENAI_API_KEY`</b>
   (сумісні провайдери: додатково `OPENAI_BASE_URL`, `OPENAI_MODEL`).
3. Endpoint: `https://<проект>.vercel.app/api/diagnose` — вставити в поле
   «Endpoint сервера діагностики» в демо (перевірка: `…/health`).

### Локально (FastAPI)
```
pip install -r requirements.txt
uvicorn app.main:app --reload   # http://127.0.0.1:8000/docs
python -m pytest tests/ -q      # тести бекенду (мок AI)

## Безпека й чесність

Результати — ілюстративні й не замінюють лабораторний аналіз. Нагадування
ЗЗР/строків очікування/ЗІЗ — вбудовані в промпт і UI (новий-4). Дані карток
поки зберігаються локально в браузері; серверна база — етап інтеграції з
VineMind AI (див. `docs/INTEGRATION_ANALYSIS.md`).
