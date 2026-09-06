"""Capa de acceso a los modelos de lenguaje, con dos proveedores intercambiables.

El proveedor se elige con ``LLM_PROVIDER`` (``anthropic`` o ``gemini``). El
resto del pipeline llama siempre a ``structured_call`` y no sabe cual esta
activo, asi que cambiar de uno a otro es editar una variable.

En ambos casos la salida estructurada NO se pide por prompt ("responde solo
JSON"), que es la fuente numero uno de errores de parseo:

* Anthropic: se declara un *tool* con su ``input_schema`` y se fuerza su uso.
* Gemini: se usa ``response_schema`` con ``response_mime_type`` JSON.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import get_settings

logger = logging.getLogger(__name__)


def _call_anthropic(
    *,
    model: str,
    system: str,
    prompt: str,
    tool_name: str,
    tool_description: str,
    input_schema: dict[str, Any],
    max_tokens: int,
) -> dict[str, Any]:
    """Llamada a la API de Anthropic con tool use forzado."""
    from anthropic import Anthropic

    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "Falta ANTHROPIC_API_KEY. Configurala en .env o en los Secrets del repo."
        )

    client = Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        tools=[
            {
                "name": tool_name,
                "description": tool_description,
                "input_schema": input_schema,
            }
        ],
        tool_choice={"type": "tool", "name": tool_name},
    )

    for block in response.content:
        if block.type == "tool_use":
            return dict(block.input)

    raise RuntimeError(f"El modelo no devolvio datos estructurados para {tool_name}.")


def _call_gemini(
    *,
    model: str,
    system: str,
    prompt: str,
    input_schema: dict[str, Any],
    max_tokens: int,
) -> dict[str, Any]:
    """Llamada a la API de Gemini con esquema de respuesta obligatorio."""
    from google import genai
    from google.genai import types

    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError(
            "Falta GEMINI_API_KEY. Sacala en aistudio.google.com y guardala "
            "en .env o en los Secrets del repo."
        )

    client = genai.Client(api_key=settings.gemini_api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=input_schema,
            max_output_tokens=max_tokens,
        ),
    )

    if not response.text:
        raise RuntimeError("Gemini devolvio una respuesta vacia.")
    return json.loads(response.text)


def resolve_model(requested: str) -> str:
    """Traduce el modelo pedido al del proveedor activo.

    El resto del pipeline pide siempre modelos de Anthropic por nombre. Si el
    proveedor activo es Gemini, aqui se mapea al equivalente: el modelo barato
    (Haiku) pasa a Flash-Lite y el de calidad (Sonnet) pasa a Flash. Asi los
    modulos que generan contenido no necesitan saber que proveedor hay debajo.

    Args:
        requested: identificador del modelo solicitado por el llamante.
    """
    settings = get_settings()
    if settings.llm_provider != "gemini":
        return requested
    es_barato = "haiku" in requested.lower() or "lite" in requested.lower()
    return settings.gemini_model_ranker if es_barato else settings.gemini_model_writer


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20), reraise=True)
def structured_call(
    *,
    model: str,
    system: str,
    prompt: str,
    tool_name: str,
    tool_description: str,
    input_schema: dict[str, Any],
    max_tokens: int = 2000,
) -> dict[str, Any]:
    """Ejecuta una llamada que devuelve obligatoriamente datos estructurados.

    Args:
        model: identificador del modelo a usar.
        system: prompt de sistema con el rol y las reglas de estilo.
        prompt: mensaje de usuario con los datos concretos.
        tool_name: nombre de la herramienta (solo lo usa Anthropic).
        tool_description: para que sirve la herramienta (solo Anthropic).
        input_schema: JSON Schema (sin defs anidados) de la respuesta esperada.
        max_tokens: limite de tokens de salida.

    Returns:
        El diccionario devuelto por el modelo.

    Raises:
        RuntimeError: si la respuesta no contiene datos estructurados validos.
    """
    settings = get_settings()
    model = resolve_model(model)

    if settings.llm_provider == "gemini":
        return _call_gemini(
            model=model,
            system=system,
            prompt=prompt,
            input_schema=input_schema,
            max_tokens=max_tokens,
        )

    return _call_anthropic(
        model=model,
        system=system,
        prompt=prompt,
        tool_name=tool_name,
        tool_description=tool_description,
        input_schema=input_schema,
        max_tokens=max_tokens,
    )
