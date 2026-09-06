"""Orquestador del pipeline.

Uso:
    python main.py --check              # solo muestra noticias nuevas
    python main.py --run                # pipeline completo
    python main.py --run --limit 1      # una sola noticia
    python main.py --run --no-video     # solo guion y metadatos
    python main.py --run --dry-run      # sin publicar (aunque esté activado)
    python main.py --run --force        # ignora la caché de noticias vistas
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from config.models import Package  # noqa: E402
from config.settings import OUTPUT_DIR, get_settings  # noqa: E402
from generators.ranker import rank_news  # noqa: E402
from generators.script_generator import generate_script  # noqa: E402
from scrapers.news_scraper import NewsCache, fetch_candidates  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")


def cmd_check(limit: int, force: bool) -> int:
    """Muestra las noticias nuevas detectadas sin gastar API de generación."""
    candidates = fetch_candidates(force=force)
    if not candidates:
        print("\nNo hay noticias nuevas en la ventana configurada.\n")
        return 0

    print(f"\n{len(candidates)} noticias nuevas (top {limit} irían a producción):\n")
    for index, item in enumerate(candidates, start=1):
        marker = "->" if index <= limit else "  "
        print(f"{marker} [{item.score:5.1f}] {item.title}")
        print(f"      {item.source} | {item.published:%d/%m %H:%M} | {item.link}\n")
    return 0


def _produce_media(package: Package, work_root: Path) -> Package:
    """Genera locución y vídeo para un paquete ya exportado."""
    from generators.tts import synthesize_script
    from generators.video_builder import build_video

    work_dir = work_root / package.slug
    tracks = synthesize_script(package.script, work_dir)
    video_path = OUTPUT_DIR / package.slug / f"{package.slug}.mp4"
    build_video(package.script, tracks, package.news.source, work_dir, video_path)

    package.audio_path = str(work_dir)
    package.video_path = str(video_path)
    return package


def _publish(package: Package) -> Package:
    """Publica en las plataformas activadas por configuración."""
    settings = get_settings()
    payload = json.loads(Path(package.json_path).read_text(encoding="utf-8"))

    if settings.publish_youtube:
        try:
            from publisher.youtube import upload_short

            package.youtube_url = upload_short(package, payload["comentario_fijado"])
        except Exception as exc:  # noqa: BLE001 - un fallo no debe perder el vídeo
            logger.error("Fallo publicando en YouTube: %s", exc)

    if settings.publish_instagram:
        try:
            from publisher.instagram import publish_reel
            from publisher.media_host import upload_public

            video_url = upload_public(package.video_path)
            package.instagram_id = publish_reel(
                video_url, payload["caption_instagram"]
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Fallo publicando en Instagram: %s", exc)

    return package


def cmd_run(limit: int, force: bool, make_video: bool, dry_run: bool) -> int:
    """Ejecuta el pipeline completo."""
    from publisher.scheduler import append_to_queue, export_package

    settings = get_settings()
    cache = NewsCache(ttl_days=settings.cache_ttl_days)

    candidates = fetch_candidates(force=force)
    if not candidates:
        logger.info("Sin noticias nuevas. Fin.")
        return 0

    selected = rank_news(candidates, limit)
    logger.info("Seleccionadas %d noticias de %d candidatas.", len(selected), len(candidates))

    produced: list[Package] = []
    with tempfile.TemporaryDirectory(prefix="shorts_") as tmp:
        work_root = Path(tmp)
        for item in selected:
            try:
                script = generate_script(item)
                package = export_package(item, script)
                if make_video:
                    package = _produce_media(package, work_root)
                    if not dry_run:
                        package = _publish(package)
                append_to_queue(package)
                cache.add(item)
                produced.append(package)
            except Exception as exc:  # noqa: BLE001 - seguimos con la siguiente
                logger.error("Error procesando '%s': %s", item.title, exc)

    cache.save()

    print("\n" + "=" * 62)
    print(f"Generados {len(produced)} paquetes en {OUTPUT_DIR}")
    for package in produced:
        print(f"\n  {package.script.title}")
        print(f"    texto : {package.txt_path}")
        if package.video_path:
            print(f"    vídeo : {package.video_path}")
        if package.youtube_url:
            print(f"    youtube: {package.youtube_url}")
        if package.instagram_id:
            print(f"    reel   : {package.instagram_id}")
    print("=" * 62 + "\n")
    return 0 if produced else 1


def build_parser() -> argparse.ArgumentParser:
    """Define la interfaz de línea de comandos."""
    parser = argparse.ArgumentParser(
        description="Pipeline de Shorts/Reels de noticias de hardware."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="Solo listar noticias nuevas")
    group.add_argument("--run", action="store_true", help="Ejecutar pipeline completo")
    parser.add_argument("--limit", type=int, default=None, help="Noticias a procesar")
    parser.add_argument("--force", action="store_true", help="Ignorar la caché")
    parser.add_argument(
        "--no-video", action="store_true", help="Solo guion y metadatos, sin montar vídeo"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Generar todo pero no publicar"
    )
    return parser


def main() -> int:
    """Punto de entrada."""
    args = build_parser().parse_args()
    settings = get_settings()
    limit = args.limit or settings.default_limit

    if args.check:
        return cmd_check(limit, args.force)
    return cmd_run(limit, args.force, not args.no_video, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
