from pydantic import BaseModel
import os


class DatabaseSettings(BaseModel):
    host: str = os.getenv("PAPERRADAR_DB_HOST", "127.0.0.1")
    port: int = int(os.getenv("PAPERRADAR_DB_PORT", "5432"))
    name: str = os.getenv("PAPERRADAR_DB_NAME", "paperradar")
    user: str = os.getenv("PAPERRADAR_DB_USER", "paperradar")
    password: str = os.getenv("PAPERRADAR_DB_PASSWORD", "paperradar")

    @property
    def dsn(self) -> str:
        return (
            f"postgresql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
        )


db_settings = DatabaseSettings()
