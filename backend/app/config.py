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

    # Embeddings
    embedding_model: str = "gemini-embedding-001"
    embedding_dim: int = 768


settings = Settings()
