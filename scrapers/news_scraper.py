"""Lectura de feeds RSS de tecnología, filtrado y deduplicación.

Puntos clave frente a una implementación ingenua:

* Cada feed se descarga con ``requests`` y User-Agent real (VideoCardz y
  Wccftech rechazan el UA por defecto de feedparser).
* Un feed caído **no** tumba la ejecución: se registra y se sigue.
* La deduplicación no es solo por enlace. Cuatro medios publican la misma
  noticia el mismo día, así que se compara el título normalizado con
  ``rapidfuzz`` contra el histórico y contra el propio lote.
* La caché tiene TTL y se escribe de forma atómica.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import feedparser
import requests
from rapidfuzz import fuzz
from tenacity import retry, stop_after_attempt, wait_exponential

from config.models import NewsItem
from config.settings import CACHE_FILE, get_settings

logger = logging.getLogger(__name__)

# Palabras que indican noticia con interés técnico real (no opinión ni ofertas).
KEYWORD_WEIGHTS: dict[str, float] = {
    "rtx": 3.0, "radeon": 3.0, "geforce": 3.0, "ryzen": 3.0, "core ultra": 3.0,
    "snapdragon": 2.5, "gpu": 2.0, "cpu": 2.0, "nvidia": 2.5, "amd": 2.5,
    "intel": 2.5, "apple": 2.0, "lanzamiento": 2.5, "launch": 2.5,
    "filtracion": 2.5, "leak": 2.5, "benchmark": 2.5, "rendimiento": 2.0,
    "precio": 2.0, "price": 2.0, "specs": 2.0, "especificaciones": 2.0,
    "ddr5": 1.5, "pcie": 1.5, "nm": 1.0, "tdp": 1.5, "overclock": 1.5,
    "ssd": 1.5, "placa base": 1.5, "motherboard": 1.5, "refrigeracion": 1.0,
    "iphone": 2.0, "android": 1.5, "movil": 1.5, "portatil": 1.5,
}

# Ruido que casi nunca da buen Short de noticias.
NEGATIVE_KEYWORDS: tuple[str, ...] = (
    "oferta", "chollo", "descuento", "cupon", "black friday", "sorteo",
    "review de", "analisis de", "guia de compra", "opinion",
)


def _normalize(text: str) -> str:
    """Minúsculas, sin acentos y sin puntuación, para comparar títulos."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", text).strip()


def _hash(link: str) -> str:
    """Identificador estable a partir del enlace."""
    return hashlib.sha1(link.strip().lower().encode()).hexdigest()[:16]


def _strip_html(raw: str) -> str:
    """Elimina etiquetas HTML del resumen del feed."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw or "")).strip()


class NewsCache:
    """Histórico de noticias ya procesadas, con TTL y escritura atómica."""

    def __init__(self, path: Path = CACHE_FILE, ttl_days: int = 30) -> None:
        self.path = path
        self.ttl_days = ttl_days
        self.entries: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Caché ilegible (%s). Se empieza de cero.", exc)
            return {}
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.ttl_days)
        return {
            key: value
            for key, value in data.items()
            if datetime.fromisoformat(value["seen_at"]) > cutoff
        }

    def contains(self, item_id: str) -> bool:
        """¿Se procesó ya esta noticia (por enlace)?"""
        return item_id in self.entries

    def is_duplicate_title(self, title: str, threshold: int) -> bool:
        """¿Hay en el histórico un titular casi idéntico (otro medio)?"""
        norm = _normalize(title)
        return any(
            fuzz.token_set_ratio(norm, entry["title_norm"]) >= threshold
            for entry in self.entries.values()
        )

    def add(self, item: NewsItem) -> None:
        """Registra la noticia como procesada."""
        self.entries[item.id] = {
            "title": item.title,
            "title_norm": _normalize(item.title),
            "link": item.link,
            "source": item.source,
            "seen_at": datetime.now(timezone.utc).isoformat(),
        }

    def save(self) -> None:
        """Escritura atómica: primero .tmp y luego os.replace."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self.entries, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, self.path)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _download_feed(url: str, user_agent: str, timeout: int) -> bytes:
    """Descarga el XML de un feed con reintentos exponenciales."""
    response = requests.get(
        url,
        headers={"User-Agent": user_agent, "Accept": "application/rss+xml, */*"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.content


def _published_at(entry: Any) -> datetime | None:
    """Extrae la fecha de publicación en UTC, si existe."""
    for field in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, field, None)
        if parsed:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
    return None


def _keyword_score(text: str) -> float:
    """Puntuación heurística por palabras clave técnicas."""
    norm = _normalize(text)
    score = sum(weight for word, weight in KEYWORD_WEIGHTS.items() if word in norm)
    score -= sum(3.0 for word in NEGATIVE_KEYWORDS if word in norm)
    return score


def fetch_candidates(force: bool = False) -> list[NewsItem]:
    """Devuelve las noticias nuevas y relevantes de las últimas N horas.

    Args:
        force: si es True ignora la caché (útil para pruebas).

    Returns:
        Lista de ``NewsItem`` ordenada por puntuación heurística descendente,
        recortada a ``settings.max_candidates``.
    """
    settings = get_settings()
    cache = NewsCache(ttl_days=settings.cache_ttl_days)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.hours_lookback)

    candidates: list[NewsItem] = []
    batch_titles: list[str] = []

    for url in settings.feeds:
        try:
            raw = _download_feed(url, settings.user_agent, settings.http_timeout)
        except Exception as exc:  # noqa: BLE001 - un feed caído no debe romper el run
            logger.warning("Feed no disponible %s: %s", url, exc)
            continue

        parsed = feedparser.parse(raw)
        source = parsed.feed.get("title", url)

        for entry in parsed.entries:
            link = entry.get("link", "").strip()
            title = entry.get("title", "").strip()
            if not link or not title:
                continue

            published = _published_at(entry)
            if published is None or published < cutoff:
                continue

            item_id = _hash(link)
            if not force and cache.contains(item_id):
                continue
            if not force and cache.is_duplicate_title(title, settings.dedup_threshold):
                logger.info("Duplicado entre medios, se descarta: %s", title)
                continue

            norm_title = _normalize(title)
            if any(
                fuzz.token_set_ratio(norm_title, other) >= settings.dedup_threshold
                for other in batch_titles
            ):
                logger.info("Duplicado dentro del lote, se descarta: %s", title)
                continue

            summary = _strip_html(entry.get("summary", ""))
            score = _keyword_score(f"{title} {summary}")
            if score <= 0:
                continue

            batch_titles.append(norm_title)
            candidates.append(
                NewsItem(
                    id=item_id,
                    title=title,
                    link=link,
                    summary=summary,
                    source=source,
                    published=published,
                    score=score,
                )
            )

    candidates.sort(key=lambda item: (item.score, item.published), reverse=True)
    logger.info("Candidatas encontradas: %d", len(candidates))
    return candidates[: settings.max_candidates]
