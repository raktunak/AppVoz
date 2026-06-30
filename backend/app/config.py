from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Base de datos propia (pgvector)
    database_url: str = "postgresql+asyncpg://appvoz:appvoz_dev@db:5432/appvoz"

    # Google Cloud (reutilizado de brainrot: Gemini + Vertex + STT/TTS)
    gcp_project_id: str = "brainrot-walloop"
    gcp_region: str = "europe-west1"
    google_api_key: str = ""

    # Vertex AI — Live API (relay de voz). Auth por SA appvoz-voice vía ADC.
    # Live NO está en el endpoint 'global'; us-central1 es la región fiable.
    google_application_credentials: str = "credentials/appvoz-voice.json"
    gcp_live_location: str = "us-central1"
    # Embeddings por Vertex (misma SA/proyecto que la voz → usa los créditos GCP,
    # sin el límite free-tier de la Developer API). Región con gemini-embedding-001.
    gcp_embeddings_location: str = "us-central1"

    # Embeddings
    embedding_model: str = "gemini-embedding-001"
    embedding_dim: int = 768

    # Telnyx (telefonía PSTN/SIP → relay a Gemini Live)
    telnyx_api_key: str = ""              # SECRETO (Bearer API v2)
    telnyx_connection_id: str = ""        # Voice API application ID (no secreto)
    telnyx_sip_subdomain: str = ""        # subdominio SIP de pruebas (no secreto)
    telnyx_public_ws_url: str = ""        # override del WSS del media-stream (vacío = derivar del host)

    # Agenda (Google Calendar) — auth por la SA appvoz-voice (+scope calendar). El calendario
    # debe estar COMPARTIDO con el email de la SA. `calendar_id` es el de la demo/por defecto;
    # más adelante cada servicio tendrá el suyo (opt-in `citas_activas`).
    calendar_id: str = ""                 # ID del calendario destino (no secreto)
    agenda_timezone: str = "Europe/Madrid"

    # OAuth Google (login de alumnos + Calendar por usuario). Se crean en Google Cloud
    # Console: pantalla de consentimiento + credenciales tipo "Aplicación web", con la
    # redirect_uri de abajo en "URIs de redireccionamiento autorizados".
    google_oauth_client_id: str = ""      # SECRETO-ish (id público pero se trata como config)
    google_oauth_client_secret: str = ""  # SECRETO
    oauth_redirect_uri: str = "http://localhost:8080/auth/callback"
    # A dónde volver tras un login correcto (la UI del onboarding).
    post_login_redirect: str = "/4g/"


settings = Settings()
