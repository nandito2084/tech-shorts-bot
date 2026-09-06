"""Locucion del guion.

Se genera **un archivo de audio por escena**, no uno global. Asi se conoce la
duracion exacta de cada escena y el video queda sincronizado con la narracion
sin necesidad de transcribir despues con Whisper.

Proveedores (``TTS_PROVIDER``):

* ``gemini`` (por defecto): voz nativa de Gemini, incluida en el nivel gratuito
  de AI Studio y con la misma clave que el resto del pipeline. Funciona desde
  servidores, que es lo que aqui importa.
* ``edge``: edge-tts, gratuito pero **inservible en GitHub Actions**: Microsoft
  responde 403 a las IPs de centros de datos. Sirve solo en local.
* ``elevenlabs``: voz de marca, requiere clave y plan de pago.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import time
import wave
from functools import lru_cache
from pathlib import Path

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from config.models import ShortScript
from config.settings import get_settings

logger = logging.getLogger(__name__)

# Formato que devuelve la sintesis de Gemini: PCM crudo de 16 bits, 24 kHz, mono.
GEMINI_PCM_RATE = 24000
GEMINI_PCM_WIDTH = 2
GEMINI_PCM_CHANNELS = 1


def ensure_ffmpeg() -> None:
    """Comprueba que ffmpeg y ffprobe estan disponibles en el PATH."""
    for binary in ("ffmpeg", "ffprobe"):
        if shutil.which(binary) is None:
            raise RuntimeError(
                f"No se encuentra '{binary}'. Instala ffmpeg "
                "(Windows: winget install Gyan.FFmpeg | CI: apt-get install ffmpeg)."
            )


def audio_duration(path: Path) -> float:
    """Duracion en segundos de un archivo de audio, via ffprobe."""
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


@lru_cache
def _gemini_tts_model() -> str:
    """Devuelve un modelo de voz de Gemini disponible para esta clave.

    Google retira y renombra modelos con frecuencia, asi que en lugar de fijar
    un nombre se consulta el catalogo real de la cuenta y se elige el primero
    que soporte sintesis de voz. Si el catalogo no se puede leer, se cae al
    valor configurado en ``GEMINI_MODEL_TTS``.
    """
    settings = get_settings()
    try:
        from google import genai

        client = genai.Client(api_key=settings.gemini_api_key)
        nombres = [modelo.name.split("/")[-1] for modelo in client.models.list()]
        candidatos = [nombre for nombre in nombres if "tts" in nombre.lower()]
        # Se prefiere una version estable frente a una preview, si hay ambas.
        candidatos.sort(key=lambda nombre: ("preview" in nombre, nombre))
        if candidatos:
            logger.info("Modelo de voz de Gemini seleccionado: %s", candidatos[0])
            return candidatos[0]
        logger.warning("Ningun modelo TTS en el catalogo; se usa el configurado.")
    except Exception as exc:  # noqa: BLE001 - degradacion controlada
        logger.warning("No se pudo listar modelos de Gemini (%s).", exc)
    return settings.gemini_model_tts


def _write_wav(pcm: bytes, out_path: Path) -> None:
    """Envuelve el PCM crudo de Gemini en un WAV valido."""
    with wave.open(str(out_path), "wb") as handle:
        handle.setnchannels(GEMINI_PCM_CHANNELS)
        handle.setsampwidth(GEMINI_PCM_WIDTH)
        handle.setframerate(GEMINI_PCM_RATE)
        handle.writeframes(pcm)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def _gemini_tts(text: str, out_path: Path) -> None:
    """Sintetiza con la voz nativa de Gemini."""
    from google import genai
    from google.genai import types

    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("Falta GEMINI_API_KEY para generar la locucion.")

    # El estilo (acento, energia, ritmo) se pide en el propio texto: es el
    # mecanismo que ofrece Gemini para dirigir la voz.
    contenido = f"{settings.gemini_tts_style}: {text}" if settings.gemini_tts_style else text

    client = genai.Client(api_key=settings.gemini_api_key)
    response = client.models.generate_content(
        model=_gemini_tts_model(),
        contents=contenido,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=settings.gemini_voice
                    )
                )
            ),
        ),
    )

    pcm = response.candidates[0].content.parts[0].inline_data.data
    if not pcm:
        raise RuntimeError("Gemini no devolvio audio.")
    _write_wav(pcm, out_path)


async def _edge_tts(text: str, out_path: Path, voice: str, rate: str) -> None:
    """Sintetiza con edge-tts (asincrono por diseno de la libreria)."""
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


def audio_extension() -> str:
    """Extension del audio segun el proveedor activo."""
    return ".wav" if get_settings().tts_provider == "gemini" else ".mp3"


def _acelerar(path: Path, factor: float) -> None:
    """Acelera el audio in situ con ffmpeg, conservando el tono de voz."""
    if abs(factor - 1.0) < 0.01:
        return
    temp = path.with_name(f"{path.stem}_rapido{path.suffix}")
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(path), "-filter:a", f"atempo={factor:.2f}", str(temp)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.warning("No se pudo acelerar el audio: %s", result.stderr[-300:])
        return
    temp.replace(path)


def synthesize_scene(text: str, out_path: Path) -> float:
    """Genera el audio de una escena y devuelve su duracion en segundos."""
    settings = get_settings()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if settings.tts_provider == "elevenlabs":
        _elevenlabs_tts(text, out_path)
    elif settings.tts_provider == "edge":
        asyncio.run(_edge_tts(text, out_path, settings.edge_voice, settings.edge_rate))
    else:
        _gemini_tts(text, out_path)

    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError(f"El TTS no genero audio para: {text[:60]}...")

    _acelerar(out_path, settings.tts_speed)
    return audio_duration(out_path)


def synthesize_script(script: ShortScript, work_dir: Path) -> list[tuple[Path, float]]:
    """Locuta el guion completo, escena a escena.

    La primera pista corresponde al gancho; el resto, a cada escena.

    Returns:
        Lista de tuplas (ruta del audio, duracion en segundos).
    """
    ensure_ffmpeg()
    work_dir.mkdir(parents=True, exist_ok=True)

    settings = get_settings()
    extension = audio_extension()
    blocks = [script.hook] + [scene.narration for scene in script.scenes]
    tracks: list[tuple[Path, float]] = []
    for index, text in enumerate(blocks):
        # El nivel gratuito limita las peticiones por minuto: esperar entre
        # escenas alarga la ejecucion, pero evita el error 429.
        if index > 0 and settings.tts_pause_seconds > 0:
            time.sleep(settings.tts_pause_seconds)
        path = work_dir / f"voz_{index:02d}{extension}"
        duration = synthesize_scene(text, path)
        logger.info("Escena %d locutada: %.2fs", index, duration)
        tracks.append((path, duration))

    total = sum(duration for _, duration in tracks)
    logger.info("Duracion total de locucion: %.1fs", total)
    return tracks
