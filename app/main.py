"""VineGuard Diag — FastAPI backend for Vercel.

За документацією Vercel (Deploy a FastAPI app → Exporting the FastAPI
application): інстанс FastAPI з ім'ям `app` у підтримуваному entrypoint
(app/main.py) підхоплюється автоматично.

Контракт ідентичний Node-версії: POST /api/diagnose
  вхід:  { image_base64, grape_variety?, user_notes?, few_shots? }
  вихід: { card, model }  — картка за schema/diagnostic_card.schema.json

ENV (Vercel → Settings → Environment Variables):
  OPENAI_API_KEY   — обов'язково (одна змінна, сумісні провайдери також)
  OPENAI_BASE_URL  — опційно, за замовчуванням https://api.openai.com/v1
  OPENAI_MODEL     — опційно, за замовчуванням gpt-4o
"""

import json
import os
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.prompt import SYSTEM_PROMPT

app = FastAPI(title="VineGuard Diag", version="1.0.0")

# CORS: демо живе на GitHub Pages
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


class DiagnoseRequest(BaseModel):
    image_base64: str = Field(..., description="data URL або чистий base64 JPEG")
    grape_variety: str | None = "Невідомо"
    user_notes: str | None = None
    few_shots: list[dict] | None = None


@app.get("/")
def read_root():
    return {"service": "VineGuard Diag", "status": "ok", "docs": "/docs"}


@app.get("/health")
def health():
    has_key = bool(os.environ.get("OPENAI_API_KEY"))
    return {"status": "ok", "openai_key_configured": has_key}


async def call_vision_model(payload: DiagnoseRequest) -> dict:
    """Виклик OpenAI-сумісного Vision API → сировинна картка (може кинути HTTPStatusError)."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY не налаштовано у Vercel")
    base_url = (os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("OPENAI_MODEL") or "gpt-4o"

    data_url = payload.image_base64
    if not data_url.startswith("data:"):
        data_url = f"data:image/jpeg;base64,{data_url}"

    few_shot_text = ""
    if payload.few_shots:
        few_shot_text = (
            "\n\nПриклади збережених карток з бази (few-shot):\n"
            + "\n".join(json.dumps(c, ensure_ascii=False) for c in payload.few_shots[:3])
        )

    user_content = [
        {"type": "text", "text": "Проаналізуй фото листя винограду й сформуй картку діагностики валідним JSON."},
        {"type": "image_url", "image_url": {"url": data_url}},
        {"type": "text", "text": f"Сорт: {payload.grape_variety or 'Невідомо'}. Спостереження користувача: {payload.user_notes or '—'}"},
    ]

    body = {
        "model": model,
        "response_format": {"type": "json_object"},
        "max_tokens": 2000,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT + few_shot_text},
            {"role": "user", "content": user_content},
        ],
    }
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=body,
        )
        r.raise_for_status()
        data = r.json()
    return json.loads(data["choices"][0]["message"]["content"])


def normalize_card(card: dict, payload: DiagnoseRequest) -> dict:
    """Гарантує обов'язкові поля schema/diagnostic_card.schema.json."""
    card.setdefault("card_id", f"vgd-{uuid.uuid4().hex[:8]}")
    card.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    card.setdefault("grape_variety", payload.grape_variety or "Невідомо")
    card.setdefault("verification_status", "ai_draft")
    if payload.user_notes:
        card.setdefault("user_notes", payload.user_notes)
    return card


@app.post("/api/diagnose")
async def diagnose(payload: DiagnoseRequest):
    try:
        card = await call_vision_model(payload)
    except RuntimeError as e:  # відсутній ключ — конфігурація, не помилка клієнта
        return {"error": str(e)}
    except httpx.HTTPStatusError as e:
        detail = e.response.text[:500]
        return {"error": "Помилка AI-провайдера", "detail": detail}
    except json.JSONDecodeError:
        return {"error": "Модель повернула невалідний JSON"}
    except httpx.HTTPError as e:
        return {"error": "Мережева помилка", "detail": str(e)[:300]}

    card = normalize_card(card, payload)
    return {"card": card}
