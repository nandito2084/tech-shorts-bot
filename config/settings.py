"""Configuración central del proyecto.

Toda la configuración se carga desde variables de entorno (.env en local,
Secrets del repositorio en GitHub Actions). No hay valores sensibles en código.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = ROOT_DIR / "data"
OUTPUT_DIR: Path = DATA_DIR / "output"
ASSETS_DIR: Path = ROOT_DIR / "assets"
FONTS_DIR: Path = ASSETS_DIR / "fonts"
CACHE_FILE: Path = DATA_DIR / "news_cache.json"
QUEUE_FILE: Path = OUTPUT_DIR / "queue.csv"
AFFILIATES_FILE: Path = ROOT_DIR / "config" / "affiliates.json"


class Settings(BaseSettings):
    """Configuración validada del pipeline."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- API de Anthropic -------------------------------------------------
    anthropic_api_key: str = Field(default="", description="Clave de la API de Anthropic")
    model_ranker: str = "claude-haiku-4-5-20251001"  # barato: puntúa candidatas
    model_writer: str = "claude-sonnet-5"  # calidad: escribe el guion

    # --- Fuentes RSS ------------------------------------------------------
    feeds: list[str] = [
        "https://elchapuzasinformatico.com/feed/",
        "https://www.geeknetic.es/rss.php",
        "https://videocardz.com/feed",
        "https://feeds.weblogssl.com/xataka2",
        "https://www.techpowerup.com/rss/news",
        "https://wccftech.com/feed/",
    ]
    hours_lookback: int = 48
    max_candidates: int = 15  # candidatas que se envían al ranker
    default_limit: int = 3  # noticias que se convierten en vídeo
    dedup_threshold: int = 85  # similitud fuzzy de títulos (0-100)
    cache_ttl_days: int = 30
    http_timeout: int = 20
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )

    # --- Guion / locución -------------------------------------------------
    target_seconds: int = 45
    words_min: int = 115
    words_max: int = 145
    brand_name: str = "TU MARCA"
    brand_handle: str = "@tumarca"

    # --- TTS --------------------------------------------------------------
    tts_provider: str = "edge"  # edge | elevenlabs
    edge_voice: str = "es-ES-AlvaroNeural"
    edge_rate: str = "+12%"
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    elevenlabs_model: str = "eleven_multilingual_v2"

    # --- Vídeo ------------------------------------------------------------
    video_width: int = 1080
    video_height: int = 1920
    video_fps: int = 30

    # --- Publicación ------------------------------------------------------
    publish_youtube: bool = False
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_refresh_token: str = ""
    youtube_privacy: str = "private"  # private | unlisted | public
    youtube_category_id: str = "28"  # Ciencia y tecnología

    publish_instagram: bool = False
    ig_user_id: str = ""
    ig_access_token: str = ""
    ig_graph_version: str = "v21.0"

    # URL pública base donde queda alojado el MP4 (Instagram lo descarga de ahí).
    # Ver publisher/media_host.py — por defecto, GitHub Releases.
    media_public_base_url: str = ""
    github_token: str = ""
    github_repo: str = ""  # formato usuario/repositorio

    def ensure_dirs(self) -> None:
        """Crea las carpetas de datos si no existen."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        FONTS_DIR.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Devuelve la configuración (cacheada) del proceso."""
    settings = Settings()
    settings.ensure_dirs()
    return settings
