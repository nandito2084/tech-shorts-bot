"""Locución del guion.

Se genera **un archivo de audio por escena**, no uno global. Así se conoce la
duración exacta de cada escena y el vídeo queda sincronizado con la narración
sin necesidad de transcribir después con Whisper.

Proveedores:
* ``edge`` (por defecto): edge-tts, gratuito, voces neuronales de Microsoft.
* ``elevenlabs``: voz de marca, requiere clave y plan de pago.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
from pathlib import Path

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from config.models import ShortScript
from config.settings import get_settings

logger = logging.getLogger(__name__)


def ensure_ffmpeg() -> None:
    """Comprueba que ffmpeg y ffprobe están disponibles en el PATH."""
    for binary in ("ffmpeg", "ffprobe"):
        if shutil.which(binary) is None:
            raise RuntimeError(
                f"No se encuentra '{binary}'. Instala ffmpeg "
                "(Windows: winget install Gyan.FFmpeg | CI: apt-get install ffmpeg)."
            )


def audio_duration(path: Path) -> float:
    """Duración en segundos de un archivo de audio, vía ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


async def _edge_tts(text: str, out_path: Path, voice: str, rate: str) -> None:
    """Sintetiza con edge-tts (asíncrono por diseño de la librería)."""
    import edge_tts  # import local: solo se necesita con este proveedor

    communicate = edge_tts.Communicate(text, voice=voice, rate=rate)
    await communicate.save(str(out_path))


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=15))
def _elevenlabs_tts(text: str, out_path: Path) -> None:
    """Sintetiza con la API de ElevenLabs."""
    settings = get_settings()
    if not (settings.elevenlabs_api_key and settings.elevenlabs_voice_id):
        raise RuntimeError("Faltan ELEVENLABS_API_KEY o ELEVENLABS_VOICE_ID.")

    response = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{settings.elevenlabs_voice_id}",
        headers={
            "xi-api-key": settings.elevenlabs_api_key,
            "Content-Type": "application/json",
        },
        json={
            "text": text,
            "model_id": settings.elevenlabs_model,
            "voice_settings": {"stability": 0.45, "similarity_boost": 0.8},
        },
        timeout=120,
    )
    response.raise_for_status()
    out_path.write_bytes(response.content)


def synthesize_scene(text: str, out_path: Path) -> float:
    """Genera el audio de una escena y devuelve su duración en segundos."""
    settings = get_settings()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if settings.tts_provider == "elevenlabs":
        _elevenlabs_tts(text, out_path)
    else:
        asyncio.run(
            _edge_tts(text, out_path, settings.edge_voice, settings.edge_rate)
        )

    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError(f"El TTS no generó audio para: {text[:60]}...")
    return audio_duration(out_path)


def synthesize_script(script: ShortScript, work_dir: Path) -> list[tuple[Path, float]]:
    """Locuta el guion completo, escena a escena.

    La primera pista corresponde al gancho; el resto, a cada escena.

    Returns:
        Lista de tuplas (ruta del audio, duración en segundos).
    """
    ensure_ffmpeg()
    work_dir.mkdir(parents=True, exist_ok=True)

    blocks = [script.hook] + [scene.narration for scene in script.scenes]
    tracks: list[tuple[Path, float]] = []
    for index, text in enumerate(blocks):
        path = work_dir / f"voz_{index:02d}.mp3"
        duration = synthesize_scene(text, path)
        logger.info("Escena %d locutada: %.2fs", index, duration)
        tracks.append((path, duration))

    total = sum(duration for _, duration in tracks)
    logger.info("Duración total de locución: %.1fs", total)
    return tracks
