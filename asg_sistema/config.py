"""Configuracao centralizada do sistema ASG.
Carrega valores do arquivo .env sem necessidade de alterar codigo-fonte.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_FILE)


class Configuracao(BaseSettings):
    db_host: str = "localhost"
    db_port: int = 5432
    db_nome: str = "asg_sp"
    db_usuario: str = "asg_user"
    db_senha: str = "asg_pass"

    modelo_spacy: str = "pt_core_news_sm"
    modelo_embeddings: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    dimensao_embedding: int = 384

    busca_top_k: int = 15
    confianca_minima: float = 0.3

    api_host: str = "0.0.0.0"
    api_porta: int = 8000

    class Config:
        env_file = _ENV_FILE
        env_prefix = "ASG_"

    @property
    def db_url(self) -> str:
        return (
            f"postgresql://{self.db_usuario}:{self.db_senha}"
            f"@{self.db_host}:{self.db_port}/{self.db_nome}"
            f"?client_encoding=utf8"
        )

    @property
    def caminho_dados(self) -> Path:
        return Path(__file__).resolve().parent.parent / "dados"

    @property
    def caminho_modelos(self) -> Path:
        return Path(__file__).resolve().parent.parent / "modelos_salvos"

    @property
    def caminho_treinamento(self) -> Path:
        return Path(__file__).resolve().parent.parent / "dados_treinamento"

    @property
    def etl_api_cooldown_segundos(self) -> int:
        """Intervalo mínimo entre POST /api/etl/executar: 1h em production, 5s em development."""
        amb = (os.environ.get("ENV") or os.environ.get("ASG_ENV") or "development").strip().lower()
        return 3600 if amb == "production" else 5


config = Configuracao()
