"""Afterglow incident intelligence API. Hindsight is the persistent memory layer."""
from __future__ import annotations

import os
import logging
import hmac
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("afterglow")
ROOT = Path(__file__).parent
app = FastAPI(
    title="Afterglow",
    description="Incident response that learns from every postmortem",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    incident: str = "active-incident"


class ResolveRequest(BaseModel):
    incident_id: str
    summary: str = Field(min_length=5, max_length=5000)
    service: str = "unknown"


@lru_cache(maxsize=1)
def hindsight_client():
    """Create the official Hindsight client only when configured."""
    try:
        from hindsight_client import Hindsight
    except ImportError as exc:
        raise RuntimeError("Install dependencies with `pip install -r requirements.txt`.") from exc
    url = os.getenv("HINDSIGHT_API_URL", "https://api.hindsight.vectorize.io")
    key = os.getenv("HINDSIGHT_API_KEY")
    client = Hindsight(base_url=url, api_key=key) if key else Hindsight(base_url=url)
    # Create the bank once per process. Existing banks return a conflict and are ready.
    try:
        client.create_bank(
            bank_id=bank_id(),
            name="Northstar On-call",
            mission="Remember incident symptoms, mitigations, outcomes, and on-call preferences to help engineers respond safely.",
        )
    except Exception as exc:
        logger.debug("Hindsight bank create skipped: %s", type(exc).__name__)
    return client


def bank_id() -> str:
    return os.getenv("HINDSIGHT_BANK_ID", "northstar-oncall")


def require_access(x_afterglow_key: str = Header(default="")) -> None:
    expected = os.getenv("AFTERGLOW_ACCESS_KEY", "")
    if expected and not hmac.compare_digest(x_afterglow_key, expected):
        raise HTTPException(status_code=401, detail="Enter the workspace access key to use the live assistant.")


def memories_as_text(response: Any) -> list[str]:
    return [str(item.text) for item in getattr(response, "results", []) if getattr(item, "text", None)]


def groq_answer(question: str, memories: list[str], incident: str) -> str:
    """Use Groq if configured; the UI has an offline scripted demo otherwise."""
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY is not set")
    from groq import Groq
    client = Groq(api_key=key)
    context = "\n".join(f"- {m}" for m in memories) or "No matching memories were found."
    response = client.chat.completions.create(
        model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        temperature=0.2,
        messages=[
            {"role": "system", "content": (
                "You are Afterglow, a careful SRE incident response assistant. "
                "Use recalled Hindsight memories as evidence, cite incident IDs when present, "
                "and recommend one reversible first step. Never claim an action was executed. "
                "Say when memory does not support a conclusion. Keep the answer under 130 words."
            )},
            {"role": "user", "content": f"Active incident: {incident}\nQuestion: {question}\n\nRecalled team memories:\n{context}"},
        ],
    )
    return response.choices[0].message.content or "I could not produce a response from the recalled context."


@app.get("/")
def index():
    return FileResponse(ROOT / "index.html")


@app.get("/styles.css")
def stylesheet():
    return FileResponse(ROOT / "styles.css", media_type="text/css")


@app.get("/app.js")
def javascript():
    return FileResponse(ROOT / "app.js", media_type="application/javascript")


@app.get("/api/status")
def status():
    hindsight_ready = bool(os.getenv("HINDSIGHT_API_KEY"))
    groq_ready = bool(os.getenv("GROQ_API_KEY"))
    return {
        "hindsight_configured": hindsight_ready,
        "groq_configured": groq_ready,
        "access_required": bool(os.getenv("AFTERGLOW_ACCESS_KEY")),
        "bank_id": bank_id(),
        "mode": "connected" if hindsight_ready and groq_ready else "demo",
    }


@app.get("/healthz")
def health():
    return {"ok": True, "service": "afterglow"}


@app.post("/api/chat", dependencies=[Depends(require_access)])
def chat(body: ChatRequest):
    try:
        client = hindsight_client()
        recalled = client.recall(bank_id=bank_id(), query=body.message, budget="mid", max_tokens=1800)
        texts = memories_as_text(recalled)
        answer = groq_answer(body.message, texts, body.incident)
        return {"answer": answer, "cite": f"{len(texts)} Hindsight memories · {bank_id()}", "memory_count": len(texts)}
    except Exception as exc:
        logger.exception("Memory assistant request failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="The memory assistant is temporarily unavailable. Check service configuration and logs.") from exc


@app.get("/api/memories", dependencies=[Depends(require_access)])
def list_memories():
    """Return real bank memories for the connected dashboard."""
    try:
        response = hindsight_client().list_memories(bank_id=bank_id(), limit=25, offset=0)
        items = getattr(response, "items", None) or getattr(response, "memories", None) or getattr(response, "results", None) or []
        return {"bank_id": bank_id(), "memories": [
            {
                "title": str(getattr(item, "fact_type", None) or getattr(item, "type", "team memory")).replace("_", " ").title(),
                "text": str(getattr(item, "text", "")),
                "source": str(getattr(item, "created_at", "Hindsight memory bank")),
                "icon": "◈",
                "tags": [str(getattr(item, "type", "memory"))],
            }
            for item in items if getattr(item, "text", None)
        ]}
    except Exception as exc:
        logger.exception("Memory listing failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Could not load memories from Hindsight. Check service configuration and logs.") from exc


@app.post("/api/resolve", dependencies=[Depends(require_access)])
def resolve(body: ResolveRequest):
    """Retain the resolved incident so a future incident can reuse its learning."""
    content = f"Resolved incident {body.incident_id} for {body.service}: {body.summary}"
    try:
        client = hindsight_client()
        client.retain(bank_id=bank_id(), content=content, context="incident postmortem", metadata={"incident_id": body.incident_id, "service": body.service, "source": "postmortem"})
        return {"ok": True, "retained": True, "bank_id": bank_id(), "incident_id": body.incident_id}
    except Exception as exc:
        logger.exception("Incident memory retention failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Could not save this postmortem to Hindsight. Check service configuration and logs.") from exc
