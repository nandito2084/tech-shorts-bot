"""Exportación de resultados: JSON estructurado, TXT legible y cola CSV.

El CSV (``data/output/queue.csv``) está pensado para importarse en Metricool o
para ser leído por un webhook de Make.com si algún día quieres orquestar la
publicación desde fuera.
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import date
from pathlib import Path

from slugify import slugify

from config.models import NewsItem, Package, ShortScript
from config.settings import OUTPUT_DIR, QUEUE_FILE
from publisher.affiliates import build_instagram_caption, build_pinned_comment

logger = logging.getLogger(__name__)

CSV_HEADERS = [
    "fecha", "slug", "titulo", "medio", "enlace_noticia",
    "ruta_video", "descripcion_youtube", "comentario_fijado",
    "caption_instagram", "estado_youtube", "estado_instagram",
]


def build_slug(title: str) -> str:
    """Slug corto y seguro para nombres de archivo."""
    return f"{date.today():%Y-%m-%d}_{slugify(title)[:60]}"


def export_package(news: NewsItem, script: ShortScript) -> Package:
    """Escribe el JSON y el TXT de una noticia y devuelve el paquete.

    Args:
        news: noticia de origen.
        script: guion generado.

    Returns:
        ``Package`` con las rutas ya rellenadas.
    """
    slug = build_slug(script.title)
    folder = OUTPUT_DIR / slug
    folder.mkdir(parents=True, exist_ok=True)

    context = f"{news.title} {news.summary}"
    pinned = build_pinned_comment(script.youtube_pinned_comment, context)
    caption = build_instagram_caption(
        script.instagram_caption, script.hashtags, script.cta_instagram
    )

    payload = {
        "noticia": json.loads(news.model_dump_json()),
        "titulo": script.title,
        "gancho": script.hook,
        "guion": script.script_body,
        "palabras": script.word_count,
        "escenas": [scene.model_dump() for scene in script.scenes],
        "prompts_visuales": script.visual_prompts,
        "cta_youtube": script.cta_youtube,
        "cta_instagram": script.cta_instagram,
        "comentario_fijado": pinned,
        "caption_instagram": caption,
        "hashtags": script.hashtags,
        "keyword": script.keyword,
    }

    json_path = folder / f"{slug}.json"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    txt_path = folder / f"{slug}.txt"
    txt_path.write_text(_render_txt(news, script, pinned, caption), encoding="utf-8")

    logger.info("Exportado: %s", folder)
    return Package(
        news=news,
        script=script,
        slug=slug,
        json_path=str(json_path),
        txt_path=str(txt_path),
    )


def _render_txt(
    news: NewsItem, script: ShortScript, pinned: str, caption: str
) -> str:
    """Versión legible para copiar y pegar de un vistazo."""
    lines = [
        f"TÍTULO: {script.title}",
        f"FUENTE: {news.source} — {news.link}",
        f"MOTIVO DE SELECCIÓN: {news.reason or 'heurística por palabras clave'}",
        "",
        "=== GUION DE LOCUCIÓN ===",
        script.script_body,
        f"({script.word_count} palabras)",
        "",
        "=== ESCENAS ===",
    ]
    for index, scene in enumerate(script.scenes, start=1):
        lines += [
            f"[{index}] RÓTULO: {scene.on_screen_text}",
            f"    LOCUCIÓN: {scene.narration}",
            f"    VISUAL: {scene.visual_prompt}",
        ]
    lines += [
        "",
        "=== YOUTUBE ===",
        f"CTA: {script.cta_youtube}",
        "COMENTARIO FIJADO:",
        pinned,
        "",
        "=== INSTAGRAM ===",
        f"PALABRA CLAVE: {script.keyword}",
        "CAPTION:",
        caption,
    ]
    return "\n".join(lines)


def append_to_queue(package: Package) -> Path:
    """Añade (o crea) una fila en la cola CSV lista para Metricool/Make."""
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    is_new = not QUEUE_FILE.exists()

    payload = json.loads(Path(package.json_path).read_text(encoding="utf-8"))
    row = {
        "fecha": f"{date.today():%Y-%m-%d}",
        "slug": package.slug,
        "titulo": package.script.title,
        "medio": package.news.source,
        "enlace_noticia": package.news.link,
        "ruta_video": package.video_path,
        "descripcion_youtube": f"{package.script.hook} {package.script.cta_youtube}",
        "comentario_fijado": payload["comentario_fijado"],
        "caption_instagram": payload["caption_instagram"],
        "estado_youtube": package.youtube_url or "pendiente",
        "estado_instagram": package.instagram_id or "pendiente",
    }

    with QUEUE_FILE.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_HEADERS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)

    return QUEUE_FILE
