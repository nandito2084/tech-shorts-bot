# Tech Shorts Bot

Pipeline local y modular que convierte noticias de hardware en Shorts de YouTube
y Reels de Instagram, con locución, montaje y publicación automáticos.

```
RSS → dedup → ranking (Haiku) → guion (Sonnet) → TTS → vídeo (ffmpeg) → publicación
```

## Instalación

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # y rellena ANTHROPIC_API_KEY
```

También necesitas **ffmpeg** en el PATH:

- Windows: `winget install Gyan.FFmpeg`
- Linux: `sudo apt install ffmpeg`

## Uso

```bash
python main.py --check                  # qué noticias hay hoy (no gasta API)
python main.py --run --limit 1          # un vídeo completo
python main.py --run --no-video         # solo guion y metadatos
python main.py --run --dry-run          # todo menos publicar
python main.py --run --force            # ignora la caché (pruebas)
```

Salida en `data/output/YYYY-MM-DD_slug/`: JSON estructurado, TXT para copiar y
pegar, MP4 final. Y una fila por vídeo en `data/output/queue.csv`.

## Antes de activar la publicación automática

Tres cosas dependen de terceros y hay que tramitarlas a mano. Hasta entonces
el pipeline funciona en modo `--dry-run` y te deja el MP4 listo para subir.

**YouTube.** Proyecto en Google Cloud con la YouTube Data API v3 activada y
credenciales OAuth de escritorio. Ejecuta `python tools/get_youtube_token.py`
una vez en local para obtener el refresh token. Aviso importante: mientras el
proyecto no pase la verificación de Google, todo lo que subas por API queda
forzado a **privado**, aunque pidas público. Déjalo en `private` y publica a
mano hasta tener la verificación. La cuota diaria (10.000 unidades, ~1.600 por
subida) da para 5-6 vídeos al día.

**Instagram.** Necesita cuenta profesional vinculada a una página de Facebook,
una app de Meta con el permiso `instagram_content_publish` aprobado en App
Review, y un token de larga duración. La API no acepta subida de archivos: Meta
descarga el vídeo desde una URL pública, por eso `publisher/media_host.py` lo
sube antes como asset de una Release del repo (el repo debe ser público). Si lo
quieres privado, cambia ese módulo por Cloudflare R2 y ajusta
`MEDIA_PUBLIC_BASE_URL`.

**Afiliados.** Edita `config/affiliates.json` con tus tags reales. El acuerdo de
Amazon Afiliados no permite difundir enlaces por mensajes privados ni email, así
que el enlace de Amazon va solo al comentario fijado y a la descripción; el CTA
de Instagram remite al enlace de la bio. Verifica las condiciones vigentes de
cada programa antes de escalar.

## Configuración en GitHub Actions

Secrets del repositorio: `ANTHROPIC_API_KEY`, y si publicas,
`YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`,
`IG_USER_ID`, `IG_ACCESS_TOKEN`, `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`.

Variables (`vars`): `BRAND_NAME`, `BRAND_HANDLE`, `TTS_PROVIDER`,
`PUBLISH_YOUTUBE`, `PUBLISH_INSTAGRAM`, `YOUTUBE_PRIVACY`.

El workflow se ejecuta a diario, sube los vídeos como artefacto y hace commit de
`news_cache.json` para que la deduplicación sobreviva entre ejecuciones (el
runner es efímero).

## Decisiones de diseño

**Salida estructurada por tool use, no por prompt.** Pedir "responde solo JSON"
falla tarde o temprano. El esquema va como `input_schema` de una herramienta con
`tool_choice` forzado, y después se valida con Pydantic; si incumple una regla de
negocio (título >55 caracteres, guion fuera del rango de palabras) se reintenta
una vez indicando el error concreto.

**Deduplicación fuzzy, no por enlace.** Chapuzas, Geeknetic, VideoCardz y Xataka
publican la misma noticia el mismo día. Se comparan títulos normalizados con
rapidfuzz contra el histórico y contra el propio lote.

**Un solo ranking para todo el lote.** Las 15 candidatas van en una única llamada
a Haiku en vez de una por noticia. Si la API falla, se cae al orden heurístico
por palabras clave y el pipeline sigue.

**Vídeo generado por código.** Tarjetas tipográficas con Pillow y Ken Burns con
ffmpeg, con la duración de cada tarjeta igual a la del audio de su escena. Sin
InVideo ni Fliki, sin cuota mensual, sin metraje de banco con dudas de licencia,
y con estética propia y consistente.

**Una locución por escena.** Permite sincronizar el texto en pantalla sin
transcribir después con Whisper.

## Riesgo a vigilar

Noticias narradas con voz sintética y visuales de plantilla es justo el perfil
que YouTube revisa como contenido repetitivo al evaluar la monetización.
Mitigaciones: voz consistente, ángulo editorial propio en el guion, gráficos
propios y no publicar más de 1-2 vídeos al día durante los primeros meses.
Empieza con `--limit 1`.
