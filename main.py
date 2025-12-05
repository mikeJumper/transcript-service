import os, json, tempfile
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from yt_dlp import YoutubeDL
from openai import OpenAI

app = FastAPI()

API_KEY = os.getenv("TRANSCRIPT_API_KEY", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
COOKIE_FILE = None
cookies_text = os.getenv("YTDLP_COOKIES", "").strip()
if cookies_text:
    import tempfile
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
    tmp.write(cookies_text.encode("utf-8"))
    tmp.flush()
    tmp.close()
    COOKIE_FILE = tmp.name

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

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
    sn = meta.get("snippet", {}) or {}
    parts = []
    if sn.get("title"): parts.append(sn["title"])
    if sn.get("description"): parts.append(sn["description"])
    tags = sn.get("tags") or []
    if isinstance(tags, list) and tags:
        parts.append(" ".join(tags))
    return " ".join(parts).replace("\n", " ").strip()

def transcribe_youtube_audio(url: str) -> str:
    if not client:
        raise RuntimeError("OPENAI_API_KEY not configured")
    with tempfile.TemporaryDirectory() as tmpdir:
        outtmpl = os.path.join(tmpdir, "audio.%(ext)s")
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "quiet": True,
            "noprogress": True,
            "cookiefile": os.getenv("YTDLP_COOKIES", "").strip(),  # ← NEW LINE
        }
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = ydl.prepare_filename(info)

        with open(filepath, "rb") as f:
            resp = client.audio.transcriptions.create(
                model="whisper-1",
                file=f
            )
        return resp.text.strip() if hasattr(resp, "text") else ""


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

    # Try real audio transcription first
    transcript = ""
    error = None
    source = "none"

    try:
        if req.platform.lower() == "youtube":
            transcript = transcribe_youtube_audio(req.url)
            source = "whisper"
    except Exception as e:
        error = f"whisper_error: {e!s}"

    # Fallback to snippet if audio failed or is empty
    if not transcript:
        snippet_text = extract_snippet_text(req.metadata_blob)
        if snippet_text:
            transcript = snippet_text
            source = "snippet_fallback"
            if not error:
                error = "audio_empty_or_failed"
        else:
            source = "none"
            if not error:
                error = "empty_snippet_and_audio"

    return TranscriptResponse(
        transcript=transcript,
        language="unknown",
        source=source,
        error=error
    )


