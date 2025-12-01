import os, json
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI()

API_KEY = os.getenv("TRANSCRIPT_API_KEY", "").strip()

class TranscriptRequest(BaseModel):
    platform: str
    url: str
    metadata_blob: str | None = None

class TranscriptResponse(BaseModel):
    transcript: str
    language: str | None = "unknown"
    source: str
    error: str | None = None

def extract_snippet_text(blob: str | None) -> str:
    if not blob:
        return ""
    try:
        meta = json.loads(blob)
    except Exception:
        return ""
    sn = meta.get("snippet", {})
    parts = []
    if sn.get("title"): parts.append(sn["title"])
    if sn.get("description"): parts.append(sn["description"])
    tags = sn.get("tags") or []
    if isinstance(tags, list) and tags:
        parts.append(" ".join(tags))
    return " ".join(parts).replace("\n", " ").strip()

@app.post("/transcript", response_model=TranscriptResponse)
def get_transcript(
    req: TranscriptRequest,
    authorization: str = Header(default="")
):
    if not API_KEY:
        raise HTTPException(500, "Server API key not configured")

    prefix = "Bearer "
    if not authorization.startswith(prefix) or authorization[len(prefix):] != API_KEY:
        raise HTTPException(401, "Unauthorized")

    # v1: just reuse snippet logic (matches what Sheets does today)
    text = extract_snippet_text(req.metadata_blob)
    return TranscriptResponse(
        transcript=text,
        language="unknown",
        source="snippet_fallback" if text else "none",
        error=None if text else "empty_snippet"
    )
