"""Тести FastAPI-бекенду (мок AI-провайдера, без мережі). Запуск: python -m pytest tests/ -q"""
import json, os, sys, uuid
from unittest.mock import patch, AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("OPENAI_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402
import app.main as m  # noqa: E402
from app.prompt import SYSTEM_PROMPT  # noqa: E402

client = TestClient(m.app)


def test_root_and_health():
    assert client.get("/").json()["status"] == "ok"
    assert client.get("/health").json()["openai_key_configured"] is False

def test_diagnose_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    r = client.post(
        "/api/diagnose",
        json={"image_base64": "data:image/jpeg;base64,QUJD"},
    )
    assert r.status_code == 503
    assert r.json()["detail"] == "Не вдалося завершити аналіз фото"




def test_diagnose_with_mock_model():
    card = json.load(open("schema/few_shots/card_mildew_chardonnay.json", encoding="utf-8"))
    os.environ["OPENAI_API_KEY"] = "test-key"
    fake = {"choices": [{"message": {"content": json.dumps({**card, "verification_status": "ai_draft"}, ensure_ascii=False)}}], "model": "gpt-4o-mock"}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return fake

    with patch.object(m.httpx.AsyncClient, "post", new=AsyncMock(return_value=FakeResp())) as mp:
        r = client.post("/api/diagnose", json={
            "image_base64": "data:image/jpeg;base64,QUJD",
            "grape_variety": "Шардоне",
            "user_notes": "після дощу",
            "few_shots": [{"card_id": "x"}],
        })
        b = r.json()
        assert b["card"]["verification_status"] == "ai_draft"
        sent = mp.call_args.kwargs["json"]
        assert SYSTEM_PROMPT[:40] in sent["messages"][0]["content"]
       assert SYSTEM_PROMPT[:40] in sent["messages"][0]["content"]
assert "Приклади збережених карток" not in sent["messages"][0]["content"]
assert '"card_id": "x"' not in sent["messages"][0]["content"]

    os.environ.pop("OPENAI_API_KEY", None)


def test_cors_preflight():
    r = client.options("/api/diagnose", headers={"Origin": "https://ismi9.github.io", "Access-Control-Request-Method": "POST"})
    assert r.status_code == 200
