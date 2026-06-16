"""Validação de SQL via AST (sqlglot): único SELECT + allowlist + funções seguras + LIMIT.

Cinturão de segurança aplicado a TODO SQL antes de executar (construtor e fallback).
"""

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from asg_sistema.analitico.catalogo import nomes_permitidos, colunas_de, todas_as_colunas


@dataclass
class ResultadoValidacao:
    valido: bool
    sql_final: str
    erro: str | None = None


_PROIBIDO = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create,
    exp.Alter, exp.TruncateTable, exp.Grant, exp.Command,
)

# Funções nomeadas permitidas (agregações + data + texto + geo).
_FUNC_OK = {
    "count", "sum", "avg", "min", "max", "round", "coalesce", "extract",
    "date_trunc", "make_date", "lower", "upper", "st_asgeojson", "abs", "cast",
}


def validar_sql(sql: str, max_limit: int = 100) -> ResultadoValidacao:
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        return ResultadoValidacao(False, "", "SQL vazio.")

    try:
        arvores = [a for a in sqlglot.parse(sql, dialect="postgres") if a is not None]
    except Exception as e:
        return ResultadoValidacao(False, "", f"SQL não parseável: {e}")
    if len(arvores) != 1:
        return ResultadoValidacao(False, "", "Apenas um comando é permitido.")
    arvore = arvores[0]

    # só SELECT / WITH ... SELECT; nada de DDL/DML
    for node in arvore.walk():
        if isinstance(node, _PROIBIDO):
            return ResultadoValidacao(False, "", f"Comando proibido: {type(node).__name__}.")
    if arvore.find(exp.Select) is None:
        return ResultadoValidacao(False, "", "Apenas SELECT é permitido.")

    # allowlist de tabelas (ignora nomes de CTE)
    permitidas = nomes_permitidos()
    nomes_cte = {c.alias_or_name for c in arvore.find_all(exp.CTE)}
    alias_tab: dict[str, str] = {}
    for tab in arvore.find_all(exp.Table):
        nome = tab.name
        if nome in nomes_cte:
            continue
        if nome not in permitidas:
            return ResultadoValidacao(False, "", f"Tabela não permitida: {nome}.")
        alias_tab[tab.alias_or_name] = nome

    # funções: qualquer função "anônima" (não nativa do sqlglot) precisa estar na allowlist
    for fn in arvore.find_all(exp.Anonymous):
        if (fn.name or "").lower() not in _FUNC_OK:
            return ResultadoValidacao(False, "", f"Função não permitida: {fn.name}.")

    # allowlist de colunas qualificadas (alias.coluna)
    universo = todas_as_colunas()
    for col in arvore.find_all(exp.Column):
        nome = col.name
        if nome == "*":
            continue
        ali = col.table
        if ali and ali in alias_tab:
            if (nome not in colunas_de(alias_tab[ali])
                    and nome not in universo and nome not in nomes_cte):
                return ResultadoValidacao(False, "", f"Coluna não permitida: {ali}.{nome}.")
        # não-qualificada: tolerada (alias de SELECT, coluna de CTE, etc.)

    # LIMIT obrigatório / clampado no SELECT externo
    select_ext = arvore if isinstance(arvore, exp.Select) else arvore.find(exp.Select)
    lim = None
    if select_ext is not None and select_ext.args.get("limit") is not None:
        try:
            lim = int(select_ext.args["limit"].expression.name)
        except Exception:
            lim = None

    if lim is None:
        sql_final = arvore.limit(max_limit).sql(dialect="postgres")
    elif lim > max_limit:
        select_ext.set("limit", exp.Limit(expression=exp.Literal.number(max_limit)))
        sql_final = arvore.sql(dialect="postgres")
    else:
        sql_final = arvore.sql(dialect="postgres")

    # sqlglot renderiza placeholders nomeados como %(nome)s (pyformat); o SQLAlchemy
    # text() usa :nome. Converte de volta para preservar os bind params na execução.
    sql_final = re.sub(r"%\((\w+)\)s", r":\1", sql_final)

    return ResultadoValidacao(True, sql_final, None)
