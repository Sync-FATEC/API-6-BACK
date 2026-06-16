"""Representação intermediária (IR) do caminho analítico.

Dois modos:
- "agregacao": COUNT/SUM/AVG + GROUP BY (+ HAVING, distribuição/%, multi-métrica).
- "fato": ranking/filtro/listagem sobre colunas concretas (feature store OU tabela
  base), sem agregação — usa `coluna_ordem`, `colunas_saida` e filtros ricos.

Filtros (dict): chave = coluna (ou especial); valor pode ser:
  - escalar (igualdade; municipio usa ILIKE; lista de municipios vira OR de ILIKE)
  - bool                              -> coluna = TRUE/FALSE
  - ("op", valor) com op em > >= < <= = <>
  - ("BETWEEN", [a, b])
  - ("IN", [v1, v2, ...])
  - ("ILIKE", "%texto%")
  - ("NOT", <qualquer-um-dos-acima>)  -> nega a cláusula
  - especiais: "periodo" {inicio, fim}, "proximo_ti" (bool), "municipio" (str|list)
"""

from dataclasses import dataclass, field


@dataclass
class Metrica:
    agg: str            # "COUNT" | "SUM" | "AVG" | "MIN" | "MAX"
    coluna: str | None  # None p/ COUNT(*)
    alias: str


@dataclass
class Ordem:
    por: str            # alias da métrica, nome de dimensão ou coluna
    desc: bool = True


@dataclass
class ConsultaAnalitica:
    tabela: str | None
    metrica: Metrica | None = None
    dimensoes: list[str] = field(default_factory=list)
    filtros: dict = field(default_factory=dict)
    ordem: "Ordem | None" = None
    limite: int = 100
    confianca: float = 0.0
    # modo "fato": ranking/filtro/listagem sobre colunas concretas (sem GROUP BY).
    modo: str = "agregacao"           # "agregacao" | "fato"
    coluna_ordem: str | None = None
    colunas_saida: list[str] = field(default_factory=list)
    # extensões genéricas
    metricas: list[Metrica] = field(default_factory=list)   # multi-métrica (modo agregacao)
    ordens: list[Ordem] = field(default_factory=list)        # ordenação múltipla
    having: list[tuple] = field(default_factory=list)        # [(op, valor)] na métrica primária
    distribuicao: bool = False                               # adiciona coluna percentual
    aviso: str | None = None                                 # nota de interpretação/limitação

    def metricas_efetivas(self) -> list[Metrica]:
        if self.metricas:
            return self.metricas
        return [self.metrica] if self.metrica else []

    def ordens_efetivas(self) -> list[Ordem]:
        if self.ordens:
            return self.ordens
        return [self.ordem] if self.ordem else []

    def completa(self) -> bool:
        if self.modo == "fato":
            return bool(self.tabela and (self.coluna_ordem or self.colunas_saida or self.filtros))
        return bool(self.tabela and self.metricas_efetivas())
