"""Montaje del vídeo vertical 1080x1920 sin plataformas externas de pago.

Cada escena se compone como una tarjeta tipográfica generada por código
(Pillow) y se anima con un Ken Burns suave vía ``zoompan`` de ffmpeg. La
duración de cada tarjeta es exactamente la del audio de esa escena, así que el
texto en pantalla siempre acompaña a lo que se está locutando.

Ventaja frente a metraje de banco o imágenes de prensa: cero riesgo de
copyright, estética propia y consistente, y coste cero.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config.models import ShortScript
from config.settings import FONTS_DIR, get_settings

logger = logging.getLogger(__name__)

# Lienzo mayor que el vídeo final para dar recorrido al zoom sin pixelar.
CANVAS_W, CANVAS_H = 1350, 2400

BG = (11, 13, 18)
ACCENT = (0, 224, 158)
TEXT = (245, 246, 250)
MUTED = (140, 148, 165)

FONT_CANDIDATES_BOLD = [
    FONTS_DIR / "Montserrat-ExtraBold.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    Path("C:/Windows/Fonts/segoeuib.ttf"),
    Path("C:/Windows/Fonts/arialbd.ttf"),
]
FONT_CANDIDATES_REGULAR = [
    FONTS_DIR / "Montserrat-Medium.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    Path("C:/Windows/Fonts/segoeui.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
]


def _load_font(candidates: list[Path], size: int) -> ImageFont.FreeTypeFont:
    """Carga la primera fuente disponible del listado de candidatas."""
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    logger.warning("Sin fuentes TTF; se usa la fuente por defecto de Pillow.")
    return ImageFont.load_default()


def _wrap(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int
) -> list[str]:
    """Parte el texto en líneas que caben en ``max_width`` píxeles."""
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def render_card(
    on_screen_text: str,
    source: str,
    index: int,
    total: int,
    out_path: Path,
) -> Path:
    """Genera el PNG de una escena.

    Args:
        on_screen_text: rótulo principal de la escena.
        source: medio de origen, se imprime en el pie.
        index: número de escena (empezando en 0).
        total: número total de escenas.
        out_path: destino del PNG.
    """
    settings = get_settings()
    image = Image.new("RGB", (CANVAS_W, CANVAS_H), BG)
    draw = ImageDraw.Draw(image)

    # Degradado sutil de fondo (barato y elimina la sensación de plano).
    for y in range(CANVAS_H):
        factor = y / CANVAS_H
        draw.line(
            [(0, y), (CANVAS_W, y)],
            fill=(
                int(BG[0] + 14 * factor),
                int(BG[1] + 16 * factor),
                int(BG[2] + 24 * factor),
            ),
        )

    font_brand = _load_font(FONT_CANDIDATES_BOLD, 44)
    font_main = _load_font(FONT_CANDIDATES_BOLD, 118)
    font_foot = _load_font(FONT_CANDIDATES_REGULAR, 38)

    # Cabecera: marca y barra de acento.
    draw.rectangle([(110, 250), (110 + 90, 250 + 10)], fill=ACCENT)
    draw.text((110, 290), settings.brand_name.upper(), font=font_brand, fill=ACCENT)

    # Texto principal, centrado verticalmente.
    max_width = CANVAS_W - 220
    lines = _wrap(draw, on_screen_text.upper(), font_main, max_width)
    line_height = 140
    block_height = line_height * len(lines)
    y = (CANVAS_H - block_height) // 2
    for line in lines:
        draw.text((110, y), line, font=font_main, fill=TEXT)
        y += line_height

    # Pie: fuente de la noticia.
    draw.text((110, CANVAS_H - 300), f"Fuente: {source}", font=font_foot, fill=MUTED)

    # Barra de progreso de escenas.
    bar_y = CANVAS_H - 200
    segment = (CANVAS_W - 220) // max(total, 1)
    for i in range(total):
        color = ACCENT if i <= index else (48, 54, 68)
        x0 = 110 + i * segment
        draw.rectangle([(x0, bar_y), (x0 + segment - 14, bar_y + 8)], fill=color)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
    return out_path


def _run(cmd: list[str]) -> None:
    """Ejecuta un comando y vuelca stderr si falla."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg falló:\n{result.stderr[-1500:]}")


def _segment(card: Path, duration: float, out_path: Path) -> Path:
    """Convierte una tarjeta estática en un clip con Ken Burns."""
    settings = get_settings()
    frames = max(int(duration * settings.video_fps), 1)
    zoom = "min(zoom+0.0006,1.12)"
    vf = (
        f"zoompan=z='{zoom}':d={frames}"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":s={settings.video_width}x{settings.video_height}:fps={settings.video_fps},"
        "format=yuv420p"
    )
    _run(
        [
            "ffmpeg", "-y", "-loop", "1", "-framerate", str(settings.video_fps),
            "-i", str(card), "-t", f"{duration:.3f}", "-vf", vf,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", str(out_path),
        ]
    )
    return out_path


def _concat(paths: list[Path], out_path: Path, reencode: bool) -> Path:
    """Concatena archivos homogéneos con el demuxer concat de ffmpeg."""
    list_file = out_path.with_suffix(".txt")
    list_file.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in paths), encoding="utf-8"
    )
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file)]
    cmd += ["-c:a", "aac", "-b:a", "192k"] if reencode else ["-c", "copy"]
    cmd.append(str(out_path))
    _run(cmd)
    return out_path


def build_video(
    script: ShortScript,
    tracks: list[tuple[Path, float]],
    source: str,
    work_dir: Path,
    out_path: Path,
) -> Path:
    """Monta el vídeo final a partir del guion y las pistas de audio.

    Args:
        script: guion generado.
        tracks: lista (audio, duración) devuelta por ``tts.synthesize_script``.
        source: medio de origen de la noticia.
        work_dir: carpeta temporal de trabajo.
        out_path: ruta del MP4 final.

    Returns:
        La ruta del MP4 generado.
    """
    work_dir.mkdir(parents=True, exist_ok=True)

    # El primer bloque es el gancho; el resto, las escenas.
    texts = [script.title] + [scene.on_screen_text for scene in script.scenes]
    total = len(texts)

    segments: list[Path] = []
    last_index = len(tracks) - 1
    for index, ((_, duration), text) in enumerate(zip(tracks, texts)):
        card = render_card(text, source, index, total, work_dir / f"card_{index:02d}.png")
        # La duración es exactamente la del audio de la escena: si se añadiera
        # margen a cada una, el desfase se acumularía y el último rótulo
        # entraría más de un segundo tarde. El aire va solo al final.
        clip_duration = duration + (0.6 if index == last_index else 0.0)
        segments.append(_segment(card, clip_duration, work_dir / f"seg_{index:02d}.mp4"))

    video_track = _concat(segments, work_dir / "video_mudo.mp4", reencode=False)
    audio_track = _concat(
        [path for path, _ in tracks], work_dir / "voz.m4a", reencode=True
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg", "-y", "-i", str(video_track), "-i", str(audio_track),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", str(out_path),
        ]
    )
    logger.info("Vídeo listo: %s", out_path)
    return out_path
