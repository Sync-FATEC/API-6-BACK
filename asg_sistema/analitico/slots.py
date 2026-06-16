"""Extração de slots → IR ConsultaAnalitica (semantic parsing híbrido).

Divisão de trabalho:
- TABELA: decidida por embeddings (SchemaLinker) — o ponto forte do modelo.
- MÉTRICA, DIMENSÕES, ORDEM/LIMITE, PERÍODO: por regex determinístico — mais
  confiável e auditável que embeddings para slots estruturais.
- FILTROS de valor (município/status): via ExtratorEntidades (RapidFuzz).
"""

import re

from asg_sistema.analitico.catalogo import METRICAS, DIMENSOES, TABELAS_PERMITIDAS
from asg_sistema.analitico.colunas import ligar_coluna, colunas_numericas, tipo_coluna
from asg_sistema.analitico.ir import ConsultaAnalitica, Metrica, Ordem
from asg_sistema.analitico.texto import normalizar

_RE_TOPN = re.compile(
    r"\btop\s*(\d{1,3})\b|\b(\d{1,3})\s+(?:cidades|munic[ií]pios|maiores|menores)\b",
    re.IGNORECASE,
)
_RE_MAIS = re.compile(r"\b(mais|maiores?|maior)\b", re.IGNORECASE)
_RE_MENOS = re.compile(r"\b(menos|menores?|menor)\b", re.IGNORECASE)
_RE_CIDADE = re.compile(r"\b(cidades?|munic[ií]pios?)\b", re.IGNORECASE)
_LIMITE_RANKING_PADRAO = 10

# Dimensões por regex (determinístico). Ordem define a ordem do GROUP BY.
_DIM_REGEX = [
    ("municipio", re.compile(r"\bpor\s+(munic[ií]pio|cidade)s?\b|\bmunic[ií]pios?\b|\bcidades?\b", re.IGNORECASE)),
    ("ano", re.compile(r"\bpor\s+anos?\b|\banual\b|ao longo dos anos", re.IGNORECASE)),
    # "por mês"/"quais meses" = dimensão; "últimos N meses" é período (não casa aqui)
    ("mes", re.compile(r"\bpor\s+m[êe]s\b|\bmensal\b|quais\s+m[êe]s|meses\s+do\s+ano", re.IGNORECASE)),
    ("bioma", re.compile(r"\bpor\s+bioma\b|\bbiomas?\b", re.IGNORECASE)),
    ("satelite", re.compile(r"\bsat[ée]lites?\b", re.IGNORECASE)),
    ("classe", re.compile(r"\bpor\s+(classe|tipo|categoria)\b", re.IGNORECASE)),
    ("estado", re.compile(r"\bpor\s+estado\b", re.IGNORECASE)),
    ("status", re.compile(r"\bpor\s+status\b", re.IGNORECASE)),
]

# Métrica por regex.
_RE_MEDIA = re.compile(r"\bm[ée]dia?\b|\bm[ée]dio\b", re.IGNORECASE)
_RE_SOMA = re.compile(r"\b[áa]rea\b|\btotal\b|\bsoma\b|\bsomat[óo]rio\b|\bhectares?\b|\bkm2\b|km²", re.IGNORECASE)
_RE_CONTA = re.compile(r"\bquant[oa]s?\b|\bn[úu]mero\b|\bcontagem\b|\bquantidade\b", re.IGNORECASE)

# Período só vale se houver marcador temporal REAL (evita "por ano" virar filtro).
_RE_PERIODO_REAL = re.compile(
    r"\b[úu]ltim[oa]s?\b|\bpassad[oa]\b|\brecente\b|\bdesde\b|\bdias?\b|\bsemanas?\b|"
    r"\btrimestre\b|\bsemestre\b|\bhoje\b|\bontem\b",
    re.IGNORECASE,
)

# ---- sinais do modo PROPRIEDADE (consulta sobre fato_propriedade_ambiental) ----
_FATO = "fato_propriedade_ambiental"
_RE_FOCOS = re.compile(r"\b(focos?|inc[êe]ndios?|queimadas?)\b", re.IGNORECASE)
_RE_RISCO = re.compile(r"\brisco\b", re.IGNORECASE)
_RE_AREA_PCT = re.compile(r"(percentual|%|propor[çc][ãa]o).*\b[áa]rea|[áa]rea\s+impactada", re.IGNORECASE)
_RE_ALERTAS = re.compile(r"\balertas?\b.*desmatamento|\balertas?\s+recentes?\b", re.IGNORECASE)
_RE_PROX_TI = re.compile(r"pr[óo]xim\w*\s+(de\s+)?terras?\s+ind[íi]gen|sobrep[õo]\w*\s+terras?\s+ind[íi]gen", re.IGNORECASE)
_RE_RECORRENTE = re.compile(r"\brecorrent\w*\b", re.IGNORECASE)
_RE_APOS_ALERTA = re.compile(r"\b(ap[óo]s|depois)\b.*alert", re.IGNORECASE)
_RE_FATORES = re.compile(r"\bfator(?:es)?\b", re.IGNORECASE)
_RE_MAIS_DE_N = re.compile(r"mais\s+de\s+(\d{1,2}|tr[êe]s|dois|quatro|cinco)", re.IGNORECASE)
_RE_AUMENTO_RISCO = re.compile(r"(aumento|crescimento|contribu[íi]ram).*risco", re.IGNORECASE)
_NUM_EXTENSO = {"dois": 2, "tres": 3, "três": 3, "quatro": 4, "cinco": 5}

# views pré-agregadas (tendência / eventos multi-fonte)
_RE_CRESCIMENTO = re.compile(r"\b(crescimento|aumento|cresc\w*|aument\w*)\b", re.IGNORECASE)
_RE_EVENTOS = re.compile(r"eventos?\s+ambient\w*|eventos?\s+cr[íi]tic\w*", re.IGNORECASE)

# ---- novos arquétipos genéricos ----
_RE_DISTRIB = re.compile(r"\bpercentual\b|\bpropor[çc][ãa]o\b|\bdistribui[çc][ãa]o\b|%", re.IGNORECASE)
_RE_ANOS = re.compile(r"\b(19|20)\d{2}\b")
_RE_ENTRE = re.compile(r"\bentre\s+([\d.]+)\s+e\s+([\d.]+)", re.IGNORECASE)
_RE_MAIOR_QUE = re.compile(r"\b(?:maior|acima|superior|mais)\s+(?:que|de|do que|a)?\s*([\d.]+)", re.IGNORECASE)
_RE_MENOR_QUE = re.compile(r"\b(?:menor|abaixo|inferior|menos)\s+(?:que|de|do que|a)?\s*([\d.]+)", re.IGNORECASE)
_RE_NEG = re.compile(r"\bsem\b|\bn[ãa]o\s+(?:t[êe]m|possui|tiveram|tem)\b|\bnenhum[ao]?\b|\bexceto\b|\bfora de\b", re.IGNORECASE)
_RE_HAVING = re.compile(r"\bmais\s+de\s+(\d{1,6})\b|\bacima\s+de\s+(\d{1,6})\b|\b(\d{1,6})\s+ou\s+mais\b", re.IGNORECASE)
# alvo de listagem -> tabela base
_RE_LISTAR = re.compile(r"\bliste\b|\blistar\b|\bmostre\b|\bquais\s+(s[ãa]o\s+)?(os|as)\b", re.IGNORECASE)
_ALVO_TABELA = [
    (re.compile(r"terras?\s+ind[íi]gen", re.IGNORECASE), "terras_indigenas"),
    (re.compile(r"unidades?\s+de\s+conserva|\bUCs?\b|parques?|reservas?", re.IGNORECASE), "unidades_conservacao"),
    (re.compile(r"quilombol", re.IGNORECASE), "comunidades_quilombolas"),
    (re.compile(r"im[óo]ve(?:l|is)|propriedades?|fazendas?|s[íi]tios?|car\b|sicar", re.IGNORECASE), "sicar_imoveis"),
    (re.compile(r"queimadas?|focos?|inc[êe]ndio", re.IGNORECASE), "queimadas"),
    (re.compile(r"alertas?|desmatamento|deter", re.IGNORECASE), "desmatamento_alertas"),
]


def _num(s: str):
    try:
        return int(s) if "." not in s else float(s)
    except (ValueError, TypeError):
        return None


# follow-up: pergunta curta/anafórica que herda o contexto anterior
_RE_FOLLOWUP = re.compile(
    r"^\s*e\s+(em|no|na|nos|nas|os|as|de|para|pra|qual|quais|quanto)\b|^\s*e\s+\w+\?*\s*$",
    re.IGNORECASE,
)


# Palavra-chave -> tabela base (piso de confiança quando o embedding fica incerto).
_TABELA_KEYWORDS = [
    (re.compile(r"queimad|\bfocos?\b|inc[êe]ndio", re.IGNORECASE), "queimadas"),
    (re.compile(r"desmatamento|\balertas?\b|\bdeter\b|prodes", re.IGNORECASE), "desmatamento_alertas"),
    (re.compile(r"im[óo]ve(?:l|is)|propriedades?|fazendas?|s[íi]tios?|sicar|\bcar\b|m[óo]dulos?\s+fiscai|\bstatus\b", re.IGNORECASE), "sicar_imoveis"),
    (re.compile(r"terras?\s+ind[íi]gen", re.IGNORECASE), "terras_indigenas"),
    (re.compile(r"unidades?\s+de\s+conserva|\bUCs?\b", re.IGNORECASE), "unidades_conservacao"),
    (re.compile(r"quilombol", re.IGNORECASE), "comunidades_quilombolas"),
]


def _tabela_por_keyword(pergunta: str) -> str | None:
    for rx, tab in _TABELA_KEYWORDS:
        if rx.search(pergunta):
            return tab
    return None


# Coluna "de tamanho" padrão por tabela (para superlativos sem coluna explícita).
_COL_TAMANHO = {
    "sicar_imoveis": "num_area",
    "prodes_desmatamento": "area_km",
    "desmatamento_alertas": "area_total_km2",
    "terras_indigenas": "area_ha",
    "unidades_conservacao": "area_ha",
}

# Colunas de saída preferidas por tabela (listagem/superlativo).
_COLS_SAIDA = {
    "sicar_imoveis": ["cod_imovel", "municipio", "num_area", "ind_status"],
    "prodes_desmatamento": ["classe_nome", "ano", "area_km", "estado"],
    "desmatamento_alertas": ["municipio", "classe", "area_total_km2", "data_avistamento"],
    "terras_indigenas": ["nome", "municipio", "etnia", "area_ha", "fase"],
    "unidades_conservacao": ["nome", "municipio", "categoria", "grupo", "esfera", "area_ha"],
    "comunidades_quilombolas": ["comunidade", "municipio", "regiao", "ano_certificacao"],
    "queimadas": ["municipio", "data_hora", "frp", "satelite", "bioma"],
}


class ExtratorSlots:
    def __init__(self, linker, extrator_entidades):
        self.linker = linker
        self.entidades = extrator_entidades

    def extrair(self, pergunta: str, rota: str = "ANALITICA", contexto: dict | None = None) -> ConsultaAnalitica:
        # follow-up conversacional: herda o contexto anterior e troca só o que mudou
        if contexto:
            seguimento = self._followup(pergunta, contexto)
            if seguimento is not None:
                return seguimento
        if rota == "PROPRIEDADE":
            return self._extrair_propriedade(pergunta)
        if rota == "LISTAGEM":
            ir = self._extrair_listagem(pergunta)
            if ir is not None:
                return ir
        # casos especiais de views pré-agregadas (tendência, eventos multi-fonte)
        especial = self._caso_especial_view(pergunta)
        if especial is not None:
            return especial
        link = self.linker.ligar(pergunta)
        ent = self.entidades.extrair(pergunta)

        # ----- ordem + limite (ranking) -----
        tem_menos = bool(_RE_MENOS.search(pergunta))
        tem_mais = bool(_RE_MAIS.search(pergunta))
        m = _RE_TOPN.search(pergunta)
        n = int(m.group(1) or m.group(2)) if m else None
        eh_ranking = bool(m or tem_mais or tem_menos)
        desc = not tem_menos  # "menos/menores" => ASC
        limite = n if n else (_LIMITE_RANKING_PADRAO if eh_ranking else 100)

        # ----- dimensões por regex (determinístico, evita over-grouping) -----
        dims_pedidas = [nome for nome, rx in _DIM_REGEX if rx.search(pergunta)]
        if ent.get("municipios") and "municipio" not in dims_pedidas:
            # município citado como filtro também serve de agrupamento natural
            dims_pedidas.insert(0, "municipio")

        # ----- tabela: embedding + piso por palavra-chave (não depende só do cosseno) -----
        tabela = link.tabela
        conf = link.confianca
        tab_kw = _tabela_por_keyword(pergunta)
        # entidades distintas (embedam mal) têm prioridade sobre o cosseno
        _ENT_FORTES = {"terras_indigenas", "unidades_conservacao",
                       "comunidades_quilombolas", "sicar_imoveis"}
        if tab_kw and (not tabela or conf < 0.45 or tab_kw in _ENT_FORTES):
            tabela = tab_kw
            conf = max(conf, 0.6)
        if (_RE_CIDADE.search(pergunta) and tabela
                and "municipio" not in DIMENSOES.get(tabela, {})):
            for alt, score in link.tabelas:
                if "municipio" in DIMENSOES.get(alt, {}) and score >= 0.4:
                    tabela = alt
                    break

        # ----- métrica por regex (fallback no embedding) -----
        agg = self._agg_por_regex(pergunta) or link.metrica_agg
        metrica = self._resolver_metrica(tabela, agg, pergunta)

        # ----- comparação temporal: anos explícitos (2023 vs 2024) -----
        anos = [int(a) for a in re.findall(r"\b(?:19|20)\d{2}\b", pergunta)]
        if anos and "ano" not in dims_pedidas and len(anos) >= 2:
            dims_pedidas.append("ano")  # comparar entre anos => agrupar por ano

        # ----- dimensões válidas para a tabela escolhida -----
        dims_validas: list[str] = []
        if tabela:
            permitidas = DIMENSOES.get(tabela, {})
            dims_validas = [d for d in dims_pedidas if d in permitidas]
            if eh_ranking and not dims_validas and "municipio" in permitidas and _RE_CIDADE.search(pergunta):
                dims_validas = ["municipio"]

        # ----- superlativo por coluna (sem agrupamento): "5 maiores imóveis", "maior área" -----
        # ranking das LINHAS por uma coluna numérica. "maior/menor X" tem precedência
        # sobre "área→soma"; só some/conta/média EXPLÍCITOS bloqueiam o superlativo.
        tem_soma_expl = bool(re.search(r"\b(total|soma|somat[óo]rio)\b", pergunta, re.IGNORECASE))
        bloqueia_sup = tem_soma_expl or bool(_RE_CONTA.search(pergunta)) or bool(_RE_MEDIA.search(pergunta))
        if eh_ranking and not dims_validas and tabela and not bloqueia_sup:
            col_sup = self._coluna_num_mencionada(pergunta, tabela) or _COL_TAMANHO.get(tabela)
            if col_sup:
                return self._listagem_ordenada(tabela, col_sup, desc, limite, ent, pergunta)

        # ----- filtros de valor -----
        filtros: dict = {}
        muns = ent.get("municipios") or []
        if len(muns) > 1:               # comparação entre municípios (A vs B)
            filtros["municipio"] = muns
            if "municipio" not in dims_validas and tabela and "municipio" in DIMENSOES.get(tabela, {}):
                dims_validas.insert(0, "municipio")
        elif muns:
            filtros["municipio"] = muns[0]
        if ent.get("status"):
            filtros["status"] = ent["status"]
        if anos:                        # restringe aos anos citados
            filtros["_anos"] = anos
        elif ent.get("periodo") and _RE_PERIODO_REAL.search(pergunta):
            filtros["periodo"] = ent["periodo"]
        # filtros numéricos genéricos (área entre X e Y, FRP > N, módulos > 50...)
        num_filtros = self._filtros_numericos(pergunta, tabela)
        filtros.update(num_filtros)

        # ----- distribuição / percentual -----
        distribuicao = bool(_RE_DISTRIB.search(pergunta)) and bool(dims_validas)

        # ----- HAVING (municípios com mais de N <métrica>) -----
        # só quando "mais de N" NÃO foi consumido por um filtro de coluna numérica.
        having = []
        mh = _RE_HAVING.search(pergunta)
        if mh and dims_validas and not num_filtros:
            n_h = next((g for g in mh.groups() if g), None)
            if n_h is not None:
                op = ">=" if "ou mais" in pergunta.lower() else ">"
                having = [(op, int(n_h))]

        ordem = Ordem(por=metrica.alias, desc=desc) if (metrica and eh_ranking) else None

        return ConsultaAnalitica(
            tabela=tabela, metrica=metrica, dimensoes=dims_validas,
            filtros=filtros, ordem=ordem, limite=limite, confianca=conf,
            distribuicao=distribuicao, having=having,
        )

    def _followup(self, pergunta: str, contexto: dict) -> "ConsultaAnalitica | None":
        """Reaproveita a consulta anterior trocando só o slot que mudou (anáfora)."""
        if not contexto or not contexto.get("tabela") or not _RE_FOLLOWUP.search(pergunta):
            return None
        ent = self.entidades.extrair(pergunta)
        filtros = dict(contexto.get("filtros") or {})
        # troca município, se citado um novo
        muns = ent.get("municipios") or []
        if muns:
            filtros["municipio"] = muns if len(muns) > 1 else muns[0]
        # troca anos, se citados
        anos = [int(a) for a in re.findall(r"\b(?:19|20)\d{2}\b", pergunta)]
        if anos:
            filtros["_anos"] = anos
            filtros.pop("periodo", None)
        # inverte direção se "maiores/menores"
        desc = contexto.get("ordem_desc", True)
        if _RE_MENOS.search(pergunta):
            desc = False
        elif _RE_MAIS.search(pergunta):
            desc = True
        m = _RE_TOPN.search(pergunta)
        limite = int(m.group(1) or m.group(2)) if m else contexto.get("limite", 100)

        modo = contexto.get("modo", "agregacao")
        coluna_ordem = contexto.get("coluna_ordem")
        ir = ConsultaAnalitica(
            tabela=contexto["tabela"], modo=modo, filtros=filtros, limite=limite,
            dimensoes=list(contexto.get("dimensoes") or []),
            colunas_saida=list(contexto.get("colunas_saida") or []),
            coluna_ordem=coluna_ordem, confianca=0.8,
            aviso="Interpretado como continuação da pergunta anterior.",
        )
        if modo == "fato":
            ir.ordem = Ordem(coluna_ordem, desc) if coluna_ordem else None
        else:
            ma = contexto.get("metrica_alias") or "total"
            ir.metrica = Metrica(contexto.get("metrica_agg", "COUNT"),
                                  contexto.get("metrica_coluna"), ma)
            ir.ordem = Ordem(ma, desc)
        return ir

    def _coluna_num_mencionada(self, pergunta: str, tabela: str | None) -> str | None:
        if not tabela:
            return None
        p = normalizar(pergunta)
        melhor, blen = None, 0
        for col, meta in colunas_numericas(tabela).items():
            for s in meta["sin"]:
                sn = normalizar(s)
                if sn and sn in p and len(sn) > blen:
                    melhor, blen = col, len(sn)
        return melhor

    def _filtros_numericos(self, pergunta: str, tabela: str | None) -> dict:
        """Filtros numéricos genéricos (BETWEEN, >, <) ligados à coluna mencionada."""
        out: dict = {}
        col = self._coluna_num_mencionada(pergunta, tabela)
        if not col:
            return out
        mb = _RE_ENTRE.search(pergunta)
        if mb:
            a, b = _num(mb.group(1)), _num(mb.group(2))
            if a is not None and b is not None:
                out[col] = ("BETWEEN", [a, b])
                return out
        mgt = _RE_MAIOR_QUE.search(pergunta)
        mlt = _RE_MENOR_QUE.search(pergunta)
        if mgt:
            v = _num(mgt.group(1))
            if v is not None:
                out[col] = (">", v)
        elif mlt:
            v = _num(mlt.group(1))
            if v is not None:
                out[col] = ("<", v)
        return out

    def _extrair_listagem(self, pergunta: str) -> "ConsultaAnalitica | None":
        """Listagem de registros de uma tabela base (SELECT colunas + filtros + LIMIT)."""
        tabela = None
        for rx, tab in _ALVO_TABELA:
            if rx.search(pergunta):
                tabela = tab
                break
        if not tabela:
            return None
        ent = self.entidades.extrair(pergunta)
        cols = TABELAS_PERMITIDAS.get(tabela, set())
        prefer = ["nome", "comunidade", "cod_imovel", "municipio", "etnia", "categoria",
                  "grupo", "esfera", "classe", "num_area", "area_ha", "area_total_km2",
                  "ind_status", "data_hora", "data_avistamento", "ano"]
        saida = [c for c in prefer if c in cols][:6] or [c for c in ("id", "municipio") if c in cols]
        filtros: dict = {}
        muns = ent.get("municipios") or []
        if muns:
            filtros["municipio"] = muns if len(muns) > 1 else muns[0]
        if ent.get("status"):
            filtros["status"] = ent["status"]
        filtros.update(self._filtros_numericos(pergunta, tabela))
        m = _RE_TOPN.search(pergunta)
        limite = int(m.group(1) or m.group(2)) if m else 100
        col_ord = None
        if _RE_MAIS.search(pergunta) or _RE_MENOS.search(pergunta):
            col_ord = self._coluna_num_mencionada(pergunta, tabela) or _COL_TAMANHO.get(tabela)
        return ConsultaAnalitica(
            tabela=tabela, modo="fato", colunas_saida=saida, filtros=filtros,
            coluna_ordem=col_ord,
            ordem=Ordem(col_ord, not bool(_RE_MENOS.search(pergunta))) if col_ord else None,
            limite=limite, confianca=0.85,
        )

    def _listagem_ordenada(self, tabela, col, desc, limite, ent, pergunta) -> ConsultaAnalitica:
        """Ranking das linhas de uma tabela por uma coluna numérica (superlativo)."""
        saida = list(_COLS_SAIDA.get(tabela, ["municipio"]))
        if col not in saida:
            saida.append(col)
        filtros: dict = {}
        muns = ent.get("municipios") or []
        if muns:
            filtros["municipio"] = muns if len(muns) > 1 else muns[0]
        if ent.get("status"):
            filtros["status"] = ent["status"]
        filtros.update(self._filtros_numericos(pergunta, tabela))
        return ConsultaAnalitica(
            tabela=tabela, modo="fato", colunas_saida=saida, filtros=filtros,
            coluna_ordem=col, ordem=Ordem(col, desc), limite=limite, confianca=0.8,
        )

    def _caso_especial_view(self, pergunta: str) -> "ConsultaAnalitica | None":
        """Intenções que mapeiam para views pré-agregadas (determinístico)."""
        m = _RE_TOPN.search(pergunta)
        limite = int(m.group(1) or m.group(2)) if m else _LIMITE_RANKING_PADRAO
        desc = not bool(_RE_MENOS.search(pergunta))

        # Tendência: "crescimento/aumento de queimadas"
        if _RE_CRESCIMENTO.search(pergunta) and _RE_FOCOS.search(pergunta):
            return ConsultaAnalitica(
                tabela="vw_queimadas_crescimento_municipio", modo="fato",
                coluna_ordem="crescimento_pct",
                colunas_saida=["municipio", "focos_ano_ini", "focos_ano_fim",
                               "crescimento_abs", "crescimento_pct"],
                ordem=Ordem("crescimento_pct", desc), limite=limite, confianca=0.9,
            )

        # Eventos ambientais críticos (multi-fonte) por município
        if _RE_EVENTOS.search(pergunta):
            return ConsultaAnalitica(
                tabela="vw_eventos_municipio", modo="fato",
                coluna_ordem="total_eventos",
                colunas_saida=["municipio", "total_eventos", "area_km2"],
                ordem=Ordem("total_eventos", desc), limite=limite, confianca=0.9,
            )
        return None

    def _extrair_propriedade(self, pergunta: str) -> ConsultaAnalitica:
        """Mapeia a pergunta para uma IR no modo 'fato' (ranking/filtro de imóveis)."""
        ent = self.entidades.extrair(pergunta)
        filtros: dict = {}
        coluna_ordem: str | None = None

        # direção e limite
        desc = not bool(_RE_MENOS.search(pergunta))
        m = _RE_TOPN.search(pergunta)
        n = int(m.group(1) or m.group(2)) if m else None
        eh_ranking = bool(m or _RE_MAIS.search(pergunta) or _RE_MENOS.search(pergunta))
        limite = n if n else (_LIMITE_RANKING_PADRAO if eh_ranking else 50)

        # coluna de ordenação (ranking) — prioridade por especificidade
        if _RE_AREA_PCT.search(pergunta):
            coluna_ordem = "area_impactada_pct"
        elif _RE_AUMENTO_RISCO.search(pergunta) or _RE_RISCO.search(pergunta):
            coluna_ordem = "nota_risco"
        elif _RE_FOCOS.search(pergunta):
            coluna_ordem = "focos_recentes_12m" if ent.get("periodo") else "focos_total"

        # filtros
        if _RE_ALERTAS.search(pergunta):
            filtros["alertas_deter_recentes_12m"] = (">", 0)
        if _RE_PROX_TI.search(pergunta):
            filtros["proximo_ti"] = True
        if _RE_RECORRENTE.search(pergunta):
            filtros["queimadas_anos_distintos_3a"] = (">=", 2)
        if _RE_APOS_ALERTA.search(pergunta):
            filtros["fogo_apos_alerta"] = (">", 0)
        if _RE_FATORES.search(pergunta):
            mn = _RE_MAIS_DE_N.search(pergunta)
            if mn:
                tok = mn.group(1).lower()
                n_fat = int(tok) if tok.isdigit() else _NUM_EXTENSO.get(tok, 3)
            else:
                n_fat = 0
            filtros["n_fatores_risco"] = (">", n_fat)
        if ent.get("municipios"):
            filtros["municipio"] = ent["municipios"][0]

        # se há filtro mas nenhuma ordenação explícita, ranqueia por risco (tiebreak)
        if coluna_ordem is None and filtros:
            coluna_ordem = "nota_risco"

        colunas_saida = ["cod_imovel", "municipio", "area_ha", "nota_risco", "nivel_risco"]
        for extra in ("focos_recentes_12m", "focos_total", "alertas_deter_recentes_12m",
                      "area_impactada_pct", "n_fatores_risco", "fogo_apos_alerta",
                      "queimadas_anos_distintos_3a", "dist_ti_km"):
            if extra in pergunta or extra == coluna_ordem or extra in filtros:
                if extra not in colunas_saida:
                    colunas_saida.append(extra)

        return ConsultaAnalitica(
            tabela=_FATO, modo="fato",
            coluna_ordem=coluna_ordem, colunas_saida=colunas_saida,
            filtros=filtros,
            ordem=Ordem(por=coluna_ordem, desc=desc) if coluna_ordem else None,
            limite=limite, confianca=0.9,
        )

    @staticmethod
    def _agg_por_regex(pergunta: str) -> str | None:
        if _RE_MEDIA.search(pergunta):
            return "AVG"
        if _RE_SOMA.search(pergunta):
            return "SUM"
        if _RE_CONTA.search(pergunta):
            return "COUNT"
        return None

    def _resolver_metrica(self, tabela: str | None, agg: str | None, pergunta: str = "") -> Metrica | None:
        if not tabela:
            return None
        metricas_tab = METRICAS.get(tabela, {})
        p = pergunta.lower()
        if agg in ("SUM", "AVG"):
            # 1) métrica pré-definida do agg que casa pela menção
            cands = [(nome, col) for nome, (a, col) in metricas_tab.items() if a == agg and col]
            for nome, col in cands:
                if col.split("_")[0] in p:
                    return Metrica(agg, col, "area_km2" if "area" in nome else nome)
            # 2) coluna numérica ligada por sinônimo (ex.: "área média dos imóveis" -> num_area)
            col = ligar_coluna(pergunta, tabela)
            if col and tipo_coluna(tabela, col) == "num":
                alias = "area_km2" if "area" in col else (f"{col}_medio" if agg == "AVG" else col)
                return Metrica(agg, col, alias)
            # 3) primeira métrica pré-definida do agg
            if cands:
                nome, col = cands[0]
                return Metrica(agg, col, "area_km2" if "area" in nome else nome)
        # default: COUNT(*) com alias coerente com a tabela
        alias = next((n for n, (a, _) in metricas_tab.items() if a == "COUNT"), "total")
        return Metrica("COUNT", None, alias)
