from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    mongodb_url: str = "mongodb://localhost:27017"
    database_name: str = "product_db"
    api_key: str = "xxx"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
