"""Decomposição de perguntas multi-intenção em subconsultas independentes.

Eixos que o planner entende:
- código CAR / cod_imovel (consulta espacial por imóvel rural)
- múltiplos municípios
- múltiplas intenções (queimadas, desmatamento, etc.)

Qualquer combinação vira um produto cartesiano de SubConsultas, que o executor
roda em paralelo e o agregador junta em uma ConsultaResponse com `grupos`.
"""

from dataclasses import dataclass, field
from typing import Literal


EixoAgrupamento = Literal["unico", "municipio", "intencao", "composto"]


@dataclass
class SubConsulta:
    intencao: str
    confianca: float
    municipio: str | None
    periodo: dict
    cod_imovel: str | None
    rotulo: str

    @property
    def eh_car(self) -> bool:
        return bool(self.cod_imovel)

    def entidades(self, base: dict) -> dict:
        """Deriva um dict de entidades específico desta subconsulta."""
        ent = dict(base)
        ent["municipios"] = [self.municipio] if self.municipio else []
        ent["periodo"] = self.periodo
        if self.cod_imovel:
            ent["cod_imovel"] = self.cod_imovel
        else:
            ent.pop("cod_imovel", None)
        return ent


@dataclass
class ExecutionPlan:
    subconsultas: list[SubConsulta]
    eixo_agrupamento: EixoAgrupamento
    intencao_principal: str
    confianca_principal: float
    intencoes_detectadas: list[dict] = field(default_factory=list)

    @property
    def eh_trivial(self) -> bool:
        return len(self.subconsultas) <= 1


_NOMES_INTENCAO = {
    "consultar_queimadas": "queimadas",
    "consultar_desmatamento": "desmatamento",
    "consultar_terra_indigena": "terras indígenas",
    "consultar_unidade_conservacao": "unidades de conservação",
    "consultar_quilombola": "quilombolas",
    "consultar_prodes": "PRODES",
    "consultar_imovel_rural": "imóveis rurais",
    "resumo_municipal": "resumo",
}


def planejar(
    intencao_principal: str,
    confianca_principal: float,
    intencoes_secundarias: list[tuple[str, float]],
    entidades: dict,
) -> ExecutionPlan:
    """Constrói o plano de execução a partir das intenções + entidades extraídas."""
    cod_imovel = entidades.get("cod_imovel")
    if not cod_imovel and entidades.get("codigos_car"):
        cod_imovel = entidades["codigos_car"][0]

    municipios = entidades.get("municipios") or []
    periodo = entidades.get("periodo") or {}

    subs: list[SubConsulta] = []

    # Eixo 1: CAR. Sempre vira 1 subconsulta dedicada quando presente.
    if cod_imovel:
        subs.append(
            SubConsulta(
                intencao="consultar_imovel_rural",
                confianca=max(confianca_principal, 0.95),
                municipio=None,
                periodo=periodo,
                cod_imovel=cod_imovel,
                rotulo=_rotulo_car(cod_imovel),
            )
        )

    # Eixo 2+3: intenções de BUSCA (tudo que não seja "consultar_imovel_rural"
    # quando já temos um CAR) × municípios.
    intencoes: list[tuple[str, float]] = [(intencao_principal, confianca_principal)]
    intencoes.extend(intencoes_secundarias)

    if cod_imovel:
        # Com CAR, a intenção "consultar_imovel_rural" é absorvida pela
        # subconsulta CAR. Mantemos apenas as outras intenções.
        intencoes = [(i, c) for i, c in intencoes if i != "consultar_imovel_rural"]
        if not intencoes and municipios:
            # Usuário citou CAR + município sem intenção específica →
            # usa resumo_municipal pro lado "situação do município".
            intencoes = [("resumo_municipal", confianca_principal)]

    if intencoes:
        eixos_municipio: list[str | None] = list(municipios) if municipios else [None]
        for intent, conf in intencoes:
            for mun in eixos_municipio:
                rotulo = _montar_rotulo(
                    intent,
                    mun,
                    n_intent=len(intencoes),
                    n_mun=len(eixos_municipio),
                    tem_car=bool(cod_imovel),
                )
                subs.append(
                    SubConsulta(
                        intencao=intent,
                        confianca=conf,
                        municipio=mun,
                        periodo=periodo,
                        cod_imovel=None,
                        rotulo=rotulo,
                    )
                )

    if not subs:
        # Fallback defensivo.
        subs.append(
            SubConsulta(
                intencao=intencao_principal,
                confianca=confianca_principal,
                municipio=None,
                periodo=periodo,
                cod_imovel=None,
                rotulo=_NOMES_INTENCAO.get(intencao_principal, intencao_principal),
            )
        )

    eixo = _inferir_eixo(
        n_intent=len(intencoes) if intencoes else 0,
        n_mun=len([m for m in (municipios or [])]),
        tem_car=bool(cod_imovel),
    )

    lista_intencoes = [
        {"intencao": i, "confianca": round(c, 3)}
        for i, c in [(intencao_principal, confianca_principal)] + list(intencoes_secundarias)
    ]

    return ExecutionPlan(
        subconsultas=subs,
        eixo_agrupamento=eixo,
        intencao_principal=intencao_principal,
        confianca_principal=confianca_principal,
        intencoes_detectadas=lista_intencoes,
    )


def _rotulo_car(cod_imovel: str) -> str:
    """Rótulo curto e identificável pro CAR."""
    cod = cod_imovel or ""
    if len(cod) > 22:
        return f"Imóvel {cod[:12]}…{cod[-6:]}"
    return f"Imóvel {cod}"


def _montar_rotulo(
    intent: str, municipio: str | None, n_intent: int, n_mun: int, tem_car: bool,
) -> str:
    nome_intent = _NOMES_INTENCAO.get(intent, intent)
    if n_intent > 1 and n_mun > 1:
        return f"{municipio} · {nome_intent}"
    if n_mun > 1:
        return municipio or nome_intent
    if n_intent > 1:
        return nome_intent
    if municipio:
        return municipio
    # Subconsulta solitária ao lado do CAR → usa o município se existir,
    # senão o nome da intenção (ex.: "resumo do Estado de SP").
    return nome_intent


def _inferir_eixo(n_intent: int, n_mun: int, tem_car: bool) -> EixoAgrupamento:
    if tem_car and (n_intent > 0 or n_mun > 1):
        return "composto"
    if n_intent > 1 and n_mun > 1:
        return "composto"
    if n_mun > 1:
        return "municipio"
    if n_intent > 1:
        return "intencao"
    return "unico"
