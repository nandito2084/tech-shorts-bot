"""Genera el refresh token de YouTube. Se ejecuta UNA sola vez, en tu PC.

Pasos previos en https://console.cloud.google.com:
 1. Crea un proyecto y activa "YouTube Data API v3".
 2. Pantalla de consentimiento OAuth: tipo Externo, y añade tu propia cuenta
    de Google como usuario de prueba.
 3. Credenciales -> ID de cliente de OAuth -> tipo "Aplicación de escritorio".
 4. Descarga el JSON y guárdalo como client_secret.json junto a este script.

Después:
    python tools/get_youtube_token.py

Copia el refresh token que imprime y guárdalo como Secret del repositorio
(YOUTUBE_REFRESH_TOKEN). No lo subas nunca al código.
"""

from __future__ import annotations

from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


def main() -> None:
    """Lanza el flujo OAuth local e imprime las credenciales resultantes."""
    secret_file = Path(__file__).parent / "client_secret.json"
    if not secret_file.exists():
        raise SystemExit(f"No se encuentra {secret_file}. Descárgalo de Google Cloud.")

    flow = InstalledAppFlow.from_client_secrets_file(str(secret_file), SCOPES)
    creds = flow.run_local_server(port=8080, prompt="consent", access_type="offline")

    print("\n" + "=" * 60)
    print("Guarda estos valores como Secrets del repositorio:\n")
    print(f"YOUTUBE_CLIENT_ID={creds.client_id}")
    print(f"YOUTUBE_CLIENT_SECRET={creds.client_secret}")
    print(f"YOUTUBE_REFRESH_TOKEN={creds.refresh_token}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
