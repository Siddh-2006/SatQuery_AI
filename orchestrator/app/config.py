"""
app/config.py
==============
Every environment variable the orchestrator reads, in one place, read
exactly once into a single `Settings` object (`settings`, at the bottom of
this file). Every other module does `from app.config import settings` and
never calls `os.environ.get(...)` directly -- that keeps "what can be
configured" answerable by reading one file, and means changing a default
never requires hunting through the codebase.

See `orchestrator/DESIGN.md` §11 for what each variable means and
`orchestrator/.env.example` for a copy-pasteable template.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

# Directory this file lives in: orchestrator/app/. Used to make every
# relative default below resolve the same way regardless of the process's
# current working directory (important once this runs inside Docker).
_APP_DIR = Path(__file__).resolve().parent
_ORCHESTRATOR_DIR = _APP_DIR.parent
_REPO_ROOT = _ORCHESTRATOR_DIR.parent


def _env(name: str, default: str) -> str:
    """Small wrapper so every read is `_env("X", "default")` -- consistent,
    greppable, and gives every setting a visible default in this file even
    when the environment doesn't set it."""
    return os.environ.get(name, default)


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    # -- LLM backend switch (DESIGN.md §3) -----------------------------
    llm_backend: str = field(default_factory=lambda: _env("LLM_BACKEND", "litert"))
    litert_server_url: str = field(default_factory=lambda: _env("LITERT_SERVER_URL", "http://localhost:8090"))
    gemini_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-2.5-flash"))

    # -- Specialist model backends (DESIGN.md §4) -----------------------
    eocaptioner_url: str = field(default_factory=lambda: _env("EOCAPTIONER_URL", "http://localhost:8000"))

    # -- Imagery data (DESIGN.md §6) -------------------------------------
    # Folder holding the four BigEarthNet-*.zip archives.
    bigearthnet_data_root: Path = field(
        default_factory=lambda: _env_path("BIGEARTHNET_DATA_ROOT", _REPO_ROOT)
    )
    # Where extracted per-patch band GeoTIFFs get cached (shared with the
    # eocaptioner container via a Docker volume in production).
    orchestrator_cache_dir: Path = field(
        default_factory=lambda: _env_path("ORCHESTRATOR_CACHE_DIR", _ORCHESTRATOR_DIR / "data_store" / "patch_cache")
    )
    # The UI's own fixture JSON files -- our patch footprint index reuses
    # them directly rather than re-deriving the same data (DESIGN.md §6).
    patch_fixtures_dir: Path = field(
        default_factory=lambda: _env_path(
            "PATCH_FIXTURES_DIR", _REPO_ROOT / "ui" / "src" / "mocks" / "fixtures" / "real-patches"
        )
    )

    # -- Persistence (DESIGN.md §10) -------------------------------------
    orchestrator_db_path: Path = field(
        default_factory=lambda: _env_path("ORCHESTRATOR_DB_PATH", _ORCHESTRATOR_DIR / "data_store" / "orchestrator.db")
    )
    upload_store_dir: Path = field(
        default_factory=lambda: _env_path("UPLOAD_STORE_DIR", _ORCHESTRATOR_DIR / "data_store" / "uploads")
    )
    report_store_dir: Path = field(
        default_factory=lambda: _env_path("REPORT_STORE_DIR", _ORCHESTRATOR_DIR / "data_store" / "reports")
    )

    # -- HTTP server -------------------------------------------------------
    cors_allow_origins: list[str] = field(
        default_factory=lambda: [o.strip() for o in _env("CORS_ALLOW_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
    )
    orchestrator_port: int = field(default_factory=lambda: int(_env("ORCHESTRATOR_PORT", "8080")))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))

    # -- Answer shaping (DESIGN.md §5 step 5 / §13) ------------------------
    # EOCaptioner doesn't emit a calibrated confidence score today. This is
    # a clearly-documented placeholder, never presented as a real measurement.
    placeholder_confidence: float = 0.75


settings = Settings()

# Every directory we might write into must exist before anything tries to
# use it -- created eagerly here (once, at import time) so individual
# modules never need their own "mkdir if missing" boilerplate.
for _dir in (
    settings.orchestrator_cache_dir,
    settings.orchestrator_db_path.parent,
    settings.upload_store_dir,
    settings.report_store_dir,
):
    _dir.mkdir(parents=True, exist_ok=True)
