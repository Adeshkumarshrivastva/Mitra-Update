from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
PUBLIC_DIR = BASE_DIR / "public"
LOG_DIR = BASE_DIR / "logs"
ENV_PATH = BASE_DIR / ".env"

# Doctors' line. Mind Check escalation always places the IVR/AI-agent call to this number (not configurable).
DOCTOR_IVR_NUMBER = "8920530832"

# Static for now: no Dhwani request is made, the doctor call is simulated. Flip to False when Dhwani is wired in.
DOCTOR_CALL_STATIC = True

STT_PROVIDERS = {"browser", "elevenlabs", "gemini"}
TTS_PROVIDERS = {"elevenlabs", "edge"}
LLM_PROVIDERS = {"gemini"}


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
    ice_servers: str
    login_pin: str
    healthcare_enabled: bool
    dhwani_call_api_key: str
    dhwani_call_base_url: str
    dhwani_call_agent: str
    healthcare_driver_number: str
    healthcare_support_number: str
    dialer_api_key: str
    dialer_api_url: str
    dialer_api_token: str
    transfer_call_url: str
    dialer_bridge_url: str
    dialer_caller_id: str
    human_agent_number: str
    stt_provider: str
    tts_provider: str
    edge_tts_voice: str
    llm_provider: str
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
            # Comma-separated STUN/TURN URIs. Browser clients on the same LAN
            # as the server got away with none; a phone on cellular data needs
            # at least a STUN server to gather a usable ICE candidate.
            ice_servers=os.getenv("ICE_SERVERS", "stun:stun.l.google.com:19302").strip(),
            login_pin=os.getenv("MITRA_LOGIN_PIN", "1234").strip(),
            healthcare_enabled=env_bool("HEALTHCARE_ENABLED", True),
            dhwani_call_api_key=os.getenv("DHWANI_CALL_API_KEY", "").strip(),
            dhwani_call_base_url=(
                os.getenv("DHWANI_CALL_BASE_URL", "https://dhwani.timbleglance.com").strip()
                or "https://dhwani.timbleglance.com"
            ).rstrip("/"),
            dhwani_call_agent=os.getenv("DHWANI_CALL_AGENT", "default").strip() or "default",
            # Hardcoded driver number for testing. Dhwani calls THIS number.
            healthcare_driver_number=os.getenv("HEALTHCARE_DRIVER_NUMBER", "6265833992").strip() or "6265833992",
            # Conceptual healthcare line only. NOT dialed during testing.
            healthcare_support_number=os.getenv("HEALTHCARE_SUPPORT_NUMBER", "8920530832").strip() or "8920530832",
            dialer_api_key=os.getenv("DIALER_API_KEY", "").strip(),
            dialer_api_url=(
                os.getenv("DIALER_API_URL", "https://api.acefone.in/v1/click_to_call_support").strip()
                or "https://api.acefone.in/v1/click_to_call_support"
            ),
            dialer_api_token=os.getenv("DIALER_API_TOKEN", "").strip(),
            transfer_call_url=(
                os.getenv("TRANSFER_CALL_URL", "https://api.acefone.in/v1/call/options").strip()
                or "https://api.acefone.in/v1/call/options"
            ),
            dialer_bridge_url=(
                os.getenv("DIALER_BRIDGE_URL", "https://api.acefone.in/v1/click_to_call").strip()
                or "https://api.acefone.in/v1/click_to_call"
            ),
            dialer_caller_id=os.getenv("DIALER_CALLER_ID", "").strip(),
            # Human agent connected into the driver's call for the "Human Agent" preference.
            human_agent_number=os.getenv("HUMAN_AGENT_NUMBER", "6265833992").strip() or "6265833992",
            stt_provider=os.getenv("STT_PROVIDER", "elevenlabs").strip().lower() or "elevenlabs",
            tts_provider=os.getenv("TTS_PROVIDER", "elevenlabs").strip().lower() or "elevenlabs",
            edge_tts_voice=os.getenv("EDGE_TTS_VOICE", "hi-IN-SwaraNeural").strip() or "hi-IN-SwaraNeural",
            llm_provider=os.getenv("LLM_PROVIDER", "gemini").strip().lower() or "gemini",
        )

    def healthcare_call_ready(self) -> bool:
        return self.healthcare_enabled and bool(self.dhwani_call_api_key) and bool(self.healthcare_driver_number)

    def doctor_call_ready(self) -> bool:
        return self.healthcare_enabled and bool(self.dhwani_call_api_key)

    def human_call_ready(self) -> bool:
        # The click_to_call bridge is authenticated with the Bearer API token.
        return (
            self.healthcare_enabled
            and bool(self.dialer_api_token)
            and bool(self.dialer_bridge_url)
            and bool(self.healthcare_driver_number)
            and bool(self.human_agent_number)
        )

    def require_voice_pipeline(self) -> None:
        if self.stt_provider not in STT_PROVIDERS:
            raise RuntimeError(f"STT_PROVIDER must be one of: {', '.join(sorted(STT_PROVIDERS))}")
        if self.tts_provider not in TTS_PROVIDERS:
            raise RuntimeError(f"TTS_PROVIDER must be one of: {', '.join(sorted(TTS_PROVIDERS))}")
        if self.llm_provider not in LLM_PROVIDERS:
            raise RuntimeError(f"LLM_PROVIDER must be one of: {', '.join(sorted(LLM_PROVIDERS))}")

        missing = []
        if "elevenlabs" in {self.stt_provider, self.tts_provider} and not self.elevenlabs_api_key:
            missing.append("ELEVENLABS_API_KEY")
        if self.stt_provider == "elevenlabs" and not self.elevenlabs_stt_model:
            missing.append("ELEVENLABS_STT_MODEL")
        if self.tts_provider == "elevenlabs" and not self.elevenlabs_tts_model:
            missing.append("ELEVENLABS_TTS_MODEL")
        if self.tts_provider == "elevenlabs" and not self.elevenlabs_tts_voice_id:
            missing.append("ELEVENLABS_TTS_VOICE_ID")
        uses_gemini = "gemini" in {self.llm_provider, self.stt_provider}
        if uses_gemini and not self.gemini_api_key:
            missing.append("GEMINI_API_KEY")
        if uses_gemini and not self.gemini_model:
            missing.append("GEMINI_MODEL")

        if missing:
            raise RuntimeError(f"Missing required configuration: {', '.join(missing)}")
