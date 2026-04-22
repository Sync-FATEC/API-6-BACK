"""Agregação de respostas parciais em uma ConsultaResponse consolidada + grupos.

Estratégia:
- 1 parcial: retorna ela mesma (back-compat total com caminho original).
- N parciais: separa CAR de busca, mescla resultados de busca dedup por id,
  chama `gerador.gerar()` UMA vez pra visão consolidada, injeta features do
  CAR no geojson top-level e levanta `imovel`/`ameacas_encontradas` do CAR
  pro topo. Cada parcial vira um `GrupoResposta`.
"""

from asg_sistema.motor.planner import ExecutionPlan


_META_KEYS = ("_sub", "_raw_resultados", "_raw_resultados_geo", "_erro")


def agregar(
    pergunta: str,
    plano: ExecutionPlan,
    entidades_base: dict,
    parciais: list[dict],
    gerador,
) -> dict:
    if not parciais:
        return _resposta_vazia(pergunta, plano)

    # Single sub → volta direto, preservando formato original (sem grupos).
    if len(parciais) == 1:
        return _limpar_parcial(parciais[0], pergunta, plano)

    # Multi-sub: separa CAR das subconsultas de busca.
    car_parciais = [p for p in parciais if (p.get("_sub") or {}).get("cod_imovel")]
    busca_parciais = [p for p in parciais if not (p.get("_sub") or {}).get("cod_imovel")]

    resultados, resultados_geo = _unir_resultados(busca_parciais)

    # Intenção para a visão top-level: se houver subconsultas de busca,
    # usa a primeira delas; senão cai na principal do plano.
    if busca_parciais:
        intent_topo = busca_parciais[0]["_sub"]["intencao"]
        conf_topo = busca_parciais[0]["_sub"]["confianca"]
    else:
        intent_topo = plano.intencao_principal
        conf_topo = plano.confianca_principal

    consolidada = gerador.gerar(
        pergunta=pergunta,
        intencao=intent_topo,
        confianca=conf_topo,
        entidades=dict(entidades_base),
        resultados=resultados,
        resultados_geo=resultados_geo,
        intencoes_detectadas=plano.intencoes_detectadas,
    )

    _mesclar_car_no_topo(consolidada, car_parciais)

    grupos = [_parcial_para_grupo(p) for p in parciais if p.get("_sub")]
    consolidada["grupos"] = grupos
    consolidada["eixo_agrupamento"] = plano.eixo_agrupamento
    consolidada["intencoes_detectadas"] = plano.intencoes_detectadas

    resumo_comparativo = _montar_resumo_comparativo(plano, grupos, consolidada)
    if resumo_comparativo:
        consolidada["resumo"] = resumo_comparativo
        exp = consolidada.get("exportacao_relatorio")
        if isinstance(exp, dict) and isinstance(exp.get("resumo"), dict):
            exp["resumo"]["texto"] = resumo_comparativo

    return consolidada


def _limpar_parcial(parcial: dict, pergunta: str, plano: ExecutionPlan) -> dict:
    clean = {k: v for k, v in parcial.items() if k not in _META_KEYS}
    clean["pergunta"] = pergunta
    # Single sub: sem grupos, mas expõe a intenção detectada.
    if plano.intencoes_detectadas:
        clean["intencoes_detectadas"] = plano.intencoes_detectadas
    return clean


def _unir_resultados(parciais: list[dict]) -> tuple[list[dict], list[dict]]:
    vistos_res: set = set()
    vistos_geo: set = set()
    resultados: list[dict] = []
    resultados_geo: list[dict] = []

    for p in parciais:
        for r in p.get("_raw_resultados") or []:
            rid = r.get("id")
            if rid is None or rid not in vistos_res:
                if rid is not None:
                    vistos_res.add(rid)
                resultados.append(r)
        for r in p.get("_raw_resultados_geo") or []:
            rid = r.get("id")
            if rid is None or rid not in vistos_geo:
                if rid is not None:
                    vistos_geo.add(rid)
                resultados_geo.append(r)

    resultados.sort(key=lambda r: float(r.get("similaridade") or 0), reverse=True)
    return resultados, resultados_geo


def _mesclar_car_no_topo(consolidada: dict, car_parciais: list[dict]) -> None:
    if not car_parciais:
        return

    primeiro = car_parciais[0]
    # Exposição top-level: ImovelAmeacasCard do front depende desses campos.
    if primeiro.get("imovel") is not None:
        consolidada["imovel"] = primeiro["imovel"]
    if primeiro.get("ameacas_encontradas") is not None:
        consolidada["ameacas_encontradas"] = primeiro["ameacas_encontradas"]

    # Merge das features do(s) CAR(s) no geojson consolidado.
    for cp in car_parciais:
        cp_geo = cp.get("geojson") or {}
        feats = cp_geo.get("features") or []
        if not feats:
            continue
        if not consolidada.get("geojson"):
            consolidada["geojson"] = {"type": "FeatureCollection", "features": []}
        consolidada["geojson"]["features"].extend(feats)

    if consolidada.get("geojson"):
        consolidada["total_resultados"] = len(consolidada["geojson"]["features"])


def _parcial_para_grupo(parcial: dict) -> dict:
    sub = parcial.get("_sub") or {}
    return {
        "rotulo": sub.get("rotulo", ""),
        "filtros": {
            "municipio": sub.get("municipio"),
            "intencao": sub.get("intencao"),
            "cod_imovel": sub.get("cod_imovel"),
        },
        "resumo": parcial.get("resumo", ""),
        "estatisticas": parcial.get("estatisticas", {}),
        "total_resultados": parcial.get("total_resultados", 0),
        "nota_risco": parcial.get("nota_risco"),
        "fontes": parcial.get("fontes", []),
    }


def _montar_resumo_comparativo(
    plano: ExecutionPlan, grupos: list[dict], consolidada: dict,
) -> str | None:
    if not grupos:
        return None

    eixo = plano.eixo_agrupamento
    total_geral = consolidada.get("total_resultados", 0)

    partes = []
    for g in grupos:
        rotulo = g.get("rotulo") or ""
        total = g.get("total_resultados", 0)
        nr = g.get("nota_risco") or {}
        nota = nr.get("nota", 0)
        nivel = nr.get("nivel", "sem_dados")
        if total > 0:
            partes.append(f"{rotulo}: {total} registros (risco {nivel}, nota {nota})")
        else:
            partes.append(f"{rotulo}: sem registros")

    if not partes:
        return None

    introducao = {
        "municipio": "Comparativo por município",
        "intencao": "Comparativo por tema",
        "composto": "Análise combinada",
    }.get(eixo, "Comparativo")

    return f"{introducao} — " + "; ".join(partes) + f". Total consolidado: {total_geral}."


def _resposta_vazia(pergunta: str, plano: ExecutionPlan) -> dict:
    return {
        "pergunta": pergunta,
        "intencao_detectada": plano.intencao_principal,
        "confianca": round(plano.confianca_principal, 3),
        "entidades": {},
        "resumo": "Nenhum resultado encontrado.",
        "estatisticas": {},
        "dados": [],
        "fontes": [],
        "geojson": None,
        "total_resultados": 0,
    }
