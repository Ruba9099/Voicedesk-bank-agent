from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "VoiceDesk Bank Agent"
    version: str = "1.0.0"
    bank_name: str = "Demo National Bank"
    # Fictional demo helpline number (not a real bank line).
    bank_phone: str = "+92-42-111-000-000"
    demo_mode: bool = True

    database_url: str = "sqlite:///./voicedesk.db"
    api_key: str = "change-me"
    cnic_pepper: str = "change-me-pepper"
    seed_demo_data: bool = True
    cors_origins: str = "*"

    # Routing: how long an operator may let a call ring before the agent takes over.
    ring_timeout_seconds: int = 20
    sweep_interval_seconds: float = 1.0

    # Security policy
    max_auth_attempts_per_call: int = 3
    max_failed_attempts_per_customer: int = 5
    lockout_minutes: int = 15
    max_unknown_turns: int = 3
    max_total_errors: int = 8
    complaint_sla_hours: int = 24

    # Telephony (Twilio-compatible webhook). Empty token = signature check off.
    twilio_auth_token: str = ""
    public_base_url: str = ""
    operator_dial_number: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
