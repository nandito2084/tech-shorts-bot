"""Configuracion central del proyecto.

Toda la configuracion se carga desde variables de entorno (.env en local,
Secrets del repositorio en GitHub Actions). No hay valores sensibles en codigo.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
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
    """Configuracion validada del pipeline."""

    @model_validator(mode="before")
    @classmethod
    def _ignorar_vacios(cls, datos: object) -> object:
        """Descarta las variables vacias para que gane el valor por defecto.

        En GitHub Actions, una variable que no existe se inyecta como cadena
        vacia. Sin esto, un TTS_SPEED sin crear tumba el arranque entero porque
        pydantic no puede convertir "" en numero.
        """
        if isinstance(datos, dict):
            return {
                clave: valor
                for clave, valor in datos.items()
                if not (isinstance(valor, str) and valor.strip() == "")
            }
        return datos

    # protected_namespaces vacio: los campos model_ranker y model_writer chocan
    # con el espacio reservado "model_" de pydantic y generan avisos.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=(),
    )

    # --- Proveedor de modelos ---------------------------------------------
    # anthropic = mejor calidad de guion, de pago por uso.
    # gemini    = nivel gratuito de Google AI Studio, modelos Flash.
    llm_provider: str = "gemini"

    # --- API de Anthropic -------------------------------------------------
    anthropic_api_key: str = Field(default="", description="Clave de la API de Anthropic")
    model_ranker: str = "claude-haiku-4-5-20251001"  # barato: puntua candidatas
    model_writer: str = "claude-sonnet-5"  # calidad: escribe el guion

    # --- API de Gemini ----------------------------------------------------
    gemini_api_key: str = Field(default="", description="Clave de Google AI Studio")
    # Google retira modelos con frecuencia. Si el pipeline falla con un 404 de
    # modelo, el propio mensaje de error indica cual es el sustituto: se cambia
    # aqui o con las variables GEMINI_MODEL_RANKER / GEMINI_MODEL_WRITER.
    gemini_model_ranker: str = "gemini-3.5-flash-lite"
    gemini_model_writer: str = "gemini-3.6-flash"

    # --- B-roll (Pexels) ---------------------------------------------------
    # Clave gratuita de pexels.com/api. Sin ella, el video se genera igual pero
    # con el fondo procedural en lugar de imagenes de apoyo.
    pexels_api_key: str = Field(default="", description="Clave de la API de Pexels")

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
    max_candidates: int = 15  # candidatas que se envian al ranker
    default_limit: int = 3  # noticias que se convierten en video
    dedup_threshold: int = 85  # similitud fuzzy de titulos (0-100)
    cache_ttl_days: int = 30
    http_timeout: int = 20
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )

    # --- Guion / locucion -------------------------------------------------
    # 30 segundos a ritmo agil son unas 80 palabras.
    target_seconds: int = 30
    words_min: int = 70
    words_max: int = 92
    brand_name: str = "TU MARCA"
    brand_handle: str = "@tumarca"

    # --- TTS --------------------------------------------------------------
    # gemini = gratis y funciona desde servidores | edge = solo en local
    # (Microsoft bloquea las IPs de centros de datos) | elevenlabs = de pago
    tts_provider: str = "gemini"
    gemini_voice: str = "Puck"  # voz masculina joven y energica
    gemini_model_tts: str = "gemini-3.5-flash-preview-tts"  # solo si falla el catalogo
    # Las voces de Gemini son multilingues: el acento se orienta con esta
    # instruccion de estilo, no se selecciona con un codigo de idioma.
    gemini_tts_style: str = (
        "Locuta en español de España, acento peninsular neutro, como un creador "
        "de contenido de tecnología joven y con energía. Ritmo rápido y natural, "
        "sin pausas largas. Enfatiza las cifras. No leas esta instrucción"
    )
    # Aceleracion posterior con ffmpeg: garantiza el ritmo aunque el modelo no
    # obedezca del todo la instruccion de velocidad. 1.0 la desactiva.
    tts_speed: float = 1.12
    # El nivel gratuito limita las peticiones por minuto: se espacian las escenas.
    tts_pause_seconds: int = 31
    edge_voice: str = "es-ES-AlvaroNeural"
    edge_rate: str = "+12%"
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    elevenlabs_model: str = "eleven_multilingual_v2"

    # --- Video ------------------------------------------------------------
    video_width: int = 1080
    video_height: int = 1920
    video_fps: int = 30

    # --- Publicacion ------------------------------------------------------
    publish_youtube: bool = False
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_refresh_token: str = ""
    youtube_privacy: str = "private"  # private | unlisted | public
    youtube_category_id: str = "28"  # Ciencia y tecnologia

    publish_instagram: bool = False
    ig_user_id: str = ""
    ig_access_token: str = ""
    ig_graph_version: str = "v21.0"

    # URL publica base donde queda alojado el MP4 (Instagram lo descarga de ahi).
    # Ver publisher/media_host.py - por defecto, GitHub Releases.
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
    """Devuelve la configuracion (cacheada) del proceso."""
    settings = Settings()
    settings.ensure_dirs()
    return settings
