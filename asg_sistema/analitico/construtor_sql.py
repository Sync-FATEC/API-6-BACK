"""IR ConsultaAnalitica -> (sql, params). Determinístico e parametrizado.

Filtros sempre via bind params — valores do usuário nunca entram por interpolação.
Suporta: filtros genéricos por coluna (=, >, >=, <, <=, <>, BETWEEN, IN, ILIKE, NOT),
GROUP BY multi-dimensão, multi-métrica, HAVING, distribuição (%) e ORDER BY múltiplo.
"""

from asg_sistema.analitico.catalogo import DIMENSOES, colunas_de
from asg_sistema.analitico.ir import ConsultaAnalitica

# Coluna de data por tabela (para filtros de período).
_COLUNA_DATA = {
    "queimadas": "data_hora",
    "desmatamento_alertas": "data_avistamento",
    "prodes_desmatamento": "data_imagem",
    "sicar_imoveis": "dat_criacao",
}

_OPERADORES_OK = {">", ">=", "<", "<=", "=", "<>"}


def _expr_metrica(m) -> str:
    if m.agg == "COUNT" or not m.coluna:
        return f"COUNT(*) AS {m.alias}"
    return f"{m.agg}({m.coluna}) AS {m.alias}"


def _clausula_valor(chave: str, valor, params: dict, idx: int) -> str | None:
    """Gera UMA cláusula WHERE parametrizada para (chave, valor). Retorna None se inválida."""
    p = f"f{idx}"

    # NOT recursivo
    if isinstance(valor, tuple) and len(valor) == 2 and valor[0] == "NOT":
        interna = _clausula_valor(chave, valor[1], params, idx)
        return f"NOT ({interna})" if interna else None

    if isinstance(valor, bool):
        params[p] = valor
        return f"{chave} = :{p}"

    if isinstance(valor, tuple) and len(valor) == 2:
        op, v = valor
        if op in _OPERADORES_OK:
            params[p] = v
            return f"{chave} {op} :{p}"
        if op == "BETWEEN" and isinstance(v, (list, tuple)) and len(v) == 2:
            params[f"{p}a"], params[f"{p}b"] = v[0], v[1]
            return f"{chave} BETWEEN :{p}a AND :{p}b"
        if op == "IN" and isinstance(v, (list, tuple)) and v:
            nomes = []
            for j, item in enumerate(v):
                params[f"{p}_{j}"] = item
                nomes.append(f":{p}_{j}")
            return f"{chave} IN ({', '.join(nomes)})"
        if op == "ILIKE":
            params[p] = v
            return f"{chave} ILIKE :{p}"
        return None

    # lista simples -> IN
    if isinstance(valor, (list, tuple)) and valor:
        nomes = []
        for j, item in enumerate(valor):
            params[f"{p}_{j}"] = item
            nomes.append(f":{p}_{j}")
        return f"{chave} IN ({', '.join(nomes)})"

    # escalar -> igualdade
    params[p] = valor
    return f"{chave} = :{p}"


def _montar_where(filtros: dict, cols_validas: set, tabela: str, params: dict) -> list[str]:
    """Cláusulas WHERE para filtros genéricos + especiais (municipio, periodo, proximo_ti)."""
    where: list[str] = []
    for i, (chave, valor) in enumerate((filtros or {}).items()):
        if chave == "proximo_ti" and valor:
            where.append("(sobrepoe_ti = TRUE OR dist_ti_km <= 10)")
            continue
        if chave == "municipio":
            vals = valor if isinstance(valor, (list, tuple)) else [valor]
            ors = []
            for j, mun in enumerate(vals):
                params[f"mun{j}"] = f"%{mun}%"
                ors.append(f"municipio ILIKE :mun{j}")
            if ors:
                where.append("(" + " OR ".join(ors) + ")")
            continue
        if chave == "_anos" and isinstance(valor, (list, tuple)) and valor:
            col_ano = "ano" if tabela == "prodes_desmatamento" else None
            nomes = []
            for j, a in enumerate(valor):
                params[f"ano{j}"] = int(a)
                nomes.append(f":ano{j}")
            if col_ano:
                where.append(f"{col_ano} IN ({', '.join(nomes)})")
            else:
                dcol = _COLUNA_DATA.get(tabela)
                if dcol:
                    where.append(f"EXTRACT(YEAR FROM {dcol}) IN ({', '.join(nomes)})")
            continue
        if chave == "periodo" and isinstance(valor, dict):
            col = _COLUNA_DATA.get(tabela)
            if col:
                if valor.get("inicio"):
                    params["data_inicio"] = valor["inicio"]
                    where.append(f"{col} >= :data_inicio")
                if valor.get("fim"):
                    params["data_fim"] = valor["fim"]
                    where.append(f"{col} < :data_fim")
            continue
        if chave == "status":  # enum SICAR
            if "ind_status" in cols_validas:
                params["f_status"] = valor
                where.append("ind_status = :f_status")
            continue
        if chave not in cols_validas:
            continue
        clausula = _clausula_valor(chave, valor, params, i)
        if clausula:
            where.append(clausula)
    return where


def _ordem_sql(ir: ConsultaAnalitica, fallback_col: str | None) -> str:
    ordens = ir.ordens_efetivas()
    if not ordens and fallback_col:
        from asg_sistema.analitico.ir import Ordem
        ordens = [Ordem(por=fallback_col, desc=True)]
    if not ordens:
        return ""
    partes = [f"{o.por} {'DESC' if o.desc else 'ASC'} NULLS LAST" for o in ordens]
    return "\nORDER BY " + ", ".join(partes)


def _construir_fato(ir: ConsultaAnalitica, max_limit: int) -> tuple[str, dict]:
    """Modo 'fato': SELECT colunas concretas + WHERE + ORDER BY (feature store ou tabela base)."""
    params: dict = {}
    cols_validas = colunas_de(ir.tabela)

    saida = list(ir.colunas_saida) or ["cod_imovel", "municipio", "nota_risco", "nivel_risco"]
    if ir.coluna_ordem and ir.coluna_ordem not in saida:
        saida.append(ir.coluna_ordem)
    saida = [c for c in saida if c in cols_validas]
    if not saida:
        saida = [c for c in ("cod_imovel", "municipio", "nome", "id") if c in cols_validas][:1] or ["*"]
    select_cols = list(saida)
    if "geom" in cols_validas:
        select_cols.append("ST_AsGeoJSON(geom) AS geometry")

    sql = f"SELECT {', '.join(select_cols)}\nFROM {ir.tabela}"
    where = _montar_where(ir.filtros, cols_validas, ir.tabela, params)
    if where:
        sql += "\nWHERE " + " AND ".join(where)

    ordem = _ordem_sql(ir, ir.coluna_ordem if (ir.coluna_ordem in cols_validas) else None)
    sql += ordem

    limite = min(int(ir.limite or max_limit), max_limit)
    sql += f"\nLIMIT {limite}"
    return sql, params


def construir(ir: ConsultaAnalitica, max_limit: int = 100) -> tuple[str, dict]:
    if not ir.completa():
        raise ValueError("IR incompleta: faltam dados mínimos.")

    if ir.modo == "fato":
        return _construir_fato(ir, max_limit)

    params: dict = {}
    cols_validas = colunas_de(ir.tabela)
    dims_sql = [DIMENSOES.get(ir.tabela, {}).get(d, d) for d in ir.dimensoes]

    metricas = ir.metricas_efetivas()
    select_cols = list(dims_sql) + [_expr_metrica(m) for m in metricas]
    # distribuição/percentual sobre a contagem
    if ir.distribuicao:
        select_cols.append("ROUND(100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0), 1) AS percentual")

    sql = f"SELECT {', '.join(select_cols)}\nFROM {ir.tabela}"

    where = _montar_where(ir.filtros, cols_validas, ir.tabela, params)
    if where:
        sql += "\nWHERE " + " AND ".join(where)

    if dims_sql:
        sql += "\nGROUP BY " + ", ".join(dims_sql)

    # HAVING sobre a métrica primária (repete a expressão; PG não aceita alias em HAVING)
    if ir.having and metricas:
        m0 = metricas[0]
        expr = "COUNT(*)" if (m0.agg == "COUNT" or not m0.coluna) else f"{m0.agg}({m0.coluna})"
        partes = []
        for k, (op, val) in enumerate(ir.having):
            if op in _OPERADORES_OK:
                params[f"h{k}"] = val
                partes.append(f"{expr} {op} :h{k}")
        if partes:
            sql += "\nHAVING " + " AND ".join(partes)

    # ORDER BY: usa ordens explícitas; senão ordena pela métrica primária desc
    fallback = metricas[0].alias if metricas else None
    sql += _ordem_sql(ir, fallback)

    limite = min(int(ir.limite or max_limit), max_limit)
    sql += f"\nLIMIT {limite}"
    return sql, params
