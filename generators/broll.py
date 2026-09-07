"""Obtencion de material de fondo (b-roll) desde Pexels.

Pexels ofrece fotografia y video con licencia de uso comercial y sin necesidad
de atribucion, lo que evita el problema de usar imagenes de los medios de la
noticia. La clave es gratuita.

El material se elige por categoria, deducida de las palabras del titular. Si la
API falla, no hay clave o no hay resultados, el pipeline sigue sin b-roll: el
video se genera igualmente con el fondo procedural de siempre. Nunca se cae la
ejecucion por esto.
"""

from __future__ import annotations

import logging
import unicodedata
from pathlib import Path

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import get_settings

logger = logging.getLogger(__name__)

API_URL = "https://api.pexels.com/v1/search"

# Palabras del titular -> consulta en Pexels. El orden importa: gana la primera
# categoria que aparezca en el texto.
CATEGORIAS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("rtx", "geforce", "nvidia", "radeon", "grafica", "gpu"), "graphics card close up"),
    (("ryzen", "intel", "core", "procesador", "cpu"), "computer processor macro"),
    (("ssd", "nvme", "disco", "almacenamiento"), "ssd hard drive technology"),
    (("ddr", "memoria", "ram"), "computer memory module"),
    (("placa", "chipset", "motherboard"), "motherboard circuit macro"),
    (("iphone", "movil", "smartphone", "android", "snapdragon"), "smartphone dark desk"),
    (("portatil", "laptop"), "gaming laptop dark"),
    (("refrigeracion", "ventilador", "temperatura"), "pc cooling fan rgb"),
)
CONSULTA_POR_DEFECTO = "gaming pc setup dark"


def _normalize(text: str) -> str:
    """Minusculas y sin acentos, para buscar las palabras clave."""
    limpio = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in limpio if not unicodedata.combining(c))


def elegir_consulta(texto: str) -> str:
    """Deduce la consulta de Pexels a partir del titular de la noticia."""
    normalizado = _normalize(texto)
    for palabras, consulta in CATEGORIAS:
        if any(palabra in normalizado for palabra in palabras):
            return consulta
    return CONSULTA_POR_DEFECTO


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=15))
def _buscar(consulta: str, cantidad: int, api_key: str) -> list[str]:
    """Devuelve URLs de imagenes verticales para la consulta dada."""
    respuesta = requests.get(
        API_URL,
        headers={"Authorization": api_key},
        params={
            "query": consulta,
            "orientation": "portrait",
            "per_page": cantidad,
            "size": "large",
        },
        timeout=30,
    )
    respuesta.raise_for_status()
    fotos = respuesta.json().get("photos", [])
    return [foto["src"]["portrait"] for foto in fotos if foto.get("src")]


def descargar_broll(texto: str, cantidad: int, work_dir: Path) -> list[Path]:
    """Descarga imagenes de fondo para una noticia.

    Args:
        texto: titular y resumen, para deducir la categoria.
        cantidad: numero de imagenes a descargar (una por escena).
        work_dir: carpeta temporal donde guardarlas.

    Returns:
        Lista de rutas locales. Lista vacia si no hay clave, la API falla o no
        hay resultados: en ese caso el video usa solo el fondo procedural.
    """
    settings = get_settings()
    if not settings.pexels_api_key:
        logger.info("Sin PEXELS_API_KEY: el video se genera sin b-roll.")
        return []

    consulta = elegir_consulta(texto)
    logger.info("B-roll: consulta '%s'", consulta)

    try:
        urls = _buscar(consulta, cantidad, settings.pexels_api_key)
    except Exception as exc:  # noqa: BLE001 - el b-roll nunca tumba el pipeline
        logger.warning("Pexels no disponible (%s). Se sigue sin b-roll.", exc)
        return []

    work_dir.mkdir(parents=True, exist_ok=True)
    rutas: list[Path] = []
    for indice, url in enumerate(urls):
        destino = work_dir / f"broll_{indice:02d}.jpg"
        try:
            contenido = requests.get(url, timeout=30)
            contenido.raise_for_status()
            destino.write_bytes(contenido.content)
            rutas.append(destino)
        except Exception as exc:  # noqa: BLE001
            logger.warning("No se pudo descargar %s: %s", url, exc)

    logger.info("B-roll descargado: %d imagenes", len(rutas))
    return rutas
