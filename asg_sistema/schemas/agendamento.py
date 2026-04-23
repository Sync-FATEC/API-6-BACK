"""Schemas Pydantic para o endpoint de agendamento de atualização."""

from datetime import date, datetime, time, timezone
from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator, field_serializer


# Unidades de recorrência aceitas pelo endpoint
UnidadeRecorrencia = Literal["minuto", "hora", "dia", "semana", "mes"]


def _dia_semana_cron(data_base: date) -> int:
    """Converte weekday Python (seg=0..dom=6) para cron (dom=0..sab=6)."""
    return (data_base.weekday() + 1) % 7


def recorrencia_para_cron(
    intervalo: int,
    unidade: UnidadeRecorrencia,
    horario: time,
    data_base: Optional[date] = None,
) -> str:
    """
    Converte uma recorrência simples em expressão cron.

    Exemplos:
      intervalo=1, unidade="dia",    horario=02:00  →  "0 2 * * *"
      intervalo=2, unidade="dia",    horario=08:30  →  "30 8 */2 * *"
      intervalo=1, unidade="semana", horario=03:00, data_base=2026-04-07 → "0 3 * * 2" (terça)
      intervalo=2, unidade="semana", horario=03:00, data_base=2026-04-07 → "0 3 7-31/14 * *"
      intervalo=1, unidade="mes",    horario=01:00, data_base=2026-04-15 → "0 1 15 * *"
      intervalo=3, unidade="mes",    horario=01:00, data_base=2026-04-15 → "0 1 15 */3 *"
            intervalo=5, unidade="minuto"                →  "*/5 * * * *"
            intervalo=1, unidade="hora"                  →  "0 */1 * * *"
    """
    m = horario.minute
    h = horario.hour
    dia_base = data_base.day if data_base else 1

    if unidade == "minuto":
        return f"*/{intervalo} * * * *"
    elif unidade == "hora":
        return f"0 */{intervalo} * * *"
    elif unidade == "dia":
        if intervalo == 1:
            return f"{m} {h} * * *"
        return f"{m} {h} */{intervalo} * *"
    elif unidade == "semana":
        if data_base:
            if intervalo == 1:
                return f"{m} {h} * * {_dia_semana_cron(data_base)}"
            # Para intervalo > 1, usa */dias (não anchora em dia_base que pode gerar range inválido)
            return f"{m} {h} */{intervalo * 7} * *"
        if intervalo == 1:
            return f"{m} {h} * * 0"       # toda semana no domingo
        return f"{m} {h} */{intervalo * 7} * *"
    elif unidade == "mes":
        if intervalo == 1:
            return f"{m} {h} {dia_base} * *"
        return f"{m} {h} {dia_base} */{intervalo} *"

    raise ValueError(f"Unidade desconhecida: {unidade}")


class AgendamentoCreate(BaseModel):
    intervalo: int = Field(
        ...,
        ge=1,
        description="Quantidade de unidades entre cada execução. Mínimo: 1.",
        json_schema_extra={"example": 1},
    )
    unidade: UnidadeRecorrencia = Field(
        ...,
        description="Unidade de tempo: 'minuto', 'hora', 'dia', 'semana' ou 'mes'.",
        json_schema_extra={"example": "semana"},
    )
    horario: time = Field(
        default=time(2, 0),
        description=(
            "Horário do dia em que a coleta será executada (HH:MM, fuso America/Sao_Paulo). "
            "Ignorado quando unidade='hora' ou unidade='minuto'."
        ),
        json_schema_extra={"example": "02:00"},
    )
    data_inicio: Optional[date] = Field(
        default=None,
        description=(
            "Data base para ancorar recorrências semanais/mensais. "
            "Ex.: unidade='semana' usa o dia da semana desta data; unidade='mes' usa o dia do mês desta data."
        ),
        json_schema_extra={"example": "2026-04-08"},
    )
    etapa: str = Field(
        default="full",
        description="Etapa do pipeline a executar: 'extract', 'load', 'embed', 'validate' ou 'full'.",
        json_schema_extra={"example": "full"},
    )

    @model_validator(mode="after")
    def validar_intervalo_por_unidade(self) -> "AgendamentoCreate":
        limites = {"minuto": 59, "hora": 23, "dia": 30, "semana": 52, "mes": 12}
        limite = limites[self.unidade]
        if self.intervalo > limite:
            raise ValueError(
                f"Para unidade='{self.unidade}', intervalo deve ser entre 1 e {limite}."
            )
        return self

    @property
    def cron_expressao(self) -> str:
        return recorrencia_para_cron(
            self.intervalo,
            self.unidade,
            self.horario,
            data_base=self.data_inicio,
        )


class AgendamentoUpdate(BaseModel):
    intervalo: Optional[int] = Field(default=None, ge=1, json_schema_extra={"example": 2})
    unidade: Optional[UnidadeRecorrencia] = Field(default=None, json_schema_extra={"example": "mes"})
    horario: Optional[time] = Field(default=None, json_schema_extra={"example": "03:00"})
    data_inicio: Optional[date] = Field(default=None, json_schema_extra={"example": "2026-04-08"})
    etapa: Optional[str] = Field(default=None, json_schema_extra={"example": "full"})
    ativo: Optional[bool] = None


class AgendamentoResponse(BaseModel):
    id: int
    intervalo: int
    unidade: str
    horario: str                      # "HH:MM" para fácil leitura
    etapa: str                        # "extract" | "load" | "embed" | "validate" | "full"
    cron_expressao: str
    ativo: bool
    criado_em: datetime
    atualizado_em: datetime
    ultima_execucao_em: Optional[datetime]
    ultimo_status: Optional[str]
    ultima_mensagem: Optional[str]

    model_config = {"from_attributes": True}

    @field_serializer('criado_em', 'atualizado_em', 'ultima_execucao_em', when_used='json')
    def serialize_datetime(self, value: Optional[datetime]) -> Optional[str]:
        """Adiciona timezone explicit (+00:00) às datas para conversão correta no frontend"""
        if value is None:
            return None
        # Se não tem timezone, assume UTC
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()


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