"""Capa fina sobre la API de Anthropic.

La salida estructurada NO se pide por prompt ("responde solo JSON"), que es la
fuente número uno de errores de parseo. Se define un *tool* con su
``input_schema`` y se fuerza su uso con ``tool_choice``: el modelo devuelve un
bloque ``tool_use`` cuyo ``input`` ya viene como diccionario válido.
"""

from __future__ import annotations

import logging
from typing import Any

from anthropic import Anthropic, APIError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config.settings import get_settings

logger = logging.getLogger(__name__)


def get_client() -> Anthropic:
    """Instancia el cliente oficial, validando que exista la clave."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "Falta ANTHROPIC_API_KEY. Configúrala en .env o en los Secrets del repo."
        )
    return Anthropic(api_key=settings.anthropic_api_key)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    retry=retry_if_exception_type(APIError),
    reraise=True,
)
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
        model: identificador del modelo (ver ``config/settings.py``).
        system: prompt de sistema con el rol y las reglas de estilo.
        prompt: mensaje de usuario con los datos concretos.
        tool_name: nombre de la herramienta que define el esquema de salida.
        tool_description: para qué sirve la herramienta.
        input_schema: JSON Schema (sin ``$defs``) de la respuesta esperada.
        max_tokens: límite de tokens de salida.

    Returns:
        El diccionario devuelto por el modelo, ya validado contra el esquema.

    Raises:
        RuntimeError: si la respuesta no contiene ningún bloque ``tool_use``.
    """
    client = get_client()
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

    raise RuntimeError(f"El modelo no devolvió datos estructurados para {tool_name}.")
