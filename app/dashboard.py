"""
dork local desktop studio - Flask backend
Full xAI API integration + OpenAI image generation & chat
Chat, Image, Video, Voice, Code, Collections, Artifacts, Skills
"""

import os
import json
import time
import uuid
import base64
import io
import urllib.request
import urllib.error
import urllib.parse
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from dotenv import dotenv_values, load_dotenv
from flask import (
    Flask, render_template, request, jsonify, Response,
    send_from_directory, stream_with_context
)

# Load .env from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
if os.environ.get("DORK_NO_ENV") != "1":
    load_dotenv(ENV_FILE)

# ── Directories ──────────────────────────────────────────────────────────────
USER_HOME = Path.home()
STATE_HOME = Path(os.environ.get("DORK_STATE_HOME", USER_HOME / ".dork-studio")).expanduser()
SETTINGS_DIR = STATE_HOME / "settings"
DATA_DIR = STATE_HOME / "media"
IMAGES_DIR = DATA_DIR / "Images"
VIDEOS_DIR = DATA_DIR / "Videos"
AUDIO_DIR = DATA_DIR / "Audio"
UPLOADS_DIR = DATA_DIR / "Uploads"
ARTIFACTS_DIR = DATA_DIR / "Artifacts"
SKILLS_DIR = DATA_DIR / "Skills"

ASSET_LIB_DIR = SETTINGS_DIR / "asset-library"

for d in [SETTINGS_DIR, IMAGES_DIR, VIDEOS_DIR, AUDIO_DIR, UPLOADS_DIR, ARTIFACTS_DIR, SKILLS_DIR, ASSET_LIB_DIR]:
    d.mkdir(parents=True, exist_ok=True, mode=0o700)

ASSET_LIB_INDEX = ASSET_LIB_DIR / "index.json"

# Existing app data and credentials are never imported automatically.
SETTINGS_FILE = SETTINGS_DIR / "settings.json"

# ── Flask App ────────────────────────────────────────────────────────────────
app = Flask(__name__,
            template_folder=str(Path(__file__).parent / "templates"),
            static_folder=str(Path(__file__).parent / "static"))
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100MB
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0  # No caching in dev


@app.before_request
def local_request_boundary():
    """Reject DNS rebinding and cross-site access to the local studio."""
    host = request.host.split(":", 1)[0].lower()
    if host not in {"127.0.0.1", "localhost"}:
        return jsonify({"error": "dork accepts local requests only"}), 403
    payload = request.get_json(silent=True)
    if isinstance(payload, dict) and "filename" in payload:
        filename = payload["filename"]
        if not isinstance(filename, str) or "/" in filename or "\\" in filename or filename in {".", ".."}:
            return jsonify({"error": "A local filename is required"}), 400
    origin = request.headers.get("Origin")
    if origin:
        parsed = urllib.parse.urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or parsed.netloc != request.host:
            return jsonify({"error": "Cross-site requests are blocked"}), 403


@app.after_request
def private_response_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    if request.path.startswith("/artifacts/"):
        response.headers["Content-Security-Policy"] = (
            "sandbox allow-scripts allow-modals; default-src 'none'; "
            "script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
            "img-src data: blob:; media-src data: blob:; connect-src 'none'"
        )
    return response

XAI_BASE = "https://api.x.ai/v1"
OPENAI_BASE = "https://api.openai.com/v1"
DEFAULT_IMAGE_MODEL = "grok-imagine-image-2.0"
DEFAULT_IMAGE_QUALITY = "low"
DEFAULT_IMAGE_RESOLUTION = "2k"
DEFAULT_IMAGE_ASPECT_RATIO = "auto"
DEFAULT_VIDEO_MODEL = "grok-imagine-video-1.5-lite"
DEFAULT_VIDEO_RESOLUTION = "720p"
DEFAULT_VIDEO_ASPECT_RATIO = "16:9"
DEFAULT_VIDEO_DURATION = 6
IMAGE_OUTPUT_COUNT_MAX = 10
IMAGE_EDIT_BATCH_MAX = 10
IMAGE_REFERENCE_MAX = 5
VIDEO_DURATION_MIN = 1
VIDEO_DURATION_MAX = 15

IMAGE_RESOLUTIONS = {"1k", "1.5k", "2k"}
IMAGE_QUALITIES = {"low", "medium", "auto"}
IMAGE_ASPECT_RATIOS = {"auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "2:1", "1:2", "19.5:9", "9:19.5", "20:9", "9:20", "21:9", "5:2"}
VIDEO_RESOLUTIONS = {"480p", "720p", "1080p"}
VIDEO_RESOLUTION_ORDER = ["480p", "720p", "1080p"]
VIDEO_ASPECT_RATIOS = {"1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"}
# Direct xAI global-endpoint prices, verified 2026-10-02. No Fal credentials
# or Fal endpoint IDs are used by this provider. Estimates are not invoices.
MEDIA_PRICING_DATE = "2026-10-02"
VIDEO_RATES = {
    "grok-imagine-video-1.5-lite": {"480p": 0.02, "720p": 0.03, "1080p": 0.14},
    "grok-imagine-video-1.5": {"480p": 0.08, "720p": 0.14, "1080p": 0.25},
    "grok-imagine-video": {"480p": 0.05, "720p": 0.07},
}
IMAGE_RATES = {
    "grok-imagine-image-2.0": {
        "low": {"1k": 0.04, "1.5k": 0.05, "2k": 0.06},
        "medium": {"1k": 0.06, "1.5k": 0.07, "2k": 0.08},
    },
    "grok-imagine-image-quality": {"1k": 0.05, "1.5k": 0.06, "2k": 0.07},
    "grok-imagine-image": {"1k": 0.02, "2k": 0.02},
}
VIDEO_MODEL_ALIASES = {
    "grok-imagine-video-1.5-latest": "grok-imagine-video-1.5",
    "grok-imagine-video-1.5-preview": "grok-imagine-video-1.5",
    "grok-imagine-video-1.5-2026-05-30": "grok-imagine-video-1.5",
}
IMAGE_MODEL_ALIASES = {
    "grok-imagine-image-quality-latest": "grok-imagine-image-quality",
    "grok-imagine-image-quality-20260403": "grok-imagine-image-quality",
    "grok-imagine-image-pro": "grok-imagine-image-quality",
}
from threading import Lock
_VIDEO_JOB_RESULTS = {}
_VIDEO_JOB_LOCK = Lock()

# ── Models Registry ──────────────────────────────────────────────────────────
MODELS = {
    "language": [
        {"id": "grok-4.3", "name": "Grok 4.3", "context": 1000000, "tag": "current"},
        {"id": "grok-4.20-multi-agent-beta-0309", "name": "Grok 4.20 Multi-Agent", "context": 2000000, "tag": "multi-agent"},
        {"id": "grok-4.20-beta-0309-reasoning", "name": "Grok 4.20 Reasoning", "context": 2000000, "tag": "reasoning"},
        {"id": "grok-4.20-beta-0309-non-reasoning", "name": "Grok 4.20", "context": 2000000, "tag": "fast"},
        {"id": "grok-code-fast-1", "name": "Grok Code Fast", "context": 256000, "tag": "code"},
        {"id": "grok-4-1-fast-reasoning", "name": "Grok 4.1 Fast Reasoning", "context": 2000000, "tag": "reasoning"},
        {"id": "grok-4-1-fast-non-reasoning", "name": "Grok 4.1 Fast", "context": 2000000, "tag": "fast"},
        {"id": "grok-build-0.1", "name": "Grok Build 0.1", "context": 256000, "tag": "coding"},
    ],
    "image": [
        {"id": "grok-imagine-image-2.0", "name": "Grok Imagine Image 2.0", "provider": "xai", "tag": "current", "price": "$0.04-$0.08/output + inputs"},
        {"id": "grok-imagine-image-quality", "name": "Grok Imagine Quality (legacy)", "price": "$0.05-$0.07/output + inputs", "retirement_date": "2026-11-02"},
        {"id": "grok-imagine-image", "name": "Grok Imagine", "price": "$0.02"},
        {"id": "gpt-image-1", "name": "ChatGPT Image", "price": "~$0.04"},
    ],
    "video": [
        {"id": "grok-imagine-video-1.5-lite", "name": "Grok Video 1.5 Lite · Fast", "provider": "xai", "tag": "fast", "price": "$0.02/$0.03/$0.14 per s (480/720/1080p)", "rates": VIDEO_RATES["grok-imagine-video-1.5-lite"]},
        {"id": "grok-imagine-video-1.5", "name": "Grok Video 1.5 · Quality", "provider": "xai", "tag": "quality", "price": "$0.08/$0.14/$0.25 per s (480/720/1080p)", "rates": VIDEO_RATES["grok-imagine-video-1.5"], "aliases": ["grok-imagine-video-1.5-preview", "grok-imagine-video-1.5-2026-05-30"]},
        {"id": "grok-imagine-video", "name": "Grok Imagine Video · Classic", "provider": "xai", "price": "$0.05/$0.07 per s (480/720p)", "rates": VIDEO_RATES["grok-imagine-video"]},
    ],
}

DEFAULT_CHAT_MODEL = "grok-4.3"
LANGUAGE_MODEL_ALIASES = {
    "grok-4.3-beta": "grok-4.3",
    "grok-4-3-beta": "grok-4.3",
    "grok-4.3-beta-early-access": "grok-4.3",
}


def load_settings():
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text() or "{}")
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def save_settings(data):
    current = load_settings()
    current.update(data)
    temporary = SETTINGS_FILE.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(current, handle, indent=2)
    temporary.chmod(0o600)
    temporary.replace(SETTINGS_FILE)
    return current


def _clean_api_key(value):
    value = str(value or "").strip().strip("'\"")
    placeholder_markers = ("YOUR_KEY_HERE", "REPLACE", "PASTE_KEY", "PLACEHOLDER")
    if not value or any(marker.lower() in value.lower() for marker in placeholder_markers):
        return ""
    return value


def _env_file_key(name):
    if os.environ.get("DORK_NO_ENV") == "1":
        return ""
    try:
        return _clean_api_key(dotenv_values(ENV_FILE).get(name, ""))
    except Exception:
        return ""


def _configured_key(env_name, settings_name):
    settings = load_settings()
    return (
        _env_file_key(env_name)
        or _clean_api_key(os.environ.get(env_name, ""))
        or _clean_api_key(settings.get(settings_name, ""))
    )


def get_api_key():
    return _configured_key("XAI_API_KEY", "xai_key")


def get_openai_api_key():
    return _configured_key("OPENAI_API_KEY", "openai_key")


def _upload_file_to_collection(filename, file_bytes, content_type, collection_id):
    """Upload a file to an xAI collection via POST /v1/files."""
    api_key = get_api_key()
    if not api_key:
        raise ValueError("No API key configured")
    boundary = uuid.uuid4().hex
    body = b""
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode()
    body += f"Content-Type: {content_type}\r\n\r\n".encode()
    body += file_bytes if isinstance(file_bytes, bytes) else file_bytes.encode("utf-8")
    body += f"\r\n--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="collection_ids"\r\n\r\n'.encode()
    body += collection_id.encode()
    body += f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(f"{XAI_BASE}/files", data=body, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("User-Agent", "DorkDirector/1.0")
    try:
        resp = urllib.request.urlopen(req, timeout=120)
        return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ValueError(_parse_xai_error(e))


IMAGE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

REFERENCE_IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp"}
XAI_REFERENCE_IMAGE_MIMES = {"image/png", "image/jpeg"}
XAI_REFERENCE_MAX_DIMENSION = 2048
XAI_REFERENCE_MAX_BYTES = 18 * 1024 * 1024


def _strip_data_uri(image_data):
    """Accept either raw base64 or a data URI from the browser."""
    image_data = (image_data or "").strip()
    if image_data.startswith("data:") and "," in image_data:
        return image_data.split(",", 1)[1]
    return image_data


def _mime_from_image_bytes(image_bytes):
    if image_bytes[:3] == b'\xff\xd8\xff':
        return "image/jpeg"
    if image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
        return "image/png"
    if image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP':
        return "image/webp"
    if image_bytes[:4] == b'GIF8':
        return "image/gif"
    return ""


def _detect_mime(b64_data):
    """Detect actual MIME type from base64-encoded image data."""
    b64_data = _strip_data_uri(b64_data)
    try:
        header = base64.b64decode(b64_data[:32])
        detected = _mime_from_image_bytes(header)
        if detected:
            return detected
    except Exception:
        pass
    return "image/png"


def _reference_image_parts(image_data, *, allow_gif=False):
    b64_data = _strip_data_uri(image_data)
    if not b64_data:
        raise ValueError("Reference image is empty")
    try:
        image_bytes = base64.b64decode(b64_data, validate=True)
    except Exception:
        raise ValueError("Reference image data is not valid base64")
    mime = _mime_from_image_bytes(image_bytes)
    allowed = set(REFERENCE_IMAGE_MIMES)
    if allow_gif:
        allowed.add("image/gif")
    if mime not in allowed:
        raise ValueError("Reference image must be PNG, JPG, or WEBP")
    return b64_data, image_bytes, mime, f"data:{mime};base64,{b64_data}"


def _xai_reference_data_uri(image_data):
    """Normalize refs to formats xAI image edits reliably accept: PNG or JPEG."""
    b64_data, image_bytes, mime, data_uri = _reference_image_parts(image_data)
    if mime in XAI_REFERENCE_IMAGE_MIMES and len(image_bytes) <= XAI_REFERENCE_MAX_BYTES:
        return data_uri

    try:
        from PIL import Image
    except Exception:
        if mime in XAI_REFERENCE_IMAGE_MIMES:
            return data_uri
        raise ValueError("Reference image must be PNG or JPG for xAI edits")

    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
    except Exception:
        raise ValueError("Reference image could not be decoded")

    width, height = img.size
    longest = max(width, height)
    if longest > XAI_REFERENCE_MAX_DIMENSION:
        scale = XAI_REFERENCE_MAX_DIMENSION / longest
        img = img.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.LANCZOS)

    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    if has_alpha:
        output = io.BytesIO()
        img.convert("RGBA").save(output, format="PNG", optimize=True)
        out_bytes = output.getvalue()
        if len(out_bytes) <= XAI_REFERENCE_MAX_BYTES:
            return f"data:image/png;base64,{base64.b64encode(out_bytes).decode('ascii')}"

    quality = 92
    working = img.convert("RGB")
    while True:
        output = io.BytesIO()
        working.save(output, format="JPEG", quality=quality, optimize=True)
        out_bytes = output.getvalue()
        if len(out_bytes) <= XAI_REFERENCE_MAX_BYTES or quality <= 74:
            return f"data:image/jpeg;base64,{base64.b64encode(out_bytes).decode('ascii')}"
        quality -= 6


def _image_metadata_path(filename):
    return IMAGES_DIR / f"{Path(filename).name}.json"


def _write_image_metadata(filename, prompt, model):
    if not filename:
        return
    try:
        _image_metadata_path(filename).write_text(json.dumps({
            "prompt": prompt,
            "model": model,
            "created": time.time(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _read_image_metadata(filename):
    try:
        path = _image_metadata_path(filename)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return {k: data[k] for k in ("prompt", "model") if data.get(k)}
    except Exception:
        pass
    return {}


def _save_image_result(img_data, prefix, prompt, model, index):
    b64 = img_data.get("b64_json") or img_data.get("base64") or ""
    if b64:
        b64 = _strip_data_uri(b64)
        ts = int(time.time() * 1000)
        mime = _detect_mime(b64)
        ext = IMAGE_EXTENSIONS.get(mime, ".png")
        filename = f"{prefix}_{ts}_{index}{ext}"
        filepath = IMAGES_DIR / filename
        filepath.write_bytes(base64.b64decode(b64))
        _write_image_metadata(filename, prompt, model)
        return {"filename": filename, "url": f"/images/{filename}", "prompt": prompt, "model": model}

    url = img_data.get("url", "")
    if not url:
        return None

    try:
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", "DorkDirector/1.0")
        resp = urllib.request.urlopen(req, timeout=120)
        image_bytes = resp.read()
        content_type = resp.headers.get("Content-Type", "").split(";", 1)[0].lower()
        mime = content_type if content_type in IMAGE_EXTENSIONS else (_mime_from_image_bytes(image_bytes) or "image/png")
        ext = IMAGE_EXTENSIONS.get(mime, ".png")
        ts = int(time.time() * 1000)
        filename = f"{prefix}_{ts}_{index}{ext}"
        filepath = IMAGES_DIR / filename
        filepath.write_bytes(image_bytes)
        _write_image_metadata(filename, prompt, model)
        return {"filename": filename, "url": f"/images/{filename}", "prompt": prompt, "model": model}
    except Exception:
        return {"filename": "", "url": url, "prompt": prompt, "model": model}


def _save_image_results(result, prefix, prompt, model):
    saved = []
    for i, img_data in enumerate(result.get("data", [])):
        saved_img = _save_image_result(img_data, prefix, prompt, model, i)
        if saved_img:
            saved.append(saved_img)
    return saved


def _xai_image_edit(model, prompt, data_uri, settings=None):
    """Submit the documented edit shape once; never retry a paid submission."""
    model = _media_model(model, "image")
    settings = dict(settings or {})
    if model == "grok-imagine-image-2.0":
        settings.setdefault("quality", DEFAULT_IMAGE_QUALITY)
    else:
        settings.pop("quality", None)
    sources = data_uri if isinstance(data_uri, list) else [data_uri]
    if not 1 <= len(sources) <= IMAGE_REFERENCE_MAX:
        raise ValueError("Reference images must contain 1–5 images")
    images = [{"type": "image_url", "url": uri} for uri in sources]
    inputs = {"image": images[0]} if len(images) == 1 else {"images": images}
    return xai_request("images/edits", {"model": model, "prompt": prompt, **settings, **inputs})


def _xai_image_edit_batch(model, prompt, data_uri, settings=None, n=1):
    n = max(1, min(int(n or 1), IMAGE_EDIT_BATCH_MAX))
    settings = dict(settings or {})
    if n == 1:
        return _xai_image_edit(model, prompt, data_uri, settings)

    # xAI edit support for `n` has varied, so run edit jobs concurrently and
    # merge the returned image data into the same shape as a batch response.
    merged = {"data": []}
    with ThreadPoolExecutor(max_workers=min(n, 4)) as executor:
        futures = [executor.submit(_xai_image_edit, model, prompt, data_uri, settings) for _ in range(n)]
        for future in as_completed(futures):
            result = future.result()
            merged["data"].extend(result.get("data", []))
    return merged


def _parse_xai_error(e):
    """Extract a readable error message from an xAI HTTP error."""
    try:
        body = json.loads(e.read().decode("utf-8"))
        err = body.get("error", body.get("code", ""))
        if isinstance(err, dict):
            msg = err.get("message", str(err))
        else:
            msg = str(err)
        return f"HTTP {e.code}: {msg}" if msg else f"HTTP {e.code}"
    except Exception:
        return f"HTTP {e.code}"


def _parse_openai_error(e):
    """Extract a readable error message from an OpenAI HTTP error."""
    try:
        body = json.loads(e.read().decode("utf-8"))
        err = body.get("error", {})
        if isinstance(err, dict):
            msg = err.get("message", str(err))
        else:
            msg = str(err)
        return f"HTTP {e.code}: {msg}" if msg else f"HTTP {e.code}"
    except Exception:
        return f"HTTP {e.code}"


def xai_request(endpoint, payload, stream=False):
    """Make a request to the xAI API."""
    api_key = get_api_key()
    if not api_key:
        raise ValueError("No xAI API key configured — set it in Settings or .env")

    url = f"{XAI_BASE}/{endpoint}"
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "DorkDirector/1.0")

    try:
        if stream:
            return urllib.request.urlopen(req, timeout=300)
        else:
            resp = urllib.request.urlopen(req, timeout=300)
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ValueError(_parse_xai_error(e))


def xai_get(endpoint):
    """GET request to xAI API."""
    api_key = get_api_key()
    if not api_key:
        raise ValueError("No xAI API key configured — set it in Settings or .env")

    url = f"{XAI_BASE}/{endpoint}"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("User-Agent", "DorkDirector/1.0")

    try:
        resp = urllib.request.urlopen(req, timeout=120)
        return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ValueError(_parse_xai_error(e))


def xai_get_optional(endpoint):
    api_key = get_api_key()
    if not api_key:
        return None

    url = f"{XAI_BASE}/{endpoint}"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("User-Agent", "DorkDirector/1.0")

    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _label_model(model_id):
    name = model_id.replace("-", " ")
    name = " ".join(part.upper() if part in ("ai", "tts") else part.capitalize() for part in name.split())
    return name.replace("Grok 4 3", "Grok 4.3").replace("Grok 4 20", "Grok 4.20").replace("Grok 4 1", "Grok 4.1")


def discover_language_models():
    discovered = []
    raw = xai_get_optional("models")
    if raw:
        for item in _model_items(raw):
            model_id = item.get("id", "")
            if not model_id:
                continue
            lower = model_id.lower()
            if any(skip in lower for skip in ("imagine", "image", "video", "tts", "audio", "voice", "embed")):
                continue
            if "4.3" in lower or "4-3" in lower:
                tag = "early-access"
            elif "code" in lower:
                tag = "code"
            elif "multi-agent" in lower:
                tag = "multi-agent"
            elif "non-reasoning" in lower:
                tag = "fast"
            elif "reasoning" in lower:
                tag = "reasoning"
            else:
                tag = "fast"
            discovered.append({
                "id": model_id,
                "name": item.get("name") or _label_model(model_id),
                "context": item.get("context_window") or item.get("context_length") or item.get("context") or (2000000 if "4" in lower else 256000),
                "tag": tag,
                "early_access": tag == "early-access",
                "available": True,
            })

    builtin_order = {m["id"]: i for i, m in enumerate(MODELS["language"])}
    by_id = {m["id"]: dict(m, available=True, builtin=True) for m in MODELS["language"]}
    for model in discovered:
        by_id[model["id"]] = {**by_id.get(model["id"], {}), **model}

    def sort_key(model):
        if model.get("tag") == "early-access":
            return (0, model.get("name", ""))
        if model.get("id") in builtin_order:
            return (1, builtin_order[model["id"]])
        order = {"multi-agent": 2, "reasoning": 3, "fast": 4, "code": 5}
        return (order.get(model.get("tag"), 9), model.get("name", ""))

    return sorted(by_id.values(), key=sort_key)


def _coerce_choice(value, allowed, default):
    value = str(value or "").strip()
    return value if value in allowed else default


def _coerce_int(value, default, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _media_model(value, kind):
    default = DEFAULT_VIDEO_MODEL if kind == "video" else DEFAULT_IMAGE_MODEL
    model = str(value or default).strip()
    aliases = VIDEO_MODEL_ALIASES if kind == "video" else IMAGE_MODEL_ALIASES
    model = aliases.get(model, model)
    rates = VIDEO_RATES if kind == "video" else IMAGE_RATES
    if model not in rates:
        raise ValueError(f"Unsupported xAI {kind} model")
    return model


def _media_int(value, default, minimum, maximum, name):
    if value is None:
        return default
    try:
        parsed = int(value)
        if isinstance(value, bool) or float(value) != parsed:
            raise ValueError()
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{name} must be an integer")
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be {minimum}–{maximum}")
    return parsed


def _media_choice(value, allowed, default, name):
    chosen = str(value or default).strip()
    if chosen not in allowed:
        raise ValueError(f"Unsupported {name}")
    return chosen


def _image_options(data):
    model = _media_model(data.get("model"), "image")
    resolutions = IMAGE_RESOLUTIONS if model != "grok-imagine-image" else {"1k", "2k"}
    options = {
        "model": model,
        "n": _media_int(data.get("n"), 1, 1, IMAGE_OUTPUT_COUNT_MAX, "Image count"),
        "resolution": _media_choice(data.get("resolution"), resolutions, DEFAULT_IMAGE_RESOLUTION, "image resolution"),
    }
    if model == "grok-imagine-image-2.0":
        options["quality"] = _media_choice(data.get("quality"), IMAGE_QUALITIES, DEFAULT_IMAGE_QUALITY, "image quality")
    aspect = _media_choice(data.get("aspect_ratio"), IMAGE_ASPECT_RATIOS, DEFAULT_IMAGE_ASPECT_RATIO, "image aspect ratio")
    if aspect != "auto":
        options["aspect_ratio"] = aspect
    return options


def _video_options(data, *, has_image=False):
    model = _media_model(data.get("model"), "video")
    options = {
        "model": model,
        "duration": _media_int(data.get("duration"), DEFAULT_VIDEO_DURATION, VIDEO_DURATION_MIN, VIDEO_DURATION_MAX, "Duration"),
        "resolution": _media_choice(data.get("resolution"), VIDEO_RATES[model], DEFAULT_VIDEO_RESOLUTION, "video resolution"),
    }
    # Direct xAI permits an I2V aspect override, but stretches the source.
    # Omitting it preserves source framing; Fal's I2V schema is different.
    aspect = data.get("aspect_ratio")
    if aspect and aspect != "auto":
        options["aspect_ratio"] = _media_choice(aspect, VIDEO_ASPECT_RATIOS, DEFAULT_VIDEO_ASPECT_RATIO, "video aspect ratio")
    elif not has_image:
        options["aspect_ratio"] = DEFAULT_VIDEO_ASPECT_RATIO
    if "generate_audio" in data:
        if not isinstance(data["generate_audio"], bool):
            raise ValueError("generate_audio must be a boolean")
        options["generate_audio"] = data["generate_audio"]
    return options


def estimate_media_cost(data):
    """Calculate a local estimate without reading a credential or calling a provider."""
    kind = data.get("kind", "video")
    if kind not in {"image", "video"}:
        raise ValueError("kind must be image or video")
    inputs = _media_int(data.get("input_images"), 0, 0, 1 if kind == "video" else IMAGE_REFERENCE_MAX, "Input image count")
    operation = data.get("operation", "generate")
    if operation not in {"generate", "edit"}:
        raise ValueError("operation must be generate or edit")
    result = {"provider": "xai", "kind": kind, "currency": "USD", "pricing_verified": MEDIA_PRICING_DATE,
              "input_images": inputs, "caveat": "Estimate using xAI global API rates; provider billing may change. Additional image composition or chat calls are excluded."}
    if kind == "video":
        if operation != "generate":
            raise ValueError("This estimate covers text/image-to-video generation only")
        options = _video_options(data, has_image=bool(inputs))
        rate = VIDEO_RATES[options["model"]][options["resolution"]]
        input_rate = 0.002 if options["model"] == "grok-imagine-video" else 0.01
        result.update(options, output_rate_per_second=rate, input_rate_per_image=input_rate,
                      estimate_usd=round(options["duration"] * rate + inputs * input_rate, 6))
    else:
        options = _image_options(data)
        model = options["model"]
        # Source-image generation routes through edits in this app. The
        # existing batch edit workflow submits one explicit job per output.
        operation = "edit" if inputs else operation
        quality = options.get("quality", "low")
        served = ("medium" if operation == "edit" else "low") if quality == "auto" else quality
        rate = IMAGE_RATES[model][served][options["resolution"]] if model == "grok-imagine-image-2.0" else IMAGE_RATES[model][options["resolution"]]
        input_rate = 0.002 if model == "grok-imagine-image" else 0.01
        result.update(options, operation=operation, estimated_served_quality=served,
                      output_rate_per_image=rate, input_rate_per_image=input_rate,
                      input_cost_repeated_per_output=operation == "edit",
                      estimate_usd=round(options["n"] * (rate + inputs * input_rate), 6))
        if quality == "auto":
            result["caveat"] += " Auto currently uses low for generation and medium for editing; the provider chooses the served quality."
    return result


def _price_label(cents):
    if cents is None:
        return ""
    try:
        value = float(cents)
    except (TypeError, ValueError):
        return ""
    dollars = value / 100
    if dollars > 100:
        dollars = value / 10_000_000_000
    return f"${dollars:.2f}"


def _model_items(raw):
    if not raw:
        return []
    if isinstance(raw.get("models"), list):
        return raw["models"]
    if isinstance(raw.get("data"), list):
        return raw["data"]
    return []


def discover_generation_models(endpoint, builtin, *, fallback_tag, price_key=None):
    raw = xai_get_optional(endpoint)
    by_id = {m["id"]: dict(m, available=True, builtin=True) for m in builtin}
    for item in _model_items(raw):
        model_id = item.get("id", "")
        if not model_id:
            continue
        model = {
            "id": model_id,
            "name": by_id.get(model_id, {}).get("name") or _label_model(model_id),
            "tag": by_id.get(model_id, {}).get("tag") or fallback_tag,
            "available": True,
            "version": item.get("version", ""),
            "aliases": item.get("aliases", []),
            "fingerprint": item.get("fingerprint", ""),
        }
        existing = by_id.get(model_id, {})
        price = _price_label(item.get(price_key)) if price_key else ""
        if price and not existing.get("price"):
            model["price"] = price
        by_id[model_id] = {**by_id.get(model_id, {}), **model}

    return list(by_id.values())


def build_xai_tools(tool_ids, collection_ids=None):
    tools = []
    for tool_id in tool_ids or []:
        if tool_id == "web_search":
            tools.append({"type": "web_search"})
        elif tool_id == "x_search":
            tools.append({"type": "x_search"})
        elif tool_id == "code_execution":
            tools.append({"type": "code_execution"})
        elif tool_id == "collections_search":
            tool = {"type": "collections_search"}
            if collection_ids:
                tool["collection_ids"] = collection_ids
            tools.append(tool)
    return tools


def normalize_language_model(model, *, allow_openai=False):
    model = (model or DEFAULT_CHAT_MODEL).strip()
    if allow_openai and model.startswith(("gpt-", "o3", "o4", "chatgpt-")):
        return model
    return LANGUAGE_MODEL_ALIASES.get(model, model or DEFAULT_CHAT_MODEL)


def _chat_part_image_url(part):
    image = part.get("image_url") if isinstance(part, dict) else None
    if isinstance(image, dict):
        return image.get("url", "")
    if isinstance(image, str):
        return image
    return part.get("url", "") if isinstance(part, dict) else ""


def sanitize_chat_messages(messages):
    """Keep chat payloads valid even if localStorage has stale image attachments."""
    safe = []
    last_image_idx = -1
    for i, msg in enumerate(messages or []):
        content = msg.get("content") if isinstance(msg, dict) else ""
        if isinstance(content, list) and any(
            isinstance(part, dict) and part.get("type") == "image_url" for part in content
        ):
            last_image_idx = i

    for i, msg in enumerate(messages or []):
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "user")
        if role not in ("system", "user", "assistant"):
            role = "user"
        content = msg.get("content", "")
        if isinstance(content, list):
            parts = []
            omitted = False
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    text = part.get("text", "")
                    if text:
                        parts.append({"type": "text", "text": text})
                elif part.get("type") == "image_url":
                    if i != last_image_idx:
                        omitted = True
                        continue
                    url = _chat_part_image_url(part)
                    if not url:
                        omitted = True
                        continue
                    if url.startswith("data:"):
                        try:
                            url = _xai_reference_data_uri(url)
                        except Exception:
                            omitted = True
                            continue
                    parts.append({"type": "image_url", "image_url": {"url": url}})
            if omitted:
                parts.append({"type": "text", "text": "[Earlier or unsupported image attachment omitted.]"})
            if not parts:
                continue
            content = parts
        elif not isinstance(content, str):
            content = str(content)
        if content == "":
            continue
        safe.append({"role": role, "content": content})
    return safe


def extract_response_text(result):
    if result.get("output_text"):
        return result["output_text"]
    parts = []
    for item in result.get("output", []):
        for content in item.get("content", []):
            text = content.get("text") or content.get("value")
            if text:
                parts.append(text)
    return "\n".join(parts)


def openai_request(endpoint, payload):
    """Make a request to the OpenAI API."""
    api_key = get_openai_api_key()
    if not api_key:
        raise ValueError("No OpenAI API key configured — set it in Settings or .env")

    url = f"{OPENAI_BASE}/{endpoint}"
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "DorkDirector/1.0")

    try:
        resp = urllib.request.urlopen(req, timeout=300)
        return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ValueError(_parse_openai_error(e))


def openai_multipart_request(endpoint, fields, files):
    """Make a multipart/form-data request to OpenAI."""
    api_key = get_openai_api_key()
    if not api_key:
        raise ValueError("No OpenAI API key configured — set it in Settings or .env")

    boundary = uuid.uuid4().hex
    body = bytearray()

    for name, value in fields.items():
        if value is None:
            continue
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        body += str(value).encode("utf-8")
        body += b"\r\n"

    for name, filename, content_type, file_bytes in files:
        body += f"--{boundary}\r\n".encode()
        body += (
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode()
        body += file_bytes
        body += b"\r\n"

    body += f"--{boundary}--\r\n".encode()

    req = urllib.request.Request(f"{OPENAI_BASE}/{endpoint}", data=bytes(body), method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("User-Agent", "DorkDirector/1.0")

    try:
        resp = urllib.request.urlopen(req, timeout=300)
        return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ValueError(_parse_openai_error(e))


def openai_chat_request(endpoint, payload, stream=False):
    """Make a request to the OpenAI API, with optional streaming support."""
    api_key = get_openai_api_key()
    if not api_key:
        raise ValueError("No OpenAI API key configured — set it in Settings or .env")

    url = f"{OPENAI_BASE}/{endpoint}"
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "DorkDirector/1.0")

    try:
        if stream:
            return urllib.request.urlopen(req, timeout=300)
        else:
            resp = urllib.request.urlopen(req, timeout=300)
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ValueError(_parse_openai_error(e))


# ── OpenAI Image Generation ──────────────────────────────────────────────────

def openai_image_generate(prompt, model="gpt-image-1", size="1024x1024", n=1):
    """Generate an image via OpenAI's image models."""
    n = max(1, min(int(n or 1), 4))
    payload = {
        "model": model,
        "prompt": prompt,
        "n": n,
        "size": size,
    }
    if model.startswith("gpt-image-"):
        payload["output_format"] = "png"
    else:
        payload["response_format"] = "b64_json"
    result = openai_request("images/generations", payload)
    images = result.get("data", [])
    if not images:
        raise ValueError("No image returned from OpenAI")

    saved = []
    for i, img_data in enumerate(images):
        b64 = img_data.get("b64_json", "")
        if not b64:
            continue
        ts = int(time.time() * 1000)
        mime = _detect_mime(b64)
        ext = {"image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}.get(mime, ".png")
        filename = f"openai_{ts}_{i}{ext}"
        filepath = IMAGES_DIR / filename
        filepath.write_bytes(base64.b64decode(b64))
        _write_image_metadata(filename, prompt, model)
        saved.append({"filename": filename, "url": f"/images/{filename}", "prompt": prompt, "model": model})
    if not saved:
        raise ValueError("No image data in response")
    return {**saved[0], "images": saved}


def openai_image_edit(prompt, image_data, model="gpt-image-1.5", size="1024x1024", n=1):
    """Edit an image via OpenAI's image models."""
    _, image_bytes, mime, _ = _reference_image_parts(image_data)
    n = max(1, min(int(n or 1), 4))
    ext = IMAGE_EXTENSIONS.get(mime, ".png")
    fields = {
        "model": model,
        "prompt": prompt,
        "n": n,
        "size": size,
        "output_format": "png",
    }
    result = openai_multipart_request(
        "images/edits",
        fields,
        [("image", f"reference{ext}", mime, image_bytes)],
    )
    saved = []
    for i, img_data in enumerate(result.get("data", [])):
        b64 = img_data.get("b64_json", "")
        if not b64:
            continue
        ts = int(time.time() * 1000)
        emime = _detect_mime(b64)
        eext = IMAGE_EXTENSIONS.get(emime, ".png")
        filename = f"openai_edit_{ts}_{i}{eext}"
        filepath = IMAGES_DIR / filename
        filepath.write_bytes(base64.b64decode(b64))
        _write_image_metadata(filename, prompt, model)
        saved.append({"filename": filename, "url": f"/images/{filename}", "prompt": prompt, "model": model})
    if not saved:
        raise ValueError("No edited image data in OpenAI response")
    return {**saved[0], "images": saved}


# ── Collection Context Retrieval ──────────────────────────────────────────────

_collection_cache = {}
CACHE_TTL = 300


def fetch_collection_context(collection_ids, max_chars=80000):
    """Fetch document contents from collections and return as combined text context."""
    api_key = get_api_key()
    if not api_key:
        return ""

    all_docs = []
    for coll_id in collection_ids:
        cached = _collection_cache.get(coll_id)
        if cached and (time.time() - cached["fetched_at"]) < CACHE_TTL:
            all_docs.extend(cached["docs"])
            continue

        try:
            doc_list = xai_get(f"collections/{coll_id}/documents")
            docs = doc_list.get("documents", [])

            fetched = []
            for doc in docs:
                file_id = doc.get("file_metadata", {}).get("file_id", "")
                file_name = doc.get("file_metadata", {}).get("name", "unknown")
                if not file_id:
                    continue
                try:
                    url = f"{XAI_BASE}/files/{file_id}/content"
                    req = urllib.request.Request(url, method="GET")
                    req.add_header("Authorization", f"Bearer {api_key}")
                    req.add_header("User-Agent", "DorkDirector/1.0")
                    resp = urllib.request.urlopen(req, timeout=30)
                    content = resp.read().decode("utf-8", errors="replace")
                    fetched.append({"name": file_name, "content": content})
                except Exception:
                    pass

            _collection_cache[coll_id] = {"docs": fetched, "fetched_at": time.time()}
            all_docs.extend(fetched)
        except Exception:
            pass

    if not all_docs:
        return ""

    parts = []
    total = 0
    for doc in all_docs:
        header = f"=== {doc['name']} ===\n"
        content = doc["content"]
        if total + len(header) + len(content) > max_chars:
            remaining = max_chars - total - len(header) - 20
            if remaining > 200:
                parts.append(header + content[:remaining] + "\n[truncated]")
            break
        parts.append(header + content)
        total += len(header) + len(content)

    return "\n\n".join(parts)


def _preview_key(key):
    if not key:
        return ""
    return key[:8] + "..." + key[-4:] if len(key) > 12 else "set"


def _dir_stats(directory, suffixes=None):
    suffixes = tuple(s.lower() for s in suffixes) if suffixes else None
    files = []
    total_bytes = 0
    for path in directory.iterdir():
        if not path.is_file():
            continue
        if suffixes and path.suffix.lower() not in suffixes:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        total_bytes += stat.st_size
        files.append({
            "filename": path.name,
            "modified": stat.st_mtime,
            "bytes": stat.st_size,
        })
    files.sort(key=lambda item: item["modified"], reverse=True)
    return {
        "count": len(files),
        "bytes": total_bytes,
        "latest": files[0] if files else None,
    }


def _workspace_summary():
    stats = {
        "images": _dir_stats(IMAGES_DIR, [".png", ".jpg", ".jpeg", ".webp", ".gif"]),
        "videos": _dir_stats(VIDEOS_DIR, [".mp4", ".mov", ".webm"]),
        "audio": _dir_stats(AUDIO_DIR, [".mp3", ".wav", ".m4a", ".ogg"]),
        "uploads": _dir_stats(UPLOADS_DIR),
        "artifacts": _dir_stats(ARTIFACTS_DIR, [".html"]),
        "skills": _dir_stats(SKILLS_DIR, [".md"]),
    }
    latest = []
    for name, data in stats.items():
        if data["latest"]:
            latest.append({"type": name, **data["latest"]})
    latest.sort(key=lambda item: item["modified"], reverse=True)
    xai_key = get_api_key()
    openai_key = get_openai_api_key()
    return {
        "app": "dork",
        "data_dir": str(DATA_DIR),
        "settings_dir": str(SETTINGS_DIR),
        "api_keys": {
            "xai": {"set": bool(xai_key)},
            "openai": {"set": bool(openai_key)},
        },
        "stats": stats,
        "latest": latest[:8],
        "generated_at": time.time(),
    }


# ── Routes: Pages ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", cache_bust=int(time.time()))


# ── Routes: Settings ─────────────────────────────────────────────────────────

@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "GET":
        settings = load_settings()
        settings.pop("xai_key", None)
        settings.pop("openai_key", None)
        xai_key = get_api_key()
        openai_key = get_openai_api_key()
        settings["xai_key_set"] = bool(xai_key)
        settings["xai_key_preview"] = "configured" if xai_key else ""
        settings["openai_key_set"] = bool(openai_key)
        settings["openai_key_preview"] = "configured" if openai_key else ""
        return jsonify(settings)
    else:
        data = request.json or {}
        cleaned = {}
        if _clean_api_key(data.get("xai_key")):
            cleaned["xai_key"] = _clean_api_key(data.get("xai_key"))
        if _clean_api_key(data.get("openai_key")):
            cleaned["openai_key"] = _clean_api_key(data.get("openai_key"))
        for key, value in data.items():
            if key not in {"xai_key", "openai_key"}:
                cleaned[key] = value
        save_settings(cleaned)
        return jsonify({"status": "ok"})


@app.route("/api/workspace")
def api_workspace():
    return jsonify(_workspace_summary())


@app.route("/api/models")
def api_models():
    models = dict(MODELS)
    models["language"] = discover_language_models()
    models["image"] = discover_generation_models("image-generation-models", MODELS["image"], fallback_tag="image", price_key="image_price")
    models["video"] = discover_generation_models("video-generation-models", MODELS["video"], fallback_tag="video")
    models["capabilities"] = {
        "image": {
            "default_model": DEFAULT_IMAGE_MODEL,
            "recommended_model": DEFAULT_IMAGE_MODEL,
            "latest_alias": DEFAULT_IMAGE_MODEL,
            "deprecated_models": ["grok-imagine-image-pro", "grok-imagine-image-quality"],
            "provider": "xai",
            "default_quality": DEFAULT_IMAGE_QUALITY,
            "quality_options": ["low", "medium", "auto"],
            "quality_model": "grok-imagine-image-2.0",
            "pricing": IMAGE_RATES,
            "pricing_verified": MEDIA_PRICING_DATE,
            "estimate_endpoint": "/api/media/estimate",
            "count_max": IMAGE_OUTPUT_COUNT_MAX,
            "edit_batch_max": IMAGE_EDIT_BATCH_MAX,
            "reference_images_max": IMAGE_REFERENCE_MAX,
            "resolutions": sorted(IMAGE_RESOLUTIONS),
            "aspect_ratios": sorted(IMAGE_ASPECT_RATIOS),
        },
        "video": {
            "default_model": DEFAULT_VIDEO_MODEL,
            "recommended_model": DEFAULT_VIDEO_MODEL,
            "stable_model": DEFAULT_VIDEO_MODEL,
            "provider": "xai",
            "fast_model": "grok-imagine-video-1.5-lite",
            "quality_model": "grok-imagine-video-1.5",
            "classic_model": "grok-imagine-video",
            "pricing": VIDEO_RATES,
            "input_image_rates": {"grok-imagine-video-1.5-lite": 0.01, "grok-imagine-video-1.5": 0.01, "grok-imagine-video": 0.002},
            "pricing_verified": MEDIA_PRICING_DATE,
            "estimate_endpoint": "/api/media/estimate",
            "model_resolutions": {model: list(rates) for model, rates in VIDEO_RATES.items()},
            "duration_min": VIDEO_DURATION_MIN,
            "duration_max": VIDEO_DURATION_MAX,
            "duration_options": [5, 6, 8, 10, 12, 15],
            "resolutions": VIDEO_RESOLUTION_ORDER,
            "aspect_ratios": sorted(VIDEO_ASPECT_RATIOS),
            "supports_image_to_video": True,
            "supports_video_editing": False,
            "supports_video_extension": False,
            "supports_reference_to_video": False,
            "supports_lastframe_continuation": True,
            "continuation_note": "Continue from an extracted last frame via a new image-to-video generation; this is a separate paid request.",
        },
    }
    models["early_access_hints"] = []
    models["discovery"] = {
        "live": bool(get_api_key()),
        "note": "Available xAI language, image, and video models are refreshed from your API key; bundled defaults are only fallback.",
    }
    return jsonify(models)


@app.route("/api/media/estimate", methods=["POST"])
def api_media_estimate():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON object required"}), 400
    try:
        return jsonify(estimate_media_cost(data))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# ── Routes: Chat (Streaming SSE) ─────────────────────────────────────────────

@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.json
    model = normalize_language_model(data.get("model", DEFAULT_CHAT_MODEL), allow_openai=True)
    messages = sanitize_chat_messages(data.get("messages", []))
    system = data.get("system", "")
    temperature = data.get("temperature", 0.7)
    collection_ids = data.get("collection_ids", [])
    requested_tools = data.get("tools", [])
    reasoning = data.get("reasoning", {})

    system_parts = []
    if system:
        system_parts.append(system)
    if collection_ids:
        coll_context = fetch_collection_context(collection_ids)
        if coll_context:
            system_parts.append(
                "The user has attached the following documents from their collection. "
                "Use this information to answer their questions:\n\n" + coll_context
            )
    system_text = "\n\n".join(system_parts) if system_parts else ""

    response_tools = build_xai_tools(requested_tools, collection_ids)

    # Tool-enabled xAI chat and multi-agent models use /v1/responses.
    is_multi_agent = "multi-agent" in model
    is_openai = model.startswith("gpt-") or model.startswith("o3") or model.startswith("o4") or model.startswith("chatgpt-")
    use_responses = (is_multi_agent or bool(response_tools)) and not is_openai

    if use_responses:
        payload = {
            "model": model,
            "input": messages,
            "stream": True,
            "temperature": temperature,
        }
        if system_text:
            payload["instructions"] = system_text
        if response_tools:
            payload["tools"] = response_tools
        if is_multi_agent:
            effort = reasoning.get("effort", "low")
            if effort in ("low", "medium", "high", "xhigh"):
                payload["reasoning"] = {"effort": effort}

        def generate_multi_agent():
            try:
                resp = xai_request("responses", payload, stream=True)
                buffer = b""
                for chunk in iter(lambda: resp.read(4096), b""):
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        line = line.strip()
                        if not line:
                            continue
                        if line.startswith(b"data: "):
                            try:
                                obj = json.loads(line[6:])
                                evt_type = obj.get("type", "")
                                if evt_type in ("response.output_text.delta", "response.refusal.delta"):
                                    delta = obj.get("delta", "")
                                    if delta:
                                        yield f"data: {json.dumps({'content': delta})}\n\n"
                                elif evt_type == "response.reasoning_text.delta":
                                    delta = obj.get("delta", "")
                                    if delta:
                                        yield f"data: {json.dumps({'reasoning': delta})}\n\n"
                                elif evt_type == "response.completed":
                                    yield "data: [DONE]\n\n"
                                    return
                            except json.JSONDecodeError:
                                pass
                yield "data: [DONE]\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return Response(
            stream_with_context(generate_multi_agent()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )

    # Standard chat/completions models
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": temperature,
    }
    if system_text:
        payload["messages"] = [{"role": "system", "content": system_text}] + payload["messages"]

    def generate():
        try:
            if is_openai:
                resp = openai_chat_request("chat/completions", payload, stream=True)
            else:
                resp = xai_request("chat/completions", payload, stream=True)
            buffer = b""
            for chunk in iter(lambda: resp.read(4096), b""):
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    if line == b"data: [DONE]":
                        yield "data: [DONE]\n\n"
                        return
                    if line.startswith(b"data: "):
                        try:
                            obj = json.loads(line[6:])
                            delta = obj.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            reasoning = delta.get("reasoning_content", "")
                            if content:
                                yield f"data: {json.dumps({'content': content})}\n\n"
                            if reasoning:
                                yield f"data: {json.dumps({'reasoning': reasoning})}\n\n"
                        except json.JSONDecodeError:
                            pass
            if buffer.strip():
                line = buffer.strip()
                if line.startswith(b"data: ") and line != b"data: [DONE]":
                    try:
                        obj = json.loads(line[6:])
                        delta = obj.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield f"data: {json.dumps({'content': content})}\n\n"
                    except json.JSONDecodeError:
                        pass
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@app.route("/api/chat/sync", methods=["POST"])
def api_chat_sync():
    data = request.json
    model = normalize_language_model(data.get("model", DEFAULT_CHAT_MODEL), allow_openai=True)
    messages = sanitize_chat_messages(data.get("messages", []))
    system = data.get("system", "")
    collection_ids = data.get("collection_ids", [])
    requested_tools = data.get("tools", [])
    reasoning = data.get("reasoning", {})

    system_parts = []
    if system:
        system_parts.append(system)
    if collection_ids:
        coll_context = fetch_collection_context(collection_ids)
        if coll_context:
            system_parts.append(
                "The user has attached the following documents from their collection. "
                "Use this information to answer their questions:\n\n" + coll_context
            )
    system_text = "\n\n".join(system_parts) if system_parts else ""

    try:
        response_tools = build_xai_tools(requested_tools, collection_ids)
        is_openai = model.startswith("gpt-") or model.startswith("o3") or model.startswith("o4") or model.startswith("chatgpt-")
        if ("multi-agent" in model or response_tools) and not is_openai:
            payload = {"model": model, "input": messages, "stream": False}
            if system_text:
                payload["instructions"] = system_text
            if response_tools:
                payload["tools"] = response_tools
            if "multi-agent" in model:
                effort = reasoning.get("effort", "low")
                if effort in ("low", "medium", "high", "xhigh"):
                    payload["reasoning"] = {"effort": effort}
            result = xai_request("responses", payload)
            content = extract_response_text(result)
        else:
            payload = {"model": model, "messages": messages, "stream": False}
            if system_text:
                payload["messages"] = [{"role": "system", "content": system_text}] + payload["messages"]
            result = openai_request("chat/completions", payload) if is_openai else xai_request("chat/completions", payload)
            content = result["choices"][0]["message"]["content"]
        return jsonify({"content": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat/sync-openai", methods=["POST"])
def api_chat_sync_openai():
    """Synchronous chat completion via OpenAI for prompt suggestions."""
    data = request.json
    model = data.get("model", "gpt-5-mini")
    messages = data.get("messages", [])
    system = data.get("system", "")

    try:
        payload = {
            "model": model,
            "messages": messages,
        }
        if system:
            payload["messages"] = [{"role": "system", "content": system}] + payload["messages"]

        result = openai_request("chat/completions", payload)
        content = result["choices"][0]["message"]["content"]
        return jsonify({"content": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Routes: Image Generation ─────────────────────────────────────────────────

@app.route("/api/image/generate", methods=["POST"])
def api_image_generate():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON object required"}), 400
    prompt = data.get("prompt", "")
    if not isinstance(prompt, str) or not prompt.strip():
        return jsonify({"error": "Prompt required"}), 400
    try:
        options = _image_options(data)
        sources = data.get("references") or ([data["reference"]] if data.get("reference") else [])
        if not isinstance(sources, list) or len(sources) > IMAGE_REFERENCE_MAX:
            raise ValueError("Reference images must be a list of at most 5 images")
        references = [_xai_reference_data_uri(source) for source in sources]
        estimate = estimate_media_cost({**data, "kind": "image", "input_images": len(references)})
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    try:
        if references:
            # Use actual reference pixels, avoiding the old extra paid vision call.
            settings = {k: v for k, v in options.items() if k not in {"model", "n"}}
            result = _xai_image_edit_batch(options["model"], prompt, references, settings, n=options["n"])
        else:
            result = xai_request("images/generations", {"prompt": prompt, "response_format": "b64_json", **options})
        saved = _save_image_results(result, "img", prompt, options["model"])
        return jsonify({"images": saved, "estimate": estimate})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/image/generate-openai", methods=["POST"])
def api_image_generate_openai():
    """Generate image via OpenAI image models."""
    data = request.json
    prompt = data.get("prompt", "")
    model = data.get("model", "gpt-image-1")
    size = data.get("size", "1024x1024")
    n = data.get("n", 1)

    if not prompt:
        return jsonify({"error": "Prompt required"}), 400

    try:
        result = openai_image_generate(prompt, model=model, size=size, n=n)
        return jsonify({"images": [{**img, "prompt": prompt, "model": model} for img in result["images"]]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/image/edit-openai", methods=["POST"])
def api_image_edit_openai():
    """Edit image via OpenAI image models."""
    data = request.json
    prompt = data.get("prompt", "")
    model = data.get("model", "gpt-image-1.5")
    image_b64 = data.get("image", "")
    size = data.get("size", "1024x1024")
    n = data.get("n", 1)

    if not prompt or not image_b64:
        return jsonify({"error": "Prompt and image required"}), 400

    try:
        result = openai_image_edit(prompt, image_b64, model=model, size=size, n=n)
        return jsonify({"images": [{**img, "prompt": prompt, "model": model} for img in result["images"]]})
    except ValueError as e:
        status = 400 if str(e).startswith("Reference image") else 500
        return jsonify({"error": str(e)}), status
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/image/edit", methods=["POST"])
def api_image_edit():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON object required"}), 400
    prompt = data.get("prompt", "")
    model = data.get("model", DEFAULT_IMAGE_MODEL)
    image_b64 = data.get("image", "")
    sources = data.get("images") or ([image_b64] if image_b64 else [])
    if not isinstance(prompt, str) or not prompt.strip() or not sources:
        return jsonify({"error": "Prompt and image required"}), 400
    if isinstance(model, str) and model.startswith("gpt-"):
        try:
            result = openai_image_edit(prompt, image_b64, model=model, size=data.get("size", "1024x1024"))
            return jsonify({"images": [{**img, "prompt": prompt, "model": model} for img in result["images"]]})
        except Exception as e:
            return jsonify({"error": str(e)}), 502
    try:
        options = _image_options(data)
        if not isinstance(sources, list) or len(sources) > IMAGE_REFERENCE_MAX:
            raise ValueError("Reference images must be a list of at most 5 images")
        references = [_xai_reference_data_uri(source) for source in sources]
        settings = {k: v for k, v in options.items() if k not in {"model", "n"}}
        estimate = estimate_media_cost({**data, "kind": "image", "operation": "edit", "input_images": len(references)})
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    try:
        result = _xai_image_edit_batch(options["model"], prompt, references, settings, n=options["n"])
        saved = _save_image_results(result, "edit", prompt, options["model"])
        return jsonify({"images": saved, "estimate": estimate})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/image/combine", methods=["POST"])
def api_image_combine():
    """Combine two images using edit API (preserves character consistency from image 1)."""
    data = request.json
    image1_b64 = data.get("image1", "")
    image2_b64 = data.get("image2", "")
    user_prompt = data.get("prompt", "")

    if not image1_b64 or not image2_b64:
        return jsonify({"error": "Two images required"}), 400

    try:
        mime2 = _detect_mime(image2_b64)
        uri2 = f"data:{mime2};base64,{image2_b64}"

        analysis_prompt = "Describe the key visual elements, subjects, style, mood, colors, and thematic content of this image in 2-3 concise sentences. Focus on what makes it distinctive — characters, objects, environment, aesthetic. Be specific and vivid."
        vision_payload = {
            "model": DEFAULT_CHAT_MODEL,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": analysis_prompt},
                {"type": "image_url", "image_url": {"url": uri2}},
            ]}]
        }
        vision_result = xai_request("chat/completions", vision_payload)
        img2_desc = vision_result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

        fusion_prompt = f"Fuse the following elements into this image while preserving the existing characters and subjects exactly as they appear: {img2_desc}"
        if user_prompt:
            fusion_prompt += f". Style direction: {user_prompt}"

        mime1 = _detect_mime(image1_b64)
        data_uri = _xai_reference_data_uri(image1_b64)
        result = _xai_image_edit(DEFAULT_IMAGE_MODEL, fusion_prompt, data_uri, {"resolution": DEFAULT_IMAGE_RESOLUTION})
        saved = _save_image_results(result, "fusion", fusion_prompt, DEFAULT_IMAGE_MODEL)
        return jsonify({"images": saved, "fusion_prompt": fusion_prompt})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/image/combine-characters", methods=["POST"])
def api_image_combine_characters():
    """Combine characters from two images into a new scene preserving both faces."""
    data = request.json
    image1_b64 = data.get("image1", "")
    image2_b64 = data.get("image2", "")
    scene_prompt = data.get("prompt", "")

    if not image1_b64 or not image2_b64:
        return jsonify({"error": "Two images required"}), 400

    try:
        mime1 = _detect_mime(image1_b64)
        mime2 = _detect_mime(image2_b64)
        uri1 = f"data:{mime1};base64,{image1_b64}"
        uri2 = f"data:{mime2};base64,{image2_b64}"

        char_prompt = "Describe each character/person in these two images with EXTREME precision for visual consistency. For EACH character: exact face shape, eye color/shape, nose, lips, skin tone, hair color/style/length, body build, height impression, clothing, accessories, any distinguishing marks. Label them Character A (image 1) and Character B (image 2). Be exhaustive — this description will be used to recreate them exactly. 4-5 sentences per character."

        vision_payload = {
            "model": DEFAULT_CHAT_MODEL,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": char_prompt},
                {"type": "image_url", "image_url": {"url": uri1}},
                {"type": "image_url", "image_url": {"url": uri2}},
            ]}]
        }
        vision_result = xai_request("chat/completions", vision_payload)
        char_descriptions = vision_result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

        scene = scene_prompt or "both characters together in the same scene, interacting naturally"
        edit_prompt = f"Add the second character into this image while preserving the EXACT face and appearance of the existing character. {char_descriptions}\n\nScene: {scene}. Both characters must appear with their exact original faces, features, and proportions."

        data_uri = _xai_reference_data_uri(image1_b64)
        result = _xai_image_edit(DEFAULT_IMAGE_MODEL, edit_prompt, data_uri, {"resolution": DEFAULT_IMAGE_RESOLUTION})
        saved = _save_image_results(result, "charcombo", edit_prompt[:200], DEFAULT_IMAGE_MODEL)
        return jsonify({"images": saved, "characters": char_descriptions[:500]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/image/upload", methods=["POST"])
def api_image_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    ts = int(time.time() * 1000)
    ext = os.path.splitext(f.filename)[1] or ".png"
    filename = f"upload_{ts}{ext}"
    filepath = UPLOADS_DIR / filename
    f.save(str(filepath))
    return jsonify({"filename": filename, "url": f"/uploads/{filename}"})


@app.route("/api/image/list")
def api_image_list():
    images = []
    for f in sorted(IMAGES_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
            item = {"filename": f.name, "url": f"/images/{f.name}", "created": f.stat().st_mtime}
            item.update(_read_image_metadata(f.name))
            images.append(item)
    return jsonify({"images": images})


@app.route("/api/image/delete", methods=["POST"])
def api_image_delete():
    data = request.json
    filename = data.get("filename", "")
    filepath = IMAGES_DIR / filename
    if filepath.exists() and filepath.parent == IMAGES_DIR:
        filepath.unlink()
        metadata_path = _image_metadata_path(filename)
        if metadata_path.exists():
            metadata_path.unlink()
        return jsonify({"success": True})
    return jsonify({"error": "File not found"}), 404


# ── Routes: Video Generation ─────────────────────────────────────────────────

@app.route("/api/video/generate", methods=["POST"])
def api_video_generate():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON object required"}), 400
    prompt = data.get("prompt", "")
    image_b64 = data.get("image", "")
    if not isinstance(prompt, str) or (not prompt.strip() and not image_b64):
        return jsonify({"error": "Prompt or source image required"}), 400
    try:
        payload = {"prompt": prompt, **_video_options(data, has_image=bool(image_b64))}
        if image_b64:
            payload["image"] = {"url": _xai_reference_data_uri(image_b64)}
        estimate = estimate_media_cost({**data, "kind": "video", "input_images": int(bool(image_b64))})
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    try:
        # A single paid submission. The user must explicitly start another job.
        result = xai_request("videos/generations", payload)
        video_id = result.get("request_id", "") or result.get("id", "") or result.get("job_id", "")
        if not video_id:
            return jsonify({"error": "Provider returned no video request ID"}), 502
        return jsonify({"id": video_id, "status": "processing", "provider": "xai", "model": payload["model"], "estimate": estimate})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/video/poll")
def api_video_poll():
    video_id = request.args.get("id", "")
    if not video_id or len(video_id) > 128 or not all(c.isalnum() or c in "-_" for c in video_id):
        return jsonify({"error": "Valid video ID required"}), 400
    try:
        with _VIDEO_JOB_LOCK:
            cached = _VIDEO_JOB_RESULTS.get(video_id)
            if cached and (VIDEOS_DIR / cached["filename"]).is_file():
                return jsonify(cached)
            result = xai_get(f"videos/{video_id}")
            status = str(result.get("status", "pending")).lower()
            video = result.get("video", {})
            video = video if isinstance(video, dict) else {}
            if video.get("respect_moderation") is False or result.get("respect_moderation") is False:
                return jsonify({"status": "failed", "error": "Content moderation rejected"})
            if status in ("failed", "error", "cancelled", "expired"):
                err = result.get("error", {})
                message = err.get("message", "") if isinstance(err, dict) else str(err)
                return jsonify({"status": status, "error": message or f"Video {status}"})
            if status not in ("done", "completed", "complete", "succeeded"):
                return jsonify({"status": status})
            video_url = video.get("url", "")
            if not video_url:
                items = result.get("data", [])
                if isinstance(items, list) and items and isinstance(items[0], dict):
                    video_url = items[0].get("url", "")
            if not video_url:
                for key in ("output", "result", "video_url", "url"):
                    value = result.get(key)
                    if isinstance(value, str):
                        video_url = value
                    elif isinstance(value, dict):
                        video_url = value.get("url", "")
                    if video_url:
                        break
            if not video_url:
                return jsonify({"status": "processing", "detail": "Waiting for provider download URL"})
            parsed = urllib.parse.urlsplit(video_url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                return jsonify({"status": "failed", "error": "Provider returned an invalid download URL"}), 502
            filename = f"video_{uuid.uuid4().hex}.mp4"
            req = urllib.request.Request(video_url)
            req.add_header("User-Agent", "dork/1.0")
            with urllib.request.urlopen(req, timeout=120) as response:
                content = response.read(512 * 1024 * 1024 + 1)
            if not content or len(content) > 512 * 1024 * 1024:
                return jsonify({"status": "failed", "error": "Provider video is empty or exceeds 512 MB"}), 502
            (VIDEOS_DIR / filename).write_bytes(content)
            completed = {"status": "completed", "filename": filename, "url": f"/videos/{filename}"}
            if len(_VIDEO_JOB_RESULTS) >= 256:
                _VIDEO_JOB_RESULTS.pop(next(iter(_VIDEO_JOB_RESULTS)))
            _VIDEO_JOB_RESULTS[video_id] = completed
            return jsonify(completed)
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/video/freeze", methods=["POST"])
def api_video_freeze():
    """Freeze a video frame and save as image."""
    data = request.json
    image_data = data.get("image", "")
    if not image_data:
        return jsonify({"error": "No image data"}), 400
    if "," in image_data:
        image_data = image_data.split(",", 1)[1]
    ts = int(time.time() * 1000)
    filename = f"frame_{ts}.png"
    filepath = IMAGES_DIR / filename
    filepath.write_bytes(base64.b64decode(image_data))
    return jsonify({"filename": filename, "url": f"/images/{filename}"})


@app.route("/api/video/lastframe", methods=["POST"])
def api_video_lastframe():
    """Extract the last frame from a video file and save as an image."""
    data = request.json
    filename = data.get("filename", "")
    if not filename:
        return jsonify({"error": "Filename required"}), 400
    video_path = VIDEOS_DIR / Path(filename).name
    if not video_path.exists():
        return jsonify({"error": "Video not found"}), 404

    ts = int(time.time() * 1000)
    frame_filename = f"frame_{ts}.png"
    frame_path = IMAGES_DIR / frame_filename

    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-sseof", "-0.1", "-i", str(video_path),
             "-update", "1", "-frames:v", "1", str(frame_path)],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0 or not frame_path.exists():
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
                capture_output=True, text=True, timeout=10
            )
            duration = float(result.stdout.strip()) - 0.05
            subprocess.run(
                ["ffmpeg", "-y", "-ss", str(max(0, duration)), "-i", str(video_path),
                 "-frames:v", "1", str(frame_path)],
                capture_output=True, text=True, timeout=30
            )

        if not frame_path.exists():
            return jsonify({"error": "Failed to extract frame"}), 500

        frame_b64 = base64.b64encode(frame_path.read_bytes()).decode()
        return jsonify({
            "filename": frame_filename,
            "url": f"/images/{frame_filename}",
            "base64": frame_b64,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/video/delete", methods=["POST"])
def api_video_delete():
    data = request.json
    filename = data.get("filename", "")
    filepath = VIDEOS_DIR / Path(filename).name
    if filepath.exists() and filepath.parent == VIDEOS_DIR:
        filepath.unlink()
        return jsonify({"success": True})
    return jsonify({"error": "File not found"}), 404


@app.route("/api/video/list")
def api_video_list():
    videos = []
    for f in sorted(VIDEOS_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.suffix.lower() in (".mp4", ".webm", ".mov"):
            videos.append({"filename": f.name, "url": f"/videos/{f.name}", "created": f.stat().st_mtime})
    return jsonify({"videos": videos})


@app.route("/api/video/stitch", methods=["POST"])
def api_video_stitch():
    """Stitch multiple videos together via ffmpeg."""
    data = request.json
    filenames = data.get("videos", [])
    if len(filenames) < 2:
        return jsonify({"error": "Need at least 2 videos"}), 400

    paths = []
    for name in filenames:
        p = VIDEOS_DIR / Path(name).name
        if not p.exists():
            return jsonify({"error": f"Not found: {name}"}), 404
        paths.append(str(p))

    stitch_id = str(uuid.uuid4())[:8]
    output_filename = f"stitch_{stitch_id}.mp4"
    output_path = VIDEOS_DIR / output_filename

    try:
        concat_path = VIDEOS_DIR / f".concat_{stitch_id}.txt"
        concat_path.write_text("\n".join(f"file '{p}'" for p in paths))

        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path), "-c", "copy", str(output_path)],
            capture_output=True, text=True, timeout=60
        )
        concat_path.unlink(missing_ok=True)

        if result.returncode != 0:
            # Retry with re-encoding
            concat_path.write_text("\n".join(f"file '{p}'" for p in paths))
            result = subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path),
                 "-c:v", "libx264", "-crf", "23", "-preset", "fast", "-c:a", "aac", str(output_path)],
                capture_output=True, text=True, timeout=120
            )
            concat_path.unlink(missing_ok=True)
            if result.returncode != 0:
                return jsonify({"error": f"ffmpeg failed: {result.stderr[:200]}"}), 500

        return jsonify({"filename": output_filename, "url": f"/videos/{output_filename}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Routes: Voice / TTS ──────────────────────────────────────────────────────

@app.route("/api/voice/speak", methods=["POST"])
def api_voice_speak():
    """TTS via POST /v1/tts — xAI native TTS endpoint."""
    data = request.json
    text = data.get("text", "")
    voice_id = data.get("voice_id", "eve")
    language = data.get("language", "en")

    if not text:
        return jsonify({"error": "Text required"}), 400

    try:
        api_key = get_api_key()
        if not api_key:
            return jsonify({"error": "No API key configured"}), 400

        payload = json.dumps({
            "text": text,
            "voice_id": voice_id,
            "language": language,
        }).encode("utf-8")

        url = f"{XAI_BASE}/tts"
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "DorkDirector/1.0")

        try:
            resp = urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as e:
            raise ValueError(_parse_xai_error(e))

        audio_data = resp.read()
        ts = int(time.time() * 1000)
        filename = f"speech_{ts}.mp3"
        filepath = AUDIO_DIR / filename
        filepath.write_bytes(audio_data)
        return jsonify({"filename": filename, "url": f"/audio/{filename}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/voice/speak-openai", methods=["POST"])
def api_voice_speak_openai():
    """TTS via OpenAI's gpt-4o-mini-tts model."""
    data = request.json
    text = data.get("text", "")
    voice = data.get("voice", "alloy")

    if not text:
        return jsonify({"error": "Text required"}), 400

    try:
        api_key = get_openai_api_key()
        if not api_key:
            return jsonify({"error": "No OpenAI API key configured"}), 400

        payload = json.dumps({
            "model": "gpt-4o-mini-tts",
            "input": text,
            "voice": voice,
            "response_format": "mp3",
        }).encode("utf-8")

        url = f"{OPENAI_BASE}/audio/speech"
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "DorkDirector/1.0")

        try:
            resp = urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as e:
            raise ValueError(_parse_openai_error(e))

        audio_data = resp.read()
        ts = int(time.time() * 1000)
        filename = f"openai_speech_{ts}.mp3"
        filepath = AUDIO_DIR / filename
        filepath.write_bytes(audio_data)
        return jsonify({"filename": filename, "url": f"/audio/{filename}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/voice/list")
def api_voice_list():
    audio_files = []
    for f in sorted(AUDIO_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.suffix.lower() in (".mp3", ".wav", ".ogg"):
            audio_files.append({"filename": f.name, "url": f"/audio/{f.name}", "created": f.stat().st_mtime})
    return jsonify({"files": audio_files})


@app.route("/api/voice/delete", methods=["POST"])
def api_voice_delete():
    filename = request.json.get("filename", "")
    filepath = AUDIO_DIR / filename
    if filepath.exists() and filepath.parent == AUDIO_DIR:
        filepath.unlink()
        return jsonify({"deleted": True})
    return jsonify({"error": "Not found"}), 404


# ── Routes: Voice Agent (Realtime) ───────────────────────────────────────────

@app.route("/api/realtime/token", methods=["POST"])
def api_realtime_token():
    """Get ephemeral token for voice agent WebSocket."""
    try:
        api_key = get_api_key()
        if not api_key:
            return jsonify({"error": "No API key configured"}), 400

        payload = json.dumps({}).encode("utf-8")
        url = f"{XAI_BASE}/realtime/client_secrets"
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "DorkDirector/1.0")

        try:
            resp = urllib.request.urlopen(req, timeout=15)
        except urllib.error.HTTPError as e:
            raise ValueError(_parse_xai_error(e))

        data = json.loads(resp.read().decode("utf-8"))
        # Token is in "value" field
        return jsonify({"token": data.get("value", ""), "expires_at": data.get("expires_at", 0)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Routes: Collections ──────────────────────────────────────────────────────

@app.route("/api/collections", methods=["GET", "POST"])
def api_collections():
    if request.method == "GET":
        try:
            result = xai_get("collections")
            raw = result.get("collections", [])
            normalized = []
            for c in raw:
                normalized.append({
                    "id": c.get("collection_id", c.get("id", "")),
                    "name": c.get("collection_name", c.get("name", "")),
                    "description": c.get("collection_description", c.get("description", "")),
                    "total_documents": c.get("documents_count", c.get("total_documents", 0)),
                    "created_at": c.get("created_at", ""),
                })
            return jsonify({"collections": normalized})
        except Exception as e:
            return jsonify({"error": str(e), "collections": []}), 200
    else:
        data = request.json
        name = data.get("name", "")
        description = data.get("description", "")
        try:
            payload = {"name": name}
            if description:
                payload["description"] = description
            result = xai_request("collections", payload)
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": str(e)}), 500


@app.route("/api/collections/<collection_id>/documents", methods=["POST"])
def api_collection_upload(collection_id):
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    try:
        result = _upload_file_to_collection(f.filename, f.read(), "application/octet-stream", collection_id)
        _collection_cache.pop(collection_id, None)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/collections/<collection_id>", methods=["DELETE"])
def api_collection_delete(collection_id):
    try:
        api_key = get_api_key()
        url = f"{XAI_BASE}/collections/{collection_id}"
        req = urllib.request.Request(url, method="DELETE")
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("User-Agent", "DorkDirector/1.0")
        urllib.request.urlopen(req, timeout=60)
        return jsonify({"status": "deleted"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Routes: Artifacts ─────────────────────────────────────────────────────────

@app.route("/api/artifacts/save", methods=["POST"])
def api_artifact_save():
    data = request.json
    title = data.get("title", "Untitled")
    html = data.get("html", "")
    css = data.get("css", "")
    js = data.get("js", "")
    source_model = data.get("model", "")

    ts = int(time.time() * 1000)
    slug = "".join(c if c.isalnum() or c in "-_ " else "" for c in title)[:40].strip().replace(" ", "-").lower()
    filename = f"{slug}_{ts}.html"

    # Build standalone HTML
    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<!-- dork Artifact | model: {source_model} | created: {time.strftime('%Y-%m-%d %H:%M')} -->
<style>
{css}
</style>
</head>
<body>
{html}
<script>
{js}
</script>
</body>
</html>"""

    filepath = ARTIFACTS_DIR / filename
    filepath.write_text(doc)

    # Save metadata sidecar
    meta = {"title": title, "filename": filename, "model": source_model, "created": time.time()}
    meta_path = ARTIFACTS_DIR / f"{filename}.json"
    meta_path.write_text(json.dumps(meta))

    return jsonify({"filename": filename, "url": f"/artifacts/{filename}", "title": title})


@app.route("/api/artifacts/list")
def api_artifact_list():
    artifacts = []
    for f in sorted(ARTIFACTS_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.suffix == ".html":
            meta_path = ARTIFACTS_DIR / f"{f.name}.json"
            meta = {}
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text())
                except Exception:
                    pass
            artifacts.append({
                "filename": f.name,
                "url": f"/artifacts/{f.name}",
                "title": meta.get("title", f.stem),
                "model": meta.get("model", ""),
                "created": meta.get("created", f.stat().st_mtime),
            })
    return jsonify({"artifacts": artifacts})


@app.route("/api/artifacts/delete", methods=["POST"])
def api_artifact_delete():
    data = request.json
    filename = data.get("filename", "")
    filepath = ARTIFACTS_DIR / filename
    meta_path = ARTIFACTS_DIR / f"{filename}.json"
    if filepath.exists():
        filepath.unlink()
        if meta_path.exists():
            meta_path.unlink()
        return jsonify({"status": "deleted"})
    return jsonify({"error": "Not found"}), 404


@app.route("/artifacts/<path:filename>")
def serve_artifact(filename):
    return send_from_directory(str(ARTIFACTS_DIR), filename)


# ── Routes: Skills ────────────────────────────────────────────────────────────

@app.route("/api/skills/save", methods=["POST"])
def api_skill_save():
    data = request.json
    name = data.get("name", "")
    description = data.get("description", "")
    skill_type = data.get("type", "instruction")
    content = data.get("content", "")
    collection_id = data.get("collection_id", "")

    if not name or not content:
        return jsonify({"error": "Name and content required"}), 400

    # Build markdown with frontmatter
    md = f"""---
name: {name}
description: |
  {description}
type: {skill_type}
created: {time.strftime('%Y-%m-%dT%H:%M:%S')}
---

{content}
"""

    slug = "".join(c if c.isalnum() or c in "-_ " else "" for c in name)[:40].strip().replace(" ", "-").lower()
    filename = f"{slug}.md"
    filepath = SKILLS_DIR / filename
    filepath.write_text(md)

    result = {"filename": filename, "name": name}

    # Upload to collection if specified
    if collection_id:
        try:
            _upload_file_to_collection(filename, md.encode("utf-8"), "text/markdown", collection_id)
            result["uploaded"] = True
            _collection_cache.pop(collection_id, None)
        except Exception as e:
            result["upload_error"] = str(e)

    return jsonify(result)


@app.route("/api/skills/list")
def api_skill_list():
    skills = []
    for f in sorted(SKILLS_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.suffix == ".md":
            text = f.read_text()
            meta = _parse_frontmatter(text)
            skills.append({
                "filename": f.name,
                "name": meta.get("name", f.stem),
                "description": meta.get("description", ""),
                "type": meta.get("type", "instruction"),
                "created": meta.get("created", ""),
            })
    return jsonify({"skills": skills})


@app.route("/api/skills/<filename>")
def api_skill_get(filename):
    filepath = SKILLS_DIR / filename
    if not filepath.exists():
        return jsonify({"error": "Not found"}), 404
    text = filepath.read_text()
    meta = _parse_frontmatter(text)
    # Extract body (after second ---)
    parts = text.split("---", 2)
    body = parts[2].strip() if len(parts) >= 3 else text
    return jsonify({"filename": filename, "body": body, **meta})


@app.route("/api/skills/delete", methods=["POST"])
def api_skill_delete():
    data = request.json
    filename = data.get("filename", "")
    filepath = SKILLS_DIR / filename
    if filepath.exists():
        filepath.unlink()
        return jsonify({"status": "deleted"})
    return jsonify({"error": "Not found"}), 404


def _parse_frontmatter(text):
    """Parse YAML-like frontmatter from markdown."""
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    meta = {}
    current_key = None
    for line in parts[1].strip().split("\n"):
        if ":" in line and not line.startswith(" "):
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if val == "|":
                current_key = key
                meta[key] = ""
            else:
                meta[key] = val
                current_key = None
        elif current_key and line.startswith("  "):
            meta[current_key] += line.strip() + " "
    # Clean up trailing spaces
    for k in meta:
        if isinstance(meta[k], str):
            meta[k] = meta[k].strip()
    return meta


# ── Routes: File Serving ─────────────────────────────────────────────────────

@app.route("/images/<path:filename>")
def serve_image(filename):
    return send_from_directory(str(IMAGES_DIR), filename)

@app.route("/uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(str(UPLOADS_DIR), filename)

@app.route("/videos/<path:filename>")
def serve_video(filename):
    return send_from_directory(str(VIDEOS_DIR), filename)

@app.route("/audio/<path:filename>")
def serve_audio(filename):
    return send_from_directory(str(AUDIO_DIR), filename)


@app.route("/api/delete", methods=["POST"])
def api_delete():
    data = request.json
    filename = data.get("filename", "")
    file_type = data.get("type", "image")
    dirs = {"image": IMAGES_DIR, "video": VIDEOS_DIR, "audio": AUDIO_DIR, "upload": UPLOADS_DIR}
    target_dir = dirs.get(file_type, IMAGES_DIR)
    filepath = target_dir / filename
    if filepath.exists():
        filepath.unlink()
        return jsonify({"status": "deleted"})
    return jsonify({"error": "Not found"}), 404


# ── Asset Library (Characters + Styles, ported from dork+ios) ───────────────
# Persistent character/style references with active toggles. Active items
# auto-attach to image and video generations as reference images.

def _asset_lib_load():
    if ASSET_LIB_INDEX.exists():
        try:
            return json.loads(ASSET_LIB_INDEX.read_text())
        except Exception:
            pass
    return {"items": []}


def _asset_lib_save(data):
    ASSET_LIB_INDEX.write_text(json.dumps(data, indent=2))


def _asset_lib_ext_from_data_url(data_url):
    low = (data_url or "").lower()
    if low.startswith("data:image/jpeg") or low.startswith("data:image/jpg"):
        return "jpg"
    if low.startswith("data:image/webp"):
        return "webp"
    if low.startswith("data:image/gif"):
        return "gif"
    return "png"


def _asset_lib_mime_from_ext(ext):
    return {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "webp": "image/webp", "gif": "image/gif"}.get(ext.lower(), "image/png")


@app.route("/api/asset-library", methods=["GET"])
def api_asset_lib_list():
    return jsonify(_asset_lib_load())


@app.route("/api/asset-library", methods=["POST"])
def api_asset_lib_add():
    data = request.json or {}
    name = (data.get("name") or "Untitled").strip()[:60] or "Untitled"
    asset_type = data.get("type", "character")
    if asset_type not in ("character", "style"):
        asset_type = "character"
    tags = (data.get("tags") or "").strip()
    image_data = data.get("image", "") or ""
    if not image_data:
        return jsonify({"error": "no image"}), 400
    orig = image_data
    if image_data.startswith("data:") and "," in image_data:
        image_data = image_data.split(",", 1)[1]
    ext = _asset_lib_ext_from_data_url(orig)
    item_id = uuid.uuid4().hex[:12]
    fname = f"{item_id}.{ext}"
    fpath = ASSET_LIB_DIR / fname
    try:
        fpath.write_bytes(base64.b64decode(image_data))
    except Exception as e:
        return jsonify({"error": f"file write: {e}"}), 500
    idx = _asset_lib_load()
    item = {"id": item_id, "name": name, "type": asset_type, "tags": tags,
            "file": fname, "created": int(time.time()), "active": False}
    idx["items"].insert(0, item)
    _asset_lib_save(idx)
    return jsonify(item)


@app.route("/api/asset-library/toggle", methods=["POST"])
def api_asset_lib_toggle():
    data = request.json or {}
    iid = data.get("id")
    idx = _asset_lib_load()
    target = next((i for i in idx["items"] if i["id"] == iid), None)
    if not target:
        return jsonify({"error": "not found"}), 404
    target["active"] = not target.get("active", False)
    _asset_lib_save(idx)
    return jsonify(idx)


@app.route("/api/asset-library/rename", methods=["POST"])
def api_asset_lib_rename():
    data = request.json or {}
    idx = _asset_lib_load()
    item = next((i for i in idx["items"] if i["id"] == data.get("id")), None)
    if not item:
        return jsonify({"error": "not found"}), 404
    item["name"] = (data.get("name") or "Untitled").strip()[:60]
    if "tags" in data:
        item["tags"] = (data.get("tags") or "")
    _asset_lib_save(idx)
    return jsonify(item)


@app.route("/api/asset-library/delete", methods=["POST"])
def api_asset_lib_delete():
    data = request.json or {}
    iid = data.get("id")
    if not iid:
        return jsonify({"error": "no id"}), 400
    idx = _asset_lib_load()
    item = next((i for i in idx["items"] if i["id"] == iid), None)
    if item:
        fpath = ASSET_LIB_DIR / item["file"]
        if fpath.exists():
            try:
                fpath.unlink()
            except Exception:
                pass
        idx["items"] = [i for i in idx["items"] if i["id"] != iid]
        _asset_lib_save(idx)
    return jsonify({"ok": True})


@app.route("/api/asset-library/dataurl/<item_id>")
def api_asset_lib_dataurl(item_id):
    idx = _asset_lib_load()
    item = next((i for i in idx["items"] if i["id"] == item_id), None)
    if not item:
        return jsonify({"error": "not found"}), 404
    fpath = ASSET_LIB_DIR / item["file"]
    if not fpath.exists():
        return jsonify({"error": "file missing"}), 404
    raw = fpath.read_bytes()
    ext = item["file"].rsplit(".", 1)[-1].lower()
    mime = _asset_lib_mime_from_ext(ext)
    b64 = base64.b64encode(raw).decode("ascii")
    return jsonify({"data_url": f"data:{mime};base64,{b64}"})


@app.route("/asset-library/<item_id>")
def asset_lib_serve(item_id):
    idx = _asset_lib_load()
    item = next((i for i in idx["items"] if i["id"] == item_id), None)
    if not item:
        return ("", 404)
    fpath = ASSET_LIB_DIR / item["file"]
    if not fpath.exists():
        return ("", 404)
    return send_from_directory(str(ASSET_LIB_DIR), item["file"])


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import threading
    import webbrowser
    from werkzeug.serving import make_server
    parser = argparse.ArgumentParser(description="Run the local dork studio")
    parser.add_argument("--port", type=int, default=0, help="0 selects a free local port")
    parser.add_argument("--open", action="store_true", help="Open the studio in your browser")
    options = parser.parse_args()
    if not 0 <= options.port <= 65535:
        parser.error("port must be between 0 and 65535")
    with make_server("127.0.0.1", options.port, app, threaded=True) as server:
        url = f"http://127.0.0.1:{server.server_port}"
        print(f"dork: {url}", flush=True)
        if options.open:
            threading.Timer(0.4, lambda: webbrowser.open(url)).start()
        server.serve_forever()
