"""Montaje del video vertical 1080x1920 sin plataformas externas de pago.

Cada escena se compone por codigo con Pillow y se anima con un Ken Burns suave
via ``zoompan`` de ffmpeg. Sobre esa base se anaden:

* **B-roll** de Pexels al fondo, oscurecido, cuando hay clave configurada.
* **Cortes cada 3 segundos**: los bloques largos se parten en varios planos con
  el zoom alternado, que es lo que evita la sensacion de presentacion.
* **Badge de fuente** flotante translucido en los planos centrales.
* **Contador animado** cuando el guion aporta dos cifras comparables.
* **Subtitulos** quemados con resaltado palabra por palabra (ver subtitles.py).

Todo el material grafico es propio o de licencia comercial verificada: nunca se
usan imagenes de los medios de la noticia.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from config.models import ShortScript
from config.settings import FONTS_DIR, get_settings
from generators import broll as broll_mod
from generators import sfx as sfx_mod
from generators import subtitles as subs_mod

logger = logging.getLogger(__name__)

# Lienzo mayor que el video final para dar recorrido al zoom sin pixelar.
CANVAS_W, CANVAS_H = 1350, 2400

BG = (11, 13, 18)
ACCENT = (0, 224, 158)
ALERT = (255, 82, 66)
TEXT = (245, 246, 250)
MUTED = (140, 148, 165)

MAX_SHOT_SECONDS = 3.0

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
    """Parte el texto en lineas que caben en ``max_width`` pixeles."""
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


def _fondo(broll_path: Path | None) -> Image.Image:
    """Crea el lienzo de fondo: b-roll oscurecido o degradado procedural."""
    if broll_path and broll_path.exists():
        try:
            foto = Image.open(broll_path).convert("RGB")
            objetivo = CANVAS_W / CANVAS_H
            ancho, alto = foto.size
            if ancho / alto > objetivo:
                nuevo_ancho = int(alto * objetivo)
                izq = (ancho - nuevo_ancho) // 2
                foto = foto.crop((izq, 0, izq + nuevo_ancho, alto))
            else:
                nuevo_alto = int(ancho / objetivo)
                arriba = (alto - nuevo_alto) // 2
                foto = foto.crop((0, arriba, ancho, arriba + nuevo_alto))
            foto = foto.resize((CANVAS_W, CANVAS_H), Image.LANCZOS)
            foto = foto.filter(ImageFilter.GaussianBlur(3))
            # Velo oscuro: el b-roll se intuye, no compite con el texto.
            velo = Image.new("RGB", (CANVAS_W, CANVAS_H), BG)
            return Image.blend(foto, velo, 0.72)
        except Exception as exc:  # noqa: BLE001 - si falla, fondo procedural
            logger.warning("No se pudo usar el b-roll %s: %s", broll_path, exc)

    imagen = Image.new("RGB", (CANVAS_W, CANVAS_H), BG)
    draw = ImageDraw.Draw(imagen)
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
    return imagen


def _badge_fuente(imagen: Image.Image, source: str) -> None:
    """Dibuja la pastilla translucida de credito a la fuente."""
    draw = ImageDraw.Draw(imagen, "RGBA")
    fuente = _load_font(FONT_CANDIDATES_REGULAR, 34)
    texto = f"Fuente: {source}"[:46]
    ancho = int(draw.textlength(texto, font=fuente)) + 56
    x0, y0 = 110, CANVAS_H - 430
    draw.rounded_rectangle(
        [(x0, y0), (x0 + ancho, y0 + 74)], radius=16, fill=(0, 0, 0, 140)
    )
    draw.text((x0 + 28, y0 + 20), texto, font=fuente, fill=(235, 238, 245))


def render_card(
    on_screen_text: str,
    source: str,
    index: int,
    total: int,
    out_path: Path,
    *,
    broll_path: Path | None = None,
    mostrar_badge: bool = False,
    contador: int | None = None,
    unidad: str = "",
    alerta: bool = False,
) -> Path:
    """Genera el PNG de un plano.

    Args:
        on_screen_text: rotulo principal.
        source: medio de origen, para el badge.
        index: numero de escena (empezando en 0).
        total: numero total de escenas.
        out_path: destino del PNG.
        broll_path: imagen de fondo opcional.
        mostrar_badge: si se dibuja la pastilla de fuente.
        contador: valor numerico grande a mostrar en lugar del rotulo.
        unidad: unidad del contador (por ejemplo, W).
        alerta: pinta el contador en rojo de alarma.
    """
    settings = get_settings()
    imagen = _fondo(broll_path)
    draw = ImageDraw.Draw(imagen)

    font_brand = _load_font(FONT_CANDIDATES_BOLD, 44)
    draw.rectangle([(110, 250), (110 + 90, 250 + 10)], fill=ACCENT)
    draw.text((110, 290), settings.brand_name.upper(), font=font_brand, fill=ACCENT)

    if contador is not None:
        font_num = _load_font(FONT_CANDIDATES_BOLD, 300)
        color = ALERT if alerta else TEXT
        texto = f"{contador}{unidad}"
        ancho = draw.textlength(texto, font=font_num)
        draw.text(
            ((CANVAS_W - ancho) / 2, CANVAS_H / 2 - 320), texto, font=font_num, fill=color
        )
        barra_x0, barra_x1 = 200, CANVAS_W - 200
        y_barra = CANVAS_H / 2 + 120
        draw.rounded_rectangle(
            [(barra_x0, y_barra), (barra_x1, y_barra + 30)], radius=15, fill=(40, 46, 58)
        )
        if alerta:
            draw.rounded_rectangle(
                [(barra_x0, y_barra), (barra_x1, y_barra + 30)], radius=15, fill=ALERT
            )
    else:
        font_main = _load_font(FONT_CANDIDATES_BOLD, 118)
        lines = _wrap(draw, on_screen_text.upper(), font_main, CANVAS_W - 220)
        line_height = 140
        y = (CANVAS_H - line_height * len(lines)) // 2 - 160
        for line in lines:
            draw.text((110, y), line, font=font_main, fill=TEXT)
            y += line_height

    if mostrar_badge:
        _badge_fuente(imagen, source)

    bar_y = CANVAS_H - 200
    segment = (CANVAS_W - 220) // max(total, 1)
    for i in range(total):
        color = ACCENT if i <= index else (48, 54, 68)
        x0 = 110 + i * segment
        draw.rectangle([(x0, bar_y), (x0 + segment - 14, bar_y + 8)], fill=color)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    imagen.save(out_path)
    return out_path


def _run(cmd: list[str]) -> None:
    """Ejecuta un comando y vuelca stderr si falla."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg fallo:\n{result.stderr[-1500:]}")


def _segment(card: Path, duration: float, out_path: Path, *, zoom_in: bool = True) -> Path:
    """Convierte una tarjeta estatica en un clip con Ken Burns.

    Alternar el sentido del zoom entre planos consecutivos evita que dos planos
    del mismo bloque parezcan el mismo plano repetido.
    """
    settings = get_settings()
    frames = max(int(duration * settings.video_fps), 1)
    zoom = "min(zoom+0.0012,1.18)" if zoom_in else "if(lte(zoom,1.0),1.18,max(1.001,zoom-0.0012))"
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
    """Concatena archivos homogeneos con el demuxer concat de ffmpeg."""
    list_file = out_path.with_suffix(".txt")
    list_file.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in paths), encoding="utf-8"
    )
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file)]
    cmd += ["-c:a", "aac", "-b:a", "192k"] if reencode else ["-c", "copy"]
    cmd.append(str(out_path))
    _run(cmd)
    return out_path


def _planos_de_bloque(duracion: float) -> list[float]:
    """Parte la duracion de un bloque en planos de tres segundos como maximo."""
    if duracion <= MAX_SHOT_SECONDS:
        return [duracion]
    trozos = int(duracion // MAX_SHOT_SECONDS) + 1
    return [duracion / trozos] * trozos


def _clips_contador(
    script: ShortScript,
    source: str,
    total: int,
    duracion: float,
    work_dir: Path,
) -> list[Path]:
    """Genera la secuencia animada del contador para un bloque concreto.

    La animacion **ocupa** la duracion del bloque en lugar de anadirse a ella:
    si se insertara como planos extra, todo lo que viene despues se
    desplazaria y la imagen dejaria de coincidir con la voz.

    Args:
        script: guion, del que se leen las cifras.
        source: medio de origen.
        total: numero de bloques, para la barra de progreso.
        duracion: segundos que dura el bloque que ocupa el contador.
        work_dir: carpeta temporal.

    Returns:
        Lista de clips cuya suma dura exactamente ``duracion``. Vacia si el
        guion no aporta dos cifras comparables.
    """
    if not script.counter:
        return []
    desde, hasta = script.counter.get("from"), script.counter.get("to")
    unidad = script.counter.get("unit", "")
    if desde is None or hasta is None:
        return []

    settings = get_settings()
    pasos = 20
    por_paso = duracion / pasos
    clips: list[Path] = []
    for paso in range(pasos):
        avance = paso / (pasos - 1)
        # Ease-out cubica: arranca rapido y frena al llegar a la cifra final.
        suave = 1 - (1 - avance) ** 3
        valor = int(desde + (hasta - desde) * suave)
        alerta = valor >= desde + (hasta - desde) * 0.85
        card = render_card(
            "", source, 1, total, work_dir / f"cont_{paso:02d}.png",
            contador=valor, unidad=unidad, alerta=alerta,
        )
        clip = work_dir / f"cont_{paso:02d}.mp4"
        _run(
            [
                "ffmpeg", "-y", "-loop", "1", "-framerate", str(settings.video_fps),
                "-i", str(card), "-t", f"{por_paso:.3f}",
                "-vf", f"scale={settings.video_width}:{settings.video_height},format=yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p", str(clip),
            ]
        )
        clips.append(clip)
    logger.info("Contador animado: %s -> %s %s en %.1fs", desde, hasta, unidad, duracion)
    return clips


def build_video(
    script: ShortScript,
    tracks: list[tuple[Path, float]],
    source: str,
    work_dir: Path,
    out_path: Path,
    *,
    news_text: str = "",
) -> Path:
    """Monta el video final a partir del guion y las pistas de audio.

    Args:
        script: guion generado.
        tracks: lista (audio, duracion) devuelta por ``tts.synthesize_script``.
        source: medio de origen de la noticia.
        work_dir: carpeta temporal de trabajo.
        out_path: ruta del MP4 final.
        news_text: titular y resumen, para elegir el b-roll.

    Returns:
        La ruta del MP4 generado.
    """
    settings = get_settings()
    work_dir.mkdir(parents=True, exist_ok=True)

    textos = [script.title] + [scene.on_screen_text for scene in script.scenes]
    total = len(textos)

    imagenes = broll_mod.descargar_broll(news_text or script.title, total, work_dir)

    # El contador, si lo hay, sustituye al bloque 1: es donde el guion suele
    # soltar el dato numerico, y asi no desplaza el resto del video.
    bloque_contador = 1 if (script.counter and len(tracks) > 1) else -1

    segments: list[Path] = []
    indice_plano = 0
    for index, ((_, duration), texto) in enumerate(zip(tracks, textos)):
        if index == bloque_contador:
            clips = _clips_contador(script, source, total, duration, work_dir)
            if clips:
                segments.extend(clips)
                indice_plano += 1
                continue

        fondo = imagenes[index] if index < len(imagenes) else None
        for parte, trozo in enumerate(_planos_de_bloque(duration)):
            card = render_card(
                texto, source, index, total,
                work_dir / f"card_{index:02d}_{parte}.png",
                broll_path=fondo,
                mostrar_badge=index in (2, 3),
            )
            segments.append(
                _segment(
                    card, trozo, work_dir / f"seg_{indice_plano:03d}.mp4",
                    zoom_in=indice_plano % 2 == 0,
                )
            )
            indice_plano += 1

    video_mudo = _concat(segments, work_dir / "video_mudo.mp4", reencode=False)

    # --- Audio: voz mas efectos sintetizados ------------------------------
    voz = _concat([path for path, _ in tracks], work_dir / "voz.m4a", reencode=True)
    banco = sfx_mod.generar_banco(work_dir)
    duracion_total = sum(d for _, d in tracks)
    efectos = [
        (banco["impacto"], 0.0),
        (banco["glitch"], min(tracks[0][1], 1.6)),
        (banco["cierre"], max(duracion_total - 1.2, 0.0)),
    ]
    if bloque_contador >= 0:
        # El zumbido acompana al contador desde el inicio de su bloque.
        efectos.append((banco["riser"], sum(d for _, d in tracks[:bloque_contador])))
    audio = sfx_mod.mezclar(voz, efectos, work_dir / "audio_final.m4a")

    # --- Subtitulos -------------------------------------------------------
    bloques = [(script.hook, tracks[0][1])] + [
        (scene.narration, tracks[i + 1][1]) for i, scene in enumerate(script.scenes)
    ]
    ass_path = subs_mod.write_ass(
        bloques, work_dir / "subs.ass",
        width=settings.video_width, height=settings.video_height,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg", "-y", "-i", str(video_mudo), "-i", str(audio),
            "-vf", f"ass={ass_path.resolve().as_posix()}",
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k", "-shortest",
            "-movflags", "+faststart", str(out_path),
        ]
    )
    logger.info("Video listo: %s (%d planos)", out_path, len(segments))
    return out_path
