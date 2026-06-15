from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Base de datos propia (pgvector)
    database_url: str = "postgresql+asyncpg://appvoz:appvoz_dev@db:5432/appvoz"

    # Google Cloud (reutilizado de brainrot: Gemini + Vertex + STT/TTS)
    gcp_project_id: str = "brainrot-walloop"
    gcp_region: str = "europe-west1"
    google_api_key: str = ""

    # Embeddings
    embedding_model: str = "gemini-embedding-001"
    embedding_dim: int = 768


settings = Settings()
