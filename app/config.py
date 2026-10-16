from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "cutflow.db"
JOBS_DIR = DATA_DIR / "jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "2048"))
MAX_VIDEO_MINUTES = int(os.getenv("MAX_VIDEO_MINUTES", "180"))
MAX_CLIPS = int(os.getenv("MAX_CLIPS", "12"))
OUTPUT_CRF = int(os.getenv("OUTPUT_CRF", "22"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "").strip()
WHISPER_ENABLED = os.getenv("WHISPER_ENABLED", "true").lower() in {"1", "true", "yes"}
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)
YTDLP_COOKIES_FILE = os.getenv("YTDLP_COOKIES_FILE", "").strip()
YTDLP_PROXY = os.getenv("YTDLP_PROXY", "").strip()

PRESETS = {
    "tiktok": {"label": "TikTok", "width": 1080, "height": 1920, "video_bitrate": "6500k", "audio_bitrate": "160k", "safe_bottom": 240},
    "reels": {"label": "Instagram Reels", "width": 1080, "height": 1920, "video_bitrate": "6000k", "audio_bitrate": "160k", "safe_bottom": 220},
    "shorts": {"label": "YouTube Shorts", "width": 1080, "height": 1920, "video_bitrate": "6500k", "audio_bitrate": "160k", "safe_bottom": 180},
}
