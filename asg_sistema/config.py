"""Configuracao centralizada do sistema ASG.
Carrega valores do arquivo .env sem necessidade de alterar codigo-fonte.
"""

from pathlib import Path

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_FILE)


class Configuracao(BaseSettings):
    db_host: str = "localhost"
    db_port: int = 5433
    db_nome: str = "asg_sp"
    db_usuario: str = "asg_user"
    db_senha: str = "asg_pass"

    modelo_spacy: str = "pt_core_news_md"
    modelo_embeddings: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    dimensao_embedding: int = 384

    # ---- Caminho analítico (Text-to-SQL local) ----
    sql_timeout_ms: int = 5000
    sql_max_limit: int = 100
    analitico_confianca_minima: float = 0.35
    # Fallback generativo local (transformers). OFF por padrão (máquina modesta).
    gerador_local_ativo: bool = False
    gerador_local_modelo: str = "cssupport/t5-small-awesome-text-to-sql"
    # Credenciais read-only (caem p/ as principais quando ausentes).
    db_usuario_ro: str | None = None
    db_senha_ro: str | None = None

    busca_top_k: int = 15
    confianca_minima: float = 0.3
    uf_escopo: str = "SP"

    api_host: str = "0.0.0.0"
    api_porta: int = 8000

    env: str = "development"
    etl_retry_intervalo_segundos: int | None = None
    etl_retry_max_tentativas: int = 3

    jwt_segredo: str
    jwt_algoritmo: str = "HS256"
    jwt_expiracao_minutos: int = 60 * 24

    # ===========================================================
    # TODO: Configurar variáveis abaixo para envio de e-mail.
    # Crie uma senha de app no Google:
    #   Conta Google > Segurança > Verificação em 2 etapas > Senhas de app
    # Adicione ao .env:
    #   ASG_EMAIL_REMETENTE=seu_email@gmail.com
    #   ASG_EMAIL_SENHA_APP=xxxx xxxx xxxx xxxx   (senha de app de 16 dígitos)
    # ===========================================================
    email_remetente: str | None = None
    email_senha_app: str | None = None
    # URL base da API em produção — usada para gerar qgis_url nas respostas
    api_url_production: str = "http://asg-backend-alb-85114170.us-east-1.elb.amazonaws.com"
    # URL base do frontend em produção — usada no link de redefinição de senha enviado por e-mail
    frontend_url_production: str = "https://asg-visiona.vercel.app"

    def get_api_url(self) -> str:
        """Retorna a URL base da API baseado no ambiente."""
        if self.env == "production":
            return self.api_url_production
        return "http://localhost:8000"

    def get_frontend_url(self) -> str:
        """Retorna a URL base do frontend baseado no ambiente."""
        if self.env == "production":
            return self.frontend_url_production
        return "http://localhost:3000"

    @field_validator("jwt_segredo")
    @classmethod
    def jwt_segredo_nao_vazio(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            raise ValueError(
                "Defina ASG_JWT_SEGREDO no .env (ou variável de ambiente); "
                "use uma string longa e aleatória, nunca commite o valor real."
            )
        return s

    class Config:
        env_file = _ENV_FILE
        env_prefix = "ASG_"
        extra = "ignore"  # tolera chaves extras no .env (ex.: DATABASE_URL) sem quebrar

    @property
    def db_url(self) -> str:
        return (
            f"postgresql://{self.db_usuario}:{self.db_senha}"
            f"@{self.db_host}:{self.db_port}/{self.db_nome}"
            f"?client_encoding=utf8"
        )

    @property
    def usuario_ro(self) -> str:
        return self.db_usuario_ro or self.db_usuario

    @property
    def senha_ro(self) -> str:
        return self.db_senha_ro or self.db_senha

    @property
    def db_url_readonly(self) -> str:
        return (
            f"postgresql://{self.usuario_ro}:{self.senha_ro}"
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
        return 5 if self.env == "production" else 5

    @property
    def etl_retry_intervalo_erro_api_segundos(self) -> int:
        """Intervalo entre retentativas quando uma API externa está indisponível."""
        if self.etl_retry_intervalo_segundos is not None:
            return self.etl_retry_intervalo_segundos
        # Em produção mantém 1 hora; em dev/testes reduz para 2 minutos.
        return 5 if self.env == "production" else 5


config = Configuracao()
