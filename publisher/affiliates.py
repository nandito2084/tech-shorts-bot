"""Resolución de enlaces de afiliado.

Reglas de negocio importantes:

* **Amazon Afiliados** no permite difundir enlaces por mensajes privados ni
  correo electrónico según su acuerdo de funcionamiento. Por eso el enlace de
  Amazon solo se inserta en el comentario fijado de YouTube y en la descripción,
  nunca en el CTA de "te lo mando por DM".
* Para Instagram se usa una URL de landing propia (enlace en la biografía), que
  es donde puedes tener ambos programas conviviendo sin infringir nada.
* La divulgación de afiliación es obligatoria en la UE: se añade siempre.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from config.settings import AFFILIATES_FILE

logger = logging.getLogger(__name__)

DISCLOSURE = "Enlaces de afiliado: si compras, me llevo una comisión sin coste para ti."


def _load_rules() -> dict[str, Any]:
    """Carga config/affiliates.json; devuelve estructura vacía si no existe."""
    if not AFFILIATES_FILE.exists():
        logger.warning("No hay config/affiliates.json; se usarán marcadores vacíos.")
        return {"landing_url": "", "rules": []}
    return json.loads(AFFILIATES_FILE.read_text(encoding="utf-8"))


def resolve_links(text: str) -> list[dict[str, str]]:
    """Devuelve los enlaces de afiliado que encajan con el texto de la noticia.

    Args:
        text: titular y resumen de la noticia.

    Returns:
        Lista de diccionarios con ``label``, ``url`` y ``program``.
    """
    rules = _load_rules()
    lowered = text.lower()
    matches = [
        {"label": rule["label"], "url": rule["url"], "program": rule.get("program", "")}
        for rule in rules.get("rules", [])
        if any(keyword.lower() in lowered for keyword in rule.get("keywords", []))
    ]
    return matches[:3] or rules.get("fallback", [])


def build_pinned_comment(template: str, text: str) -> str:
    """Sustituye [LINK_AFILIADO_AQUI] por los enlaces reales (YouTube)."""
    links = resolve_links(text)
    if not links:
        block = "(pendiente de enlace)"
    else:
        block = "\n".join(f"{item['label']}: {item['url']}" for item in links)
    return f"{template.replace('[LINK_AFILIADO_AQUI]', block)}\n\n{DISCLOSURE}"


def build_instagram_caption(caption: str, hashtags: list[str], cta: str) -> str:
    """Compone la caption de Instagram con CTA de bio (nunca enlaces en DM)."""
    landing = _load_rules().get("landing_url", "")
    bio_cta = f"Todo el material en el enlace de la bio ({landing})" if landing else ""
    parts = [caption, cta, bio_cta, DISCLOSURE, " ".join(hashtags)]
    return "\n\n".join(part for part in parts if part)
