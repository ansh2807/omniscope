"""Central configuration. Everything is env-driven so the same image runs in dev and prod."""
from __future__ import annotations

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Anchor relative paths to the project root so imports work from any CWD.
_ROOT = Path(__file__).resolve().parents[1]
_DATA = _ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ROOT / ".env"),
        extra="ignore",
    )

    app_name: str = "OMNISCOPE"
    database_url: str = f"sqlite:///{(_DATA / 'creatorintel.db').as_posix()}"
    reports_dir: str = str(_DATA / "reports")
    documents_dir: str = str(_DATA / "documents")
    cache_dir: str = str(_DATA / "cache")
    max_document_mb: int = 8
    public_base_url: str = "http://localhost:8000"
    api_keys: str = "dev-key-change-me"

    # politeness
    user_agent: str = "CreatorIntelBot/1.0 (+https://example.com/bot)"
    request_timeout: int = 20
    max_concurrency: int = 4
    per_host_delay: float = 1.5
    respect_robots: bool = True
    cache_ttl_hours: int = 24

    # storage hygiene — reports are ephemeral; download before the timer ends
    report_ttl_minutes: int = 1440    # 24 hours so hubs, watch and digest can be used
    retention_days: int = 0           # fallback age window when ttl minutes is 0
    max_reports: int = 200            # hard cap on stored reports (0 = unlimited)
    max_cache_mb: int = 500           # prune the HTTP cache above this size

    # browser tier — renders public pages logged out, the way a visitor sees them.
    # This is what removes the need for a YouTube API key.
    browser_mode: str = "auto"          # off | auto | always
    browser_headless: bool = True
    browser_timeout_ms: int = 30000
    browser_user_agent: str = ""
    browser_max_comment_videos: int = 6

    # ---------- commercial ----------
    deployment_mode: str = "saas"        # saas | selfhost
    app_version: str = "8.23.0"

    # Public product — no customer accounts. SMTP empty = skip send; reports still expire.
    public_email_mode: bool = True
    # Empty date = free with no sunset. Paid gates stay off unless paid_enforced is true.
    free_until: str = ""
    paid_enforced: bool = False
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_secure: bool = True
    # Optional prose. Empty key = DESK stays deterministic.
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    admin_token: str = ""                # separate from customer keys; required for /admin
    signup_open: bool = False
    trial_days: int = 7
    trial_reports: int = 3

    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""

    # self-hosted instances phone this server to validate their licence
    license_server_url: str = ""
    license_key: str = ""
    license_grace_days: int = 14
    update_channel: str = "stable"

    # sources
    youtube_api_key: str = ""
    search_provider: str = "none"
    search_ensemble: bool = True       # query every configured provider, selected one first
    search_max_providers: int = 3
    discovery_query_budget: int = 36
    discovery_concurrency: int = 4
    website_max_pages: int = 6
    serper_api_key: str = ""
    brave_api_key: str = ""
    google_cse_key: str = ""
    google_cse_cx: str = ""
    ig_provider: str = "none"
    ig_provider_url: str = ""
    ig_provider_key: str = ""
    watch_interval_minutes: int = 0   # 0 = manual sweep only

    @property
    def key_set(self) -> set[str]:
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}

    @property
    def free_until_label(self) -> str:
        raw = (self.free_until or "").strip()
        if not raw:
            return ""
        try:
            year, month, day = (int(part) for part in raw.split("-"))
            months = ("January", "February", "March", "April", "May", "June",
                      "July", "August", "September", "October", "November",
                      "December")
            return f"{day} {months[month - 1]} {year}"
        except (ValueError, IndexError):
            return raw

    @property
    def report_ttl_label(self) -> str:
        minutes = int(self.report_ttl_minutes or 0)
        if minutes <= 0:
            return "until purged"
        if minutes % 1440 == 0:
            days = minutes // 1440
            return "1 day" if days == 1 else f"{days} days"
        if minutes % 60 == 0:
            hours = minutes // 60
            return "1 hour" if hours == 1 else f"{hours} hours"
        return f"{minutes} minutes"

    def ensure_dirs(self) -> None:
        Path(self.reports_dir).mkdir(parents=True, exist_ok=True)
        Path(self.cache_dir).mkdir(parents=True, exist_ok=True)
        Path(self.documents_dir).mkdir(parents=True, exist_ok=True)
        _DATA.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
