"""IR + linhas -> dict no contrato ConsultaResponse. Resumo determinístico (sem LLM).

NUNCA inventa números: o resumo é formatado a partir das próprias linhas.
"""

import json

from asg_sistema.analitico.ir import ConsultaAnalitica


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return str(v)


def _resumo(pergunta: str, ir: ConsultaAnalitica, linhas: list[dict]) -> str:
    if not linhas:
        return "Nenhum resultado encontrado para a sua pergunta."

    # Modo propriedade: lista os imóveis no topo do ranking.
    if ir.modo == "fato":
        col = ir.coluna_ordem
        topo = linhas[: min(3, len(linhas))]
        def rotulo(l):
            return (l.get("nome") or l.get("comunidade") or l.get("cod_imovel")
                    or l.get("municipio") or "registro")
        if col and col in linhas[0]:
            partes = [f"{rotulo(l)} ({_fmt(l[col])})" for l in topo]
            return (f"{len(linhas)} resultado(s). Destaques: " + "; ".join(partes) + ".")
        partes = [f"{rotulo(l)}" for l in topo]
        return f"{len(linhas)} resultado(s). Ex.: " + "; ".join(partes) + "."

    alias = ir.metrica.alias if ir.metrica else None
    dim = ir.dimensoes[0] if ir.dimensoes else None
    if dim and alias and dim in linhas[0] and alias in linhas[0]:
        topo = linhas[: min(3, len(linhas))]
        partes = [f"{l[dim]} ({_fmt(l[alias])})" for l in topo]
        verbo = "maiores" if (ir.ordem and ir.ordem.desc) else "menores"
        return f"Os {verbo} resultados por {dim}: " + "; ".join(partes) + "."
    return f"Foram encontrados {len(linhas)} resultado(s)."


def _geojson(linhas: list[dict]) -> dict | None:
    chave = None
    if linhas:
        for k in linhas[0]:
            kl = k.lower()
            if kl in ("geometry", "geom_geojson", "geojson", "geom") or "geojson" in kl:
                chave = k
                break
    if not chave:
        return None
    feats = []
    for l in linhas:
        raw = l.get(chave)
        if not raw:
            continue
        geom = json.loads(raw) if isinstance(raw, str) else raw
        props = {k: v for k, v in l.items() if k != chave}
        feats.append({"type": "Feature", "geometry": geom, "properties": props})
    return {"type": "FeatureCollection", "features": feats} if feats else None


def renderizar(pergunta: str, ir: ConsultaAnalitica, linhas: list[dict], sql: str) -> dict:
    """Dict pronto para popular ConsultaResponse (chaves lidas por _salvar_historico)."""
    resumo = _resumo(pergunta, ir, linhas)
    if ir.aviso:
        resumo = f"{ir.aviso} {resumo}"
    # contexto compacto p/ follow-up na próxima pergunta da conversa
    ir_contexto = {
        "tabela": ir.tabela, "modo": ir.modo,
        "filtros": {k: v for k, v in (ir.filtros or {}).items() if k != "periodo"},
        "dimensoes": list(ir.dimensoes),
        "colunas_saida": list(ir.colunas_saida),
        "coluna_ordem": ir.coluna_ordem,
        "ordem_desc": (ir.ordens_efetivas()[0].desc if ir.ordens_efetivas() else True),
        "limite": ir.limite,
        "metrica_agg": (ir.metrica.agg if ir.metrica else None),
        "metrica_coluna": (ir.metrica.coluna if ir.metrica else None),
        "metrica_alias": (ir.metrica.alias if ir.metrica else None),
    }
    return {
        "pergunta": pergunta,
        "intencao_detectada": "consulta_analitica",
        "confianca": round(float(ir.confianca), 3),
        "entidades": dict(ir.filtros or {}),
        "resumo": resumo,
        "estatisticas": {
            "total": len(linhas),
            "colunas": list(linhas[0].keys()) if linhas else [],
            "sql": sql,
            "tabela": ir.tabela,
            "metrica": (ir.metrica.alias if ir.metrica else None),
            "dimensoes": ir.dimensoes,
            "ir_contexto": ir_contexto,
        },
        "dados": linhas,
        "fontes": [{"nome": "Consulta analítica (Text-to-SQL local)", "tabela": ir.tabela}],
        "geojson": _geojson(linhas),
        "nota_risco": None,
        "grupos": None,
        "total_resultados": len(linhas),
    }
