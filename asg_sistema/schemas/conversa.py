"""Schemas Pydantic para o histórico de conversas."""

from datetime import datetime
from pydantic import BaseModel


class ConversaUpdate(BaseModel):
    titulo: str


class MensagemPreview(BaseModel):
    id: int
    papel: str
    conteudo_texto: str
    intencao_detectada: str | None = None
    entidades_json: dict | None = None
    tem_dados_geo: bool
    criado_em: datetime

    model_config = {"from_attributes": True}


class ConversaListItem(BaseModel):
    id: int
    titulo: str
    criado_em: datetime
    atualizado_em: datetime
    total_mensagens: int
    primeira_mensagem: str | None = None

    model_config = {"from_attributes": True}


class ConversaDetalhe(BaseModel):
    id: int
    titulo: str
    criado_em: datetime
    atualizado_em: datetime
    mensagens: list[MensagemPreview]

    model_config = {"from_attributes": True}


class MensagemDadosResponse(BaseModel):
    mensagem_id: int
    geojson: dict | None = None
    estatisticas: dict | None = None
    nota_risco: dict | None = None
    grupos: list | None = None
    fontes: list | None = None

    model_config = {"from_attributes": True}
