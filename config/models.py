"""Modelos de datos compartidos por todo el pipeline."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class NewsItem(BaseModel):
    """Noticia normalizada procedente de un feed RSS."""

    id: str = Field(description="Hash estable del enlace canónico")
    title: str
    link: str
    summary: str = ""
    source: str = ""
    published: datetime
    score: float = 0.0
    reason: str = ""

    def short_summary(self, limit: int = 600) -> str:
        """Resumen recortado para no inflar el prompt."""
        return self.summary[:limit]


class Scene(BaseModel):
    """Una escena del Short: narración + texto en pantalla + prompt visual."""

    narration: str = Field(description="Lo que se locuta en esta escena")
    on_screen_text: str = Field(description="Rótulo corto en pantalla (máx. 8 palabras)")
    visual_prompt: str = Field(description="Descripción visual en inglés")

    @field_validator("on_screen_text")
    @classmethod
    def _limit_words(cls, value: str) -> str:
        words = value.split()
        return " ".join(words[:8])


class ShortScript(BaseModel):
    """Salida estructurada del generador de guiones."""

    title: str = Field(max_length=70)
    hook: str
    scenes: list[Scene] = Field(min_length=4, max_length=5)
    cta_youtube: str
    cta_instagram: str
    youtube_pinned_comment: str
    instagram_caption: str
    hashtags: list[str] = Field(min_length=10, max_length=15)
    keyword: str = Field(description="Palabra clave del CTA de Instagram (ej. GPU)")

    # --- Derivados usados por el resto del pipeline -----------------------

    @property
    def script_body(self) -> str:
        """Guion completo de locución (gancho incluido)."""
        return " ".join([self.hook, *(s.narration for s in self.scenes)])

    @property
    def visual_prompts(self) -> list[str]:
        """Lista de prompts visuales, uno por escena."""
        return [s.visual_prompt for s in self.scenes]

    @property
    def word_count(self) -> int:
        """Número de palabras del guion completo."""
        return len(self.script_body.split())


class Package(BaseModel):
    """Paquete final: noticia + guion + rutas de los archivos generados."""

    news: NewsItem
    script: ShortScript
    slug: str
    json_path: str = ""
    txt_path: str = ""
    audio_path: str = ""
    video_path: str = ""
    youtube_url: str = ""
    instagram_id: str = ""
