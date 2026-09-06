"""Subida a YouTube mediante la Data API v3.

Requisitos y avisos importantes:

* Autenticación OAuth con *refresh token* generado una vez en local
  (``tools/get_youtube_token.py``) y guardado como Secret del repositorio.
* Cuota diaria por defecto: 10.000 unidades. Una subida cuesta ~1.600, así que
  el techo real son 5-6 vídeos al día.
* Mientras el proyecto de Google Cloud no pase la auditoría de verificación,
  **todo lo que subas por API queda forzado a privado**. Publica primero como
  ``private`` o ``unlisted`` y cambia a público a mano hasta tener la
  verificación aprobada.
"""

from __future__ import annotations

import logging

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config.models import Package
from config.settings import get_settings

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.force-ssl"]


def _credentials() -> Credentials:
    """Construye credenciales OAuth a partir del refresh token."""
    settings = get_settings()
    missing = [
        name
        for name, value in {
            "YOUTUBE_CLIENT_ID": settings.youtube_client_id,
            "YOUTUBE_CLIENT_SECRET": settings.youtube_client_secret,
            "YOUTUBE_REFRESH_TOKEN": settings.youtube_refresh_token,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(f"Faltan credenciales de YouTube: {', '.join(missing)}")

    creds = Credentials(
        token=None,
        refresh_token=settings.youtube_refresh_token,
        client_id=settings.youtube_client_id,
        client_secret=settings.youtube_client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return creds


def upload_short(package: Package, pinned_comment: str) -> str:
    """Sube el vídeo y fija el comentario con los enlaces de afiliado.

    Args:
        package: paquete con ``video_path`` ya generado.
        pinned_comment: texto del comentario a publicar y fijar.

    Returns:
        La URL pública del vídeo subido.
    """
    settings = get_settings()
    youtube = build("youtube", "v3", credentials=_credentials(), cache_discovery=False)

    description = (
        f"{package.script.hook}\n\n"
        f"{package.script.cta_youtube}\n\n"
        f"Fuente: {package.news.source} — {package.news.link}\n\n"
        f"{' '.join(package.script.hashtags[:5])}\n#Shorts"
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": package.script.title[:100],
                "description": description[:4900],
                "tags": [tag.lstrip("#") for tag in package.script.hashtags[:12]],
                "categoryId": settings.youtube_category_id,
                "defaultLanguage": "es",
            },
            "status": {
                "privacyStatus": settings.youtube_privacy,
                "selfDeclaredMadeForKids": False,
            },
        },
        media_body=MediaFileUpload(package.video_path, chunksize=-1, resumable=True),
    )

    response = None
    while response is None:
        _, response = request.next_chunk()

    video_id = response["id"]
    logger.info("Subido a YouTube: %s", video_id)

    try:
        youtube.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {"textOriginal": pinned_comment[:9000]}
                    },
                }
            },
        ).execute()
    except Exception as exc:  # noqa: BLE001 - el vídeo ya está subido
        logger.warning("No se pudo publicar el comentario fijado: %s", exc)

    return f"https://youtube.com/shorts/{video_id}"
