"""Selección de las noticias con más potencial viral.

En lugar de una llamada por noticia (caro y lento), se envía el lote completo
de candidatas en **una sola** llamada a Haiku, que las puntúa y devuelve el
ranking con su justificación.
"""

from __future__ import annotations

import logging

from config.models import NewsItem
from config.settings import get_settings
from generators.claude_client import structured_call

logger = logging.getLogger(__name__)

SYSTEM = """Eres editor jefe de un canal de noticias de hardware y tecnología en
YouTube Shorts e Instagram Reels, en español de España.

Puntúas noticias de 0 a 10 según su potencial para un vídeo vertical de 45
segundos. Priorizas, en este orden:
1. Impacto para quien compra o monta un PC (precios, lanzamientos, rendimiento real).
2. Novedad y exclusividad (filtraciones, primeros benchmarks, specs confirmadas).
3. Capacidad de generar debate o sorpresa.

Penalizas: refritos de notas de prensa, ofertas, contenido corporativo sin
consecuencias prácticas y noticias que ya son de dominio general."""

SCHEMA = {
    "type": "object",
    "properties": {
        "ranking": {
            "type": "array",
            "description": "Noticias ordenadas de mayor a menor potencial.",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "id exacto de la noticia"},
                    "score": {"type": "number", "description": "Puntuación de 0 a 10"},
                    "reason": {
                        "type": "string",
                        "description": "Justificación en una frase corta",
                    },
                },
                "required": ["id", "score", "reason"],
            },
        }
    },
    "required": ["ranking"],
}


def rank_news(candidates: list[NewsItem], limit: int) -> list[NewsItem]:
    """Ordena las candidatas por potencial y devuelve las ``limit`` mejores.

    Si la API falla, se cae con elegancia al orden heurístico por palabras
    clave que ya trae el scraper: el pipeline nunca se queda sin salida.
    """
    if not candidates:
        return []

    settings = get_settings()
    listing = "\n\n".join(
        f"id: {item.id}\nmedio: {item.source}\ntitular: {item.title}\n"
        f"resumen: {item.short_summary(400)}"
        for item in candidates
    )

    try:
        result = structured_call(
            model=settings.model_ranker,
            system=SYSTEM,
            prompt=f"Puntúa estas {len(candidates)} noticias:\n\n{listing}",
            tool_name="emitir_ranking",
            tool_description="Devuelve el ranking de noticias puntuadas.",
            input_schema=SCHEMA,
            max_tokens=1500,
        )
    except Exception as exc:  # noqa: BLE001 - degradación controlada
        logger.warning("Ranker no disponible (%s). Se usa el orden heurístico.", exc)
        return candidates[:limit]

    by_id = {item.id: item for item in candidates}
    ranked: list[NewsItem] = []
    for row in sorted(result["ranking"], key=lambda r: r["score"], reverse=True):
        item = by_id.get(row["id"])
        if item is None:
            continue
        item.score = float(row["score"])
        item.reason = row["reason"]
        ranked.append(item)

    return (ranked or candidates)[:limit]
