"""Schemas Pydantic para o endpoint de agendamento de atualização."""

from datetime import datetime, time
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


# Unidades de recorrência aceitas pelo endpoint
UnidadeRecorrencia = Literal["hora", "dia", "semana", "mes"]


def recorrencia_para_cron(intervalo: int, unidade: UnidadeRecorrencia, horario: time) -> str:
    """
    Converte uma recorrência simples em expressão cron.

    Exemplos:
      intervalo=1, unidade="dia",    horario=02:00  →  "0 2 * * *"
      intervalo=2, unidade="dia",    horario=08:30  →  "30 8 */2 * *"
      intervalo=1, unidade="semana", horario=03:00  →  "0 3 * * 0"   (domingo)
      intervalo=2, unidade="semana", horario=03:00  →  "0 3 */14 * *" (a cada 14 dias)
      intervalo=1, unidade="mes",    horario=01:00  →  "0 1 1 * *"
      intervalo=3, unidade="mes",    horario=01:00  →  "0 1 1 */3 *"
      intervalo=1, unidade="hora"                   →  "0 */1 * * *"
    """
    m = horario.minute
    h = horario.hour

    if unidade == "hora":
        return f"0 */{intervalo} * * *"
    elif unidade == "dia":
        if intervalo == 1:
            return f"{m} {h} * * *"
        return f"{m} {h} */{intervalo} * *"
    elif unidade == "semana":
        if intervalo == 1:
            return f"{m} {h} * * 0"       # toda semana no domingo
        return f"{m} {h} */{intervalo * 7} * *"
    elif unidade == "mes":
        if intervalo == 1:
            return f"{m} {h} 1 * *"       # todo mês no dia 1
        return f"{m} {h} 1 */{intervalo} *"

    raise ValueError(f"Unidade desconhecida: {unidade}")


class AgendamentoCreate(BaseModel):
    intervalo: int = Field(
        ...,
        ge=1,
        example=1,
        description="Quantidade de unidades entre cada execução. Mínimo: 1.",
    )
    unidade: UnidadeRecorrencia = Field(
        ...,
        example="semana",
        description="Unidade de tempo: 'hora', 'dia', 'semana' ou 'mes'.",
    )
    horario: time = Field(
        default=time(2, 0),
        example="02:00",
        description=(
            "Horário do dia em que a coleta será executada (HH:MM, fuso America/Sao_Paulo). "
            "Ignorado quando unidade='hora'."
        ),
    )

    @model_validator(mode="after")
    def validar_intervalo_por_unidade(self) -> "AgendamentoCreate":
        limites = {"hora": 23, "dia": 30, "semana": 52, "mes": 12}
        limite = limites[self.unidade]
        if self.intervalo > limite:
            raise ValueError(
                f"Para unidade='{self.unidade}', intervalo deve ser entre 1 e {limite}."
            )
        return self

    @property
    def cron_expressao(self) -> str:
        return recorrencia_para_cron(self.intervalo, self.unidade, self.horario)


class AgendamentoUpdate(BaseModel):
    intervalo: Optional[int] = Field(None, ge=1, example=2)
    unidade: Optional[UnidadeRecorrencia] = Field(None, example="mes")
    horario: Optional[time] = Field(None, example="03:00")
    ativo: Optional[bool] = None


class AgendamentoResponse(BaseModel):
    id: int
    intervalo: int
    unidade: str
    horario: str                      # "HH:MM" para fácil leitura
    cron_expressao: str
    ativo: bool
    criado_em: datetime
    atualizado_em: datetime
    ultima_execucao_em: Optional[datetime]
    ultimo_status: Optional[str]
    ultima_mensagem: Optional[str]

    model_config = {"from_attributes": True}


class StatusExecucaoResponse(BaseModel):
    agendamento_id: int
    intervalo: int
    unidade: str
    horario: str
    cron_expressao: str
    ativo: bool
    job_registrado_no_scheduler: bool
    ultima_execucao_em: Optional[datetime]
    ultimo_status: Optional[str]
    ultima_mensagem: Optional[str]