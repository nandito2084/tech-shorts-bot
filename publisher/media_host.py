"""Alojamiento temporal del MP4 en una URL pública.

Instagram descarga el vídeo desde una URL, así que en un runner de GitHub
Actions hace falta publicarlo en algún sitio accesible. La opción con cero
coste y cero infraestructura es subirlo como *asset* de una Release del propio
repositorio.

Requisito: el repositorio debe ser **público** para que la URL del asset sea
descargable sin cabecera de autenticación. Si prefieres mantenerlo privado,
sustituye este módulo por Cloudflare R2 o un bucket S3 con URL firmada; la
interfaz (``upload_public``) es la misma.
"""

from __future__ import annotations

import logging
from pathlib import Path

import requests

from config.settings import get_settings

logger = logging.getLogger(__name__)

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _ensure_release(repo: str, token: str, tag: str) -> dict:
    """Obtiene la Release del tag indicado, creándola si no existe."""
    response = requests.get(
        f"{API}/repos/{repo}/releases/tags/{tag}", headers=_headers(token), timeout=30
    )
    if response.status_code == 200:
        return response.json()

    created = requests.post(
        f"{API}/repos/{repo}/releases",
        headers=_headers(token),
        json={
            "tag_name": tag,
            "name": f"Media {tag}",
            "body": "Alojamiento temporal de vídeos para publicación automática.",
        },
        timeout=30,
    )
    created.raise_for_status()
    return created.json()


def upload_public(video_path: str | Path, tag: str = "media") -> str:
    """Sube el vídeo y devuelve su URL pública de descarga directa.

    Args:
        video_path: ruta local del MP4.
        tag: tag de la Release que hace de contenedor.

    Returns:
        URL pública del archivo.
    """
    settings = get_settings()

    # Si ya tienes un CDN propio configurado, se usa ese y no se toca GitHub.
    if settings.media_public_base_url:
        return f"{settings.media_public_base_url.rstrip('/')}/{Path(video_path).name}"

    if not (settings.github_token and settings.github_repo):
        raise RuntimeError(
            "Para publicar en Instagram hace falta GITHUB_TOKEN y GITHUB_REPO, "
            "o bien MEDIA_PUBLIC_BASE_URL apuntando a tu propio alojamiento."
        )

    path = Path(video_path)
    release = _ensure_release(settings.github_repo, settings.github_token, tag)

    upload_url = f"{UPLOADS}/repos/{settings.github_repo}/releases/{release['id']}/assets"
    headers = _headers(settings.github_token) | {"Content-Type": "video/mp4"}
    response = requests.post(
        upload_url,
        headers=headers,
        params={"name": path.name},
        data=path.read_bytes(),
        timeout=300,
    )
    response.raise_for_status()

    url = response.json()["browser_download_url"]
    logger.info("Vídeo alojado en %s", url)
    return url
