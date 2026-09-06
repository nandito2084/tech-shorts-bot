"""Generación del guion, los metadatos y los prompts visuales.

El esquema está escrito a mano (sin ``$defs``) para máxima compatibilidad con
la API. Tras recibir la respuesta se validan las reglas de negocio (longitud de
título, número de palabras del guion). Si fallan, se reintenta una vez
indicándole al modelo exactamente qué corregir.
"""

from __future__ import annotations

import logging

from pydantic import ValidationError

from config.models import NewsItem, ShortScript
from config.settings import get_settings
from generators.claude_client import structured_call

logger = logging.getLogger(__name__)

SYSTEM_TEMPLATE = """Eres guionista de un canal de noticias de hardware y tecnología
en español de España, formato vertical de 45-50 segundos.

Reglas de estilo innegociables:
- Tono directo de creador tech: frases cortas, verbos en presente, cero relleno.
- Prohibidos los saludos, "¿Sabías que...?", "En el mundo de la tecnología",
  "Sin más dilación" y cualquier fórmula de locutor.
- El gancho ataca en los 3 primeros segundos con el dato más fuerte: una cifra,
  un precio o una comparación. Nunca una pregunta retórica.
- Datos concretos siempre que la noticia los dé: modelo, cifra, porcentaje, euros.
- Nunca inventes datos que no estén en la noticia. Si algo es un rumor, dilo.
- El guion completo (gancho + escenas) debe tener entre {words_min} y {words_max}
  palabras. Es un requisito duro.
- Los rótulos en pantalla son telegráficos, en mayúsculas de impacto, máximo 8 palabras.
- Los prompts visuales van en inglés, describen plano concreto, sin logotipos ni
  marcas registradas visibles ni caras de personas reales.

La marca del canal es {brand_name} ({brand_handle})."""

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "Título viral con gancho, máximo 55 caracteres.",
        },
        "hook": {
            "type": "string",
            "description": "Primera frase de alto impacto (3 segundos).",
        },
        "scenes": {
            "type": "array",
            "description": "Entre 4 y 5 escenas que continúan el gancho.",
            "items": {
                "type": "object",
                "properties": {
                    "narration": {
                        "type": "string",
                        "description": "Texto locutado de la escena (1-2 frases).",
                    },
                    "on_screen_text": {
                        "type": "string",
                        "description": "Rótulo en pantalla, máximo 8 palabras.",
                    },
                    "visual_prompt": {
                        "type": "string",
                        "description": "Descripción visual del plano, en inglés.",
                    },
                },
                "required": ["narration", "on_screen_text", "visual_prompt"],
            },
        },
        "cta_youtube": {
            "type": "string",
            "description": "Frase breve remitiendo al comentario fijado.",
        },
        "cta_instagram": {
            "type": "string",
            "description": "Frase pidiendo comentar una palabra clave.",
        },
        "youtube_pinned_comment": {
            "type": "string",
            "description": "Comentario fijado, con el marcador [LINK_AFILIADO_AQUI].",
        },
        "instagram_caption": {
            "type": "string",
            "description": "Copy de Instagram sin hashtags (van aparte).",
        },
        "hashtags": {
            "type": "array",
            "description": "Entre 10 y 15 hashtags de nicho, con almohadilla.",
            "items": {"type": "string"},
        },
        "keyword": {
            "type": "string",
            "description": "Palabra clave en mayúsculas del CTA de Instagram.",
        },
    },
    "required": [
        "title", "hook", "scenes", "cta_youtube", "cta_instagram",
        "youtube_pinned_comment", "instagram_caption", "hashtags", "keyword",
    ],
}


def _build_prompt(news: NewsItem, correction: str = "") -> str:
    """Construye el mensaje de usuario a partir de la noticia."""
    base = (
        f"NOTICIA\n"
        f"Medio: {news.source}\n"
        f"Titular: {news.title}\n"
        f"Resumen: {news.short_summary()}\n"
        f"Enlace: {news.link}\n\n"
        f"Escribe el paquete completo para el Short."
    )
    if correction:
        base += f"\n\nCORRIGE ESTO DE TU INTENTO ANTERIOR: {correction}"
    return base


def _validate(script: ShortScript, words_min: int, words_max: int) -> str:
    """Devuelve el texto de corrección necesario, o cadena vacía si todo va bien."""
    problems: list[str] = []
    if len(script.title) > 55:
        problems.append(f"el título tiene {len(script.title)} caracteres, máximo 55")
    if not words_min <= script.word_count <= words_max:
        problems.append(
            f"el guion tiene {script.word_count} palabras y debe tener "
            f"entre {words_min} y {words_max}"
        )
    if "[LINK_AFILIADO_AQUI]" not in script.youtube_pinned_comment:
        problems.append("falta el marcador [LINK_AFILIADO_AQUI] en el comentario fijado")
    return "; ".join(problems)


def generate_script(news: NewsItem) -> ShortScript:
    """Genera el guion y los metadatos de una noticia.

    Args:
        news: noticia seleccionada por el ranker.

    Returns:
        ``ShortScript`` validado.

    Raises:
        RuntimeError: si tras el reintento la salida sigue sin ser válida.
    """
    settings = get_settings()
    system = SYSTEM_TEMPLATE.format(
        words_min=settings.words_min,
        words_max=settings.words_max,
        brand_name=settings.brand_name,
        brand_handle=settings.brand_handle,
    )

    correction = ""
    last_error = ""
    for attempt in (1, 2):
        raw = structured_call(
            model=settings.model_writer,
            system=system,
            prompt=_build_prompt(news, correction),
            tool_name="emitir_guion",
            tool_description="Devuelve el guion y los metadatos del Short.",
            input_schema=SCHEMA,
            max_tokens=2500,
        )
        try:
            script = ShortScript.model_validate(raw)
        except ValidationError as exc:
            last_error = str(exc)
            correction = f"la estructura no era válida: {exc.errors()[:2]}"
            logger.warning("Intento %d inválido: %s", attempt, last_error[:200])
            continue

        correction = _validate(script, settings.words_min, settings.words_max)
        if not correction:
            logger.info("Guion generado (%d palabras): %s", script.word_count, script.title)
            return script
        logger.warning("Intento %d con problemas: %s", attempt, correction)
        last_error = correction

    raise RuntimeError(f"No se pudo generar un guion válido: {last_error}")
