"""Subtitulos dinamicos en formato ASS, con resaltado palabra por palabra.

El pipeline conoce la duracion de cada bloque de audio, pero no cuando suena
cada palabra. En lugar de transcribir el audio (lento y pesado en CI), se
reparte la duracion del bloque entre sus palabras ponderando por numero de
caracteres, que es como se distribuye el tiempo al hablar. El error tipico es
de una decima de segundo: imperceptible con subtitulos de dos palabras.

Se usa ASS y no SRT porque permite colorear una palabra concreta dentro de la
linea, que es justo el efecto que se busca.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Palabras que siempre van resaltadas aunque no sean la que suena: son el dato
# que el espectador debe retener aunque vea el video sin sonido.
KEYWORD_PATTERNS = (
    r"^\d+[.,]?\d*$",  # cifras sueltas: 613, 4.5
    r"^\d+[a-z%€$]+$",  # cifras con unidad: 600w, 30%, 800€
    r"^(dlss|fsr|rtx|rx|ryzen|core|gpu|cpu|ram|ssd|nvme|hz|fps|w|tdp)$",
)

MAX_WORDS_PER_CUE = 2


@dataclass
class Cue:
    """Una linea de subtitulo con su ventana temporal."""

    start: float
    end: float
    words: list[str]
    highlight: int  # indice de la palabra resaltada dentro de la linea


def _normalize(word: str) -> str:
    """Minusculas sin acentos ni puntuacion, para comparar con los patrones."""
    limpio = unicodedata.normalize("NFKD", word.lower())
    limpio = "".join(c for c in limpio if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9%€$.,]", "", limpio)


def is_keyword(word: str) -> bool:
    """Indica si una palabra debe ir siempre en color de acento."""
    limpio = _normalize(word)
    return any(re.match(patron, limpio) for patron in KEYWORD_PATTERNS)


def _split_words(text: str, start: float, duration: float) -> list[tuple[str, float, float]]:
    """Reparte la duracion del bloque entre sus palabras, segun longitud."""
    words = text.split()
    if not words:
        return []
    pesos = [max(len(w), 2) for w in words]
    total = sum(pesos)
    salida: list[tuple[str, float, float]] = []
    reloj = start
    for word, peso in zip(words, pesos):
        fin = reloj + duration * peso / total
        salida.append((word, reloj, fin))
        reloj = fin
    return salida


def build_cues(blocks: list[tuple[str, float]]) -> list[Cue]:
    """Convierte los bloques de locucion en lineas de subtitulo.

    Args:
        blocks: lista de (texto del bloque, duracion en segundos), en orden.

    Returns:
        Lista de ``Cue``, una por palabra: la linea se mantiene y solo cambia
        la palabra resaltada, lo que produce el efecto de karaoke.
    """
    cues: list[Cue] = []
    reloj = 0.0
    for texto, duracion in blocks:
        palabras = _split_words(texto, reloj, duracion)
        reloj += duracion
        # Se agrupan de dos en dos: mas palabras no caben en vertical.
        for inicio in range(0, len(palabras), MAX_WORDS_PER_CUE):
            grupo = palabras[inicio : inicio + MAX_WORDS_PER_CUE]
            for indice, (_, comienzo, fin) in enumerate(grupo):
                cues.append(
                    Cue(
                        start=comienzo,
                        end=fin,
                        words=[w for w, _, _ in grupo],
                        highlight=indice,
                    )
                )
    return cues


def _timestamp(segundos: float) -> str:
    """Convierte segundos al formato de tiempo de ASS (h:mm:ss.cc)."""
    segundos = max(segundos, 0.0)
    horas, resto = divmod(segundos, 3600)
    minutos, seg = divmod(resto, 60)
    return f"{int(horas)}:{int(minutos):02d}:{seg:05.2f}"


def _render_line(cue: Cue, accent_hex: str, text_hex: str) -> str:
    """Genera el texto ASS de una linea, con la palabra activa en color."""
    partes = []
    for indice, palabra in enumerate(cue.words):
        activa = indice == cue.highlight
        color = accent_hex if (activa or is_keyword(palabra)) else text_hex
        escala = r"\fscx108\fscy108" if activa else r"\fscx100\fscy100"
        partes.append(f"{{\\c&H{color}&{escala}}}{palabra}")
    return " ".join(partes)


def write_ass(
    blocks: list[tuple[str, float]],
    out_path: Path,
    *,
    width: int,
    height: int,
    font_size: int = 64,
    accent_bgr: str = "9EE000",  # ASS usa BGR, no RGB
    text_bgr: str = "FAF6F5",
) -> Path:
    """Escribe el archivo .ass listo para quemar con ffmpeg.

    Args:
        blocks: lista de (texto, duracion) por bloque de locucion.
        out_path: ruta del archivo .ass.
        width: ancho del video en pixeles.
        height: alto del video en pixeles.
        font_size: tamano de la tipografia del subtitulo.
        accent_bgr: color de acento en BGR hexadecimal.
        text_bgr: color base del texto en BGR hexadecimal.

    Returns:
        La ruta del archivo generado.
    """
    cues = build_cues(blocks)

    cabecera = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Base,DejaVu Sans,{font_size},&H00{text_bgr},&H00101010,&H90000000,-1,0,0,0,100,100,0,0,1,6,3,2,80,80,320,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lineas = [
        f"Dialogue: 0,{_timestamp(c.start)},{_timestamp(c.end)},Base,,0,0,0,,"
        f"{_render_line(c, accent_bgr, text_bgr)}"
        for c in cues
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(cabecera + "\n".join(lineas) + "\n", encoding="utf-8")
    logger.info("Subtitulos generados: %d lineas", len(lineas))
    return out_path
