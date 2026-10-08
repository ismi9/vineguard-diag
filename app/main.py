"""VineGuard Diag: діагностика фото та Telegram-вебхук для Vercel."""

import base64
import hmac
import json
import os
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.prompt import SYSTEM_PROMPT


app = FastAPI(title="VineGuard Diag", version="1.1.0")

# Залишаємо сумісність із поточним вебдемо.
# Перед ширшим запуском слід обмежити дозволені адреси сайту.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


class DiagnoseRequest(BaseModel):
    image_base64: str = Field(..., description="data URL або base64 фото")
    grape_variety: str | None = "Невідомо"
    user_notes: str | None = None
    few_shots: list[dict] | None = None


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Не налаштовано {name}")
    return value


@app.get("/")
def read_root():
    return {"service": "VineGuard Diag", "status": "ok", "docs": "/docs"}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "openai_key_configured": bool(os.environ.get("OPENAI_API_KEY")),
    }


async def call_vision_model(payload: DiagnoseRequest) -> dict:
    """Повертає попередній результат OpenAI-сумісного Vision API."""
    api_key = required_env("OPENAI_API_KEY")
    base_url = (
        os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    ).rstrip("/")
    model = os.environ.get("OPENAI_MODEL") or "gpt-4o"

    data_url = payload.image_base64
    if not data_url.startswith("data:"):
        data_url = f"data:image/jpeg;base64,{data_url}"

    # Не передаємо надіслані браузером few_shots як «підтверджену базу»:
    # браузер міг змінити їхній вміст або статус.
    user_content = [
        {
            "type": "text",
            "text": (
                "Проаналізуй фото листя винограду й сформуй "
                "попередню картку діагностики валідним JSON. "
                "Не вважай діагноз підтвердженим користувачем."
            ),
        },
        {"type": "image_url", "image_url": {"url": data_url}},
        {
            "type": "text",
            "text": (
                f"Сорт: {payload.grape_variety or 'Невідомо'}. "
                f"Спостереження користувача: {payload.user_notes or '—'}"
            ),
        },
    ]

    body = {
        "model": model,
        "response_format": {"type": "json_object"},
        "max_tokens": 2000,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    }

    # Менше за maxDuration=60 у vercel.json: залишаємо час на
    # отримання фото, запис у базу й відповідь Telegram.
    async with httpx.AsyncClient(timeout=32) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=body,
        )
        response.raise_for_status()
        result = response.json()

    card = json.loads(result["choices"][0]["message"]["content"])
    if not isinstance(card, dict):
        raise ValueError("AI не повернув об'єкт картки")
    return card


def normalize_card(card: dict, payload: DiagnoseRequest) -> dict:
    """Готує чернетку; AI не може встановити статус підтвердження."""
    if not isinstance(card, dict):
        raise ValueError("Некоректна картка")

    card["card_id"] = f"vgd-{uuid.uuid4().hex}"
    card["timestamp"] = datetime.now(timezone.utc).isoformat()
    card["grape_variety"] = payload.grape_variety or "Невідомо"
    card["verification_status"] = "ai_draft"

    if not isinstance(card.get("visual_symptoms"), dict):
        card["visual_symptoms"] = {}
    for field in (
        "chlorosis",
        "necrosis",
        "spots_and_plaque",
        "leaf_deformation",
    ):
        card["visual_symptoms"].setdefault(field, "Не визначено")

    if not isinstance(card.get("diagnosis"), dict):
        card["diagnosis"] = {}
    for field in ("diseases", "nutrient_deficiencies"):
        if not isinstance(card["diagnosis"].get(field), list):
            card["diagnosis"][field] = []

    if not isinstance(card.get("recommendations"), dict):
        card["recommendations"] = {}
    for field in (
        "agrotechnical",
        "chemical_or_biological_treatment",
        "fertilization",
    ):
        if not isinstance(card["recommendations"].get(field), list):
            card["recommendations"][field] = []

    if payload.user_notes:
        card["user_notes"] = payload.user_notes
    return card


@app.post("/api/diagnose")
async def diagnose(payload: DiagnoseRequest):
    try:
        card = normalize_card(await call_vision_model(payload), payload)
        return {"card": card}
    except (RuntimeError, httpx.HTTPError, ValueError, KeyError, TypeError):
        # Не віддаємо браузеру відповідь AI-провайдера чи секрети.
        raise HTTPException(
            status_code=503,
            detail="Не вдалося завершити аналіз фото",
        )


def supabase_headers(prefer: str | None = None) -> dict[str, str]:
    key = required_env("SUPABASE_SERVICE_ROLE_KEY")
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def cards_url() -> str:
    return (
        required_env("SUPABASE_URL").rstrip("/")
        + "/rest/v1/diagnostic_cards"
    )


async def card_already_exists(card_id: str) -> bool:
    """Не запускаємо повторний аналіз уже збереженого Telegram update."""
    async with httpx.AsyncClient(timeout=6) as client:
        response = await client.get(
            cards_url(),
            headers=supabase_headers(),
            params={"select": "card_id", "card_id": f"eq.{card_id}"},
        )
        response.raise_for_status()
        return bool(response.json())


async def download_telegram_photo(file_id: str) -> str:
    token = required_env("TELEGRAM_BOT_TOKEN")

    async with httpx.AsyncClient(timeout=8) as client:
        info = await client.get(
            f"https://api.telegram.org/bot{token}/getFile",
            params={"file_id": file_id},
        )
        info.raise_for_status()
        body = info.json()
        if not body.get("ok"):
            raise ValueError("Telegram не повернув фото")

        file_path = body["result"]["file_path"]
        photo = await client.get(
            f"https://api.telegram.org/file/bot{token}/{file_path}"
        )
        photo.raise_for_status()

    # Обмежуємо розмір перед кодуванням у base64.
    if len(photo.content) > 8 * 1024 * 1024:
        raise ValueError("Фото завелике")

    return base64.b64encode(photo.content).decode("ascii")


async def save_telegram_card(card: dict, update_id: int) -> bool:
    """Повертає False, якщо запис цього update_id уже існує."""
    async with httpx.AsyncClient(timeout=6) as client:
        response = await client.post(
            cards_url(),
            headers=supabase_headers(
                "resolution=ignore-duplicates,return=representation"
            ),
            params={"on_conflict": "card_id"},
            json={
                "card_id": card["card_id"],
                "owner_id": required_env("SUPABASE_OWNER_USER_ID"),
                "telegram_update_id": update_id,
                "card": card,
            },
        )
        response.raise_for_status()
        return bool(response.json())


async def notify_telegram(chat_id: int) -> None:
    """Сповіщення не повинне скасувати вже збережену картку."""
    token = required_env("TELEGRAM_BOT_TOKEN")
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": (
                        "Фото отримано. Створено чернетку картки VineGuard. "
                        "Діагноз ще не підтверджено."
                    ),
                },
            )
    except httpx.HTTPError:
        pass


@app.post("/api/telegram")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
    allowed_chat = os.environ.get("ALLOWED_TELEGRAM_CHAT_ID")

    if not secret or not allowed_chat:
        raise HTTPException(status_code=503, detail="Вебхук не налаштовано")

    if not x_telegram_bot_api_secret_token or not hmac.compare_digest(
        x_telegram_bot_api_secret_token, secret
    ):
        raise HTTPException(status_code=403, detail="Доступ заборонено")

    try:
        update = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Некоректний запит")

    if not isinstance(update, dict):
        raise HTTPException(status_code=400, detail="Некоректний запит")

    message = update.get("message") or {}
    chat = message.get("chat") or {}

    # Тільки особистий чат дозволеного власника.
    if (
        chat.get("type") != "private"
        or str(chat.get("id")) != allowed_chat
        or str((message.get("from") or {}).get("id")) != allowed_chat
    ):
        return {"ok": True}

    photos = message.get("photo") or []
    if not photos:
        return {"ok": True}

    update_id = update.get("update_id")
    if not isinstance(update_id, int):
        raise HTTPException(status_code=400, detail="Немає update_id")

    card_id = f"tg-{update_id}"

    try:
        if await card_already_exists(card_id):
            return {"ok": True, "duplicate": True}

        payload = DiagnoseRequest(
            image_base64=await download_telegram_photo(
                photos[-1]["file_id"]
            ),
            grape_variety="Невідомо",
            user_notes=message.get("caption") or None,
        )
        card = normalize_card(await call_vision_model(payload), payload)
        card["card_id"] = card_id

        inserted = await save_telegram_card(card, update_id)
    except (
        RuntimeError,
        httpx.HTTPError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ):
        # Telegram може повторити невдале повідомлення; секрети не розкриваємо.
        raise HTTPException(
            status_code=503,
            detail="Обробка фото не завершилася",
        )

    if inserted:
        await notify_telegram(chat["id"])

    return {"ok": True, "saved": inserted}
