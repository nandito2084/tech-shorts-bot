"""Efectos de sonido sintetizados y mezcla final del audio.

Los efectos no se descargan: se generan con los osciladores y filtros de
ffmpeg. Asi no hay archivos que licenciar, no hay descargas que fallen en el
runner y el resultado es identico en cada ejecucion. Si algun dia se quieren
efectos de banco, basta con sustituir las funciones de sintesis por la lectura
de un archivo.

Efectos disponibles:

* ``impacto``  - golpe grave de entrada, para el primer fotograma.
* ``glitch``   - chispazo electrico corto, para el corte del gancho.
* ``riser``    - zumbido ascendente que acompana al contador y corta en seco.
* ``cierre``   - golpe suave y apagado para la tarjeta final.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

SAMPLE_RATE = 24000


def _run(cmd: list[str]) -> None:
    """Ejecuta ffmpeg y vuelca el error si falla."""
    resultado = subprocess.run(cmd, capture_output=True, text=True)
    if resultado.returncode != 0:
        raise RuntimeError(f"ffmpeg fallo:\n{resultado.stderr[-800:]}")


def impacto(out_path: Path) -> Path:
    """Golpe grave: seno de 55 Hz con caida rapida."""
    filtro = f"aevalsrc=0.9*sin(2*PI*55*t)*exp(-6*t):s={SAMPLE_RATE}:d=0.6"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-f", "lavfi", "-i", filtro, str(out_path)])
    return out_path


def glitch(out_path: Path) -> Path:
    """Chispazo: ruido blanco filtrado en banda alta, muy corto."""
    filtro = (
        f"anoisesrc=r={SAMPLE_RATE}:c=white:d=0.18:a=0.5,"
        "highpass=f=1800,lowpass=f=6500,"
        "afade=t=out:st=0.06:d=0.12"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-f", "lavfi", "-i", filtro, str(out_path)])
    return out_path


def riser(out_path: Path, duracion: float = 1.5) -> Path:
    """Zumbido ascendente: barrido de 120 Hz a 900 Hz que corta en seco."""
    filtro = (
        f"aevalsrc=0.35*sin(2*PI*(120+780*t/{duracion:.2f})*t):"
        f"s={SAMPLE_RATE}:d={duracion:.2f}"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", filtro,
            "-af", "afade=t=in:st=0:d=0.2,volume=1.2",
            str(out_path),
        ]
    )
    return out_path


def cierre(out_path: Path) -> Path:
    """Golpe de cierre: grave apagado y con menos pegada que el de entrada."""
    filtro = f"aevalsrc=0.6*sin(2*PI*70*t)*exp(-9*t):s={SAMPLE_RATE}:d=0.5"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-f", "lavfi", "-i", filtro, str(out_path)])
    return out_path


def mezclar(
    voz_path: Path,
    efectos: list[tuple[Path, float]],
    out_path: Path,
    *,
    volumen_efectos: float = 0.32,
) -> Path:
    """Mezcla la locucion con los efectos en sus posiciones exactas.

    Args:
        voz_path: pista de locucion ya concatenada.
        efectos: lista de (archivo del efecto, segundo en el que entra).
        out_path: archivo de audio resultante.
        volumen_efectos: ganancia aplicada a los efectos (la voz queda a 1.0).

    Returns:
        La ruta del audio mezclado. Si no hay efectos, devuelve la voz tal cual.
    """
    if not efectos:
        return voz_path

    entradas: list[str] = ["-i", str(voz_path)]
    for ruta, _ in efectos:
        entradas += ["-i", str(ruta)]

    # Cada efecto se retrasa hasta su posicion y se baja de volumen; luego se
    # suman todos sobre la voz sin recortar picos.
    partes = []
    etiquetas = ["[0:a]"]
    for indice, (_, segundo) in enumerate(efectos, start=1):
        ms = int(segundo * 1000)
        partes.append(
            f"[{indice}:a]adelay={ms}|{ms},volume={volumen_efectos:.2f}[e{indice}]"
        )
        etiquetas.append(f"[e{indice}]")
    filtro = ";".join(partes)
    filtro += f";{''.join(etiquetas)}amix=inputs={len(etiquetas)}:duration=first:normalize=0[out]"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        ["ffmpeg", "-y", *entradas, "-filter_complex", filtro,
         "-map", "[out]", "-c:a", "aac", "-b:a", "192k", str(out_path)]
    )
    logger.info("Audio mezclado con %d efectos", len(efectos))
    return out_path


def generar_banco(work_dir: Path) -> dict[str, Path]:
    """Genera los cuatro efectos y devuelve un diccionario por nombre."""
    work_dir.mkdir(parents=True, exist_ok=True)
    return {
        "impacto": impacto(work_dir / "sfx_impacto.wav"),
        "glitch": glitch(work_dir / "sfx_glitch.wav"),
        "riser": riser(work_dir / "sfx_riser.wav"),
        "cierre": cierre(work_dir / "sfx_cierre.wav"),
    }
