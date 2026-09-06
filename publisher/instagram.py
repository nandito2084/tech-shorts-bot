"""Publicación de Reels con la Instagram Graph API.

Condiciones que impone Meta y que condicionan el diseño:

* La cuenta debe ser **profesional** (Business o Creator) y estar vinculada a
  una página de Facebook. Con cuenta personal no hay API.
* La app necesita el permiso ``instagram_content_publish`` aprobado en App
  Review. Hasta entonces solo funciona con usuarios de prueba.
* La API **no acepta subida directa de archivos**: Instagram descarga el vídeo
  desde una URL pública. Por eso el MP4 se sube antes a un alojamiento
  accesible (ver ``publisher/media_host.py``).
* Límite de 50 publicaciones por 24 horas.

El flujo es en dos pasos: crear el contenedor, esperar a que Meta lo procese y
después publicarlo.
"""

from __future__ import annotations

import logging
import time

import requests

from config.settings import get_settings

logger = logging.getLogger(__name__)


def _base_url() -> str:
    settings = get_settings()
    return f"https://graph.facebook.com/{settings.ig_graph_version}"


def _create_container(video_url: str, caption: str) -> str:
    """Crea el contenedor del Reel y devuelve su id."""
    settings = get_settings()
    response = requests.post(
        f"{_base_url()}/{settings.ig_user_id}/media",
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption[:2200],
            "share_to_feed": "true",
            "access_token": settings.ig_access_token,
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["id"]


def _wait_ready(container_id: str, timeout_s: int = 300) -> None:
    """Espera a que Meta termine de procesar el vídeo del contenedor."""
    settings = get_settings()
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        response = requests.get(
            f"{_base_url()}/{container_id}",
            params={
                "fields": "status_code,status",
                "access_token": settings.ig_access_token,
            },
            timeout=30,
        )
        response.raise_for_status()
        status = response.json().get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"Instagram rechazó el vídeo: {response.json()}")
        logger.info("Instagram procesando (%s)...", status)
        time.sleep(10)
    raise TimeoutError("Instagram no terminó de procesar el vídeo a tiempo.")


def publish_reel(video_url: str, caption: str) -> str:
    """Publica un Reel a partir de una URL pública de vídeo.

    Args:
        video_url: URL pública y directa del MP4.
        caption: texto de la publicación con hashtags incluidos.

    Returns:
        El id de la publicación creada.
    """
    settings = get_settings()
    if not (settings.ig_user_id and settings.ig_access_token):
        raise RuntimeError("Faltan IG_USER_ID o IG_ACCESS_TOKEN.")

    container_id = _create_container(video_url, caption)
    _wait_ready(container_id)

    response = requests.post(
        f"{_base_url()}/{settings.ig_user_id}/media_publish",
        data={"creation_id": container_id, "access_token": settings.ig_access_token},
        timeout=60,
    )
    response.raise_for_status()
    media_id = response.json()["id"]
    logger.info("Reel publicado: %s", media_id)
    return media_id
