from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
PUBLIC_DIR = BASE_DIR / "public"
LOG_DIR = BASE_DIR / "logs"
ENV_PATH = BASE_DIR / ".env"


def load_env(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


@dataclass(frozen=True)
class Settings:
    use_dhwani: bool
    elevenlabs_api_key: str
    elevenlabs_stt_model: str
    elevenlabs_tts_model: str
    elevenlabs_tts_voice_id: str
    gemini_api_key: str
    gemini_model: str
    app_host: str
    app_port: int
    login_pin: str
    public_dir: Path = PUBLIC_DIR
    log_dir: Path = LOG_DIR

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            use_dhwani=env_bool("USE_DHWANI", False),
            elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY", "").strip(),
            elevenlabs_stt_model=os.getenv("ELEVENLABS_STT_MODEL", "scribe_v2").strip() or "scribe_v2",
            elevenlabs_tts_model=os.getenv("ELEVENLABS_TTS_MODEL", "").strip(),
            elevenlabs_tts_voice_id=os.getenv("ELEVENLABS_TTS_VOICE_ID", "").strip(),
            gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite").strip() or "gemini-3.1-flash-lite",
            app_host=os.getenv("APP_HOST", "0.0.0.0").strip() or "0.0.0.0",
            app_port=env_int("APP_PORT", 8000),
            login_pin=os.getenv("MITRA_LOGIN_PIN", "1234").strip(),
        )

    def require_voice_pipeline(self) -> None:
        missing = []
        if not self.elevenlabs_api_key:
            missing.append("ELEVENLABS_API_KEY")
        if not self.elevenlabs_stt_model:
            missing.append("ELEVENLABS_STT_MODEL")
        if not self.elevenlabs_tts_model:
            missing.append("ELEVENLABS_TTS_MODEL")
        if not self.elevenlabs_tts_voice_id:
            missing.append("ELEVENLABS_TTS_VOICE_ID")
        if not self.gemini_api_key:
            missing.append("GEMINI_API_KEY")
        if not self.gemini_model:
            missing.append("GEMINI_MODEL")

        if missing:
            raise RuntimeError(f"Missing required configuration: {', '.join(missing)}")
