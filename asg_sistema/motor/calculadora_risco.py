"""Calculadora de Nota de Risco Socioambiental ASG via AHP.

Recebe o resultado do cruzamento espacial (queimadas, DETER, PRODES, TIs, UCs,
quilombolas) e calcula uma nota de 0 a 100 usando pesos derivados do método
AHP (Analytic Hierarchy Process).
"""

from asg_sistema.motor.ahp import (
    CRITERIOS_ASG,
    obter_pesos_ahp,
    obter_info_ahp,
)


def _sub_score_queimadas(dados: dict, area_fazenda_km2: float) -> tuple[float, list[str]]:
    """Sub-score 0-1 para queimadas."""
    focos_internos = int(dados.get("focos_internos") or 0)
    focos_total = int(dados.get("focos_total") or 0)
    frp_medio = float(dados.get("frp_medio") or 0)
    focos_6m = int(dados.get("focos_recentes_6m") or 0)
    fatores = []

    if focos_total == 0:
        return 0.0, fatores

    # Densidade: focos dentro da fazenda por km² (cap em 5 focos/km²)
    densidade = focos_internos / area_fazenda_km2 if area_fazenda_km2 > 0 else 0
    fator_densidade = min(densidade / 5, 1.0)

    # Intensidade: FRP médio (cap em 100 MW)
    fator_intensidade = min(frp_medio / 100, 1.0)

    # Recência: proporção de focos nos últimos 6 meses
    fator_recencia = focos_6m / max(focos_total, 1)

    sub = min(1.0, fator_densidade * 0.4 + fator_intensidade * 0.3 + fator_recencia * 0.3)

    if focos_internos > 0:
        fatores.append(f"{focos_internos} foco(s) de queimada dentro do imóvel")
    else:
        dist = float(dados.get("distancia_min_km") or 0)
        fatores.append(f"{focos_total} foco(s) a {dist:.1f} km do imóvel")
    if frp_medio > 20:
        fatores.append(f"FRP médio elevado ({frp_medio:.1f} MW)")
    if focos_6m > 0:
        fatores.append(f"{focos_6m} foco(s) detectado(s) nos últimos 6 meses")

    return sub, fatores


def _sub_score_deter(dados: dict, area_fazenda_km2: float) -> tuple[float, list[str]]:
    """Sub-score 0-1 para alertas DETER."""
    total = int(dados.get("total_alertas") or 0)
    area_inter = float(dados.get("area_intersecao_km2") or 0)
    recentes = int(dados.get("alertas_recentes_12m") or 0)
    fatores = []

    if total == 0:
        return 0.0, fatores

    pct_afetada = area_inter / area_fazenda_km2 if area_fazenda_km2 > 0 else 0
    base = min(1.0, pct_afetada * 2 + total / 20)
    multiplicador_temporal = 0.5 + 0.5 * (recentes / max(total, 1))
    sub = min(1.0, base * multiplicador_temporal)

    if area_inter > 0:
        ha = area_inter * 100
        fatores.append(f"{ha:.2f} ha com alerta DETER dentro do imóvel")
    else:
        dist = float(dados.get("distancia_min_km") or 0)
        fatores.append(f"{total} alerta(s) DETER a {dist:.1f} km")
    if recentes > 0:
        fatores.append(f"{recentes} alerta(s) nos últimos 12 meses")

    return sub, fatores


def _sub_score_prodes(dados: dict, area_fazenda_km2: float) -> tuple[float, list[str]]:
    """Sub-score 0-1 para desmatamento histórico PRODES."""
    total = int(dados.get("total_poligonos") or 0)
    area_hist = float(dados.get("area_hist_km2") or 0)
    recentes = int(dados.get("poligonos_recentes") or 0)
    antigos = int(dados.get("poligonos_antigos") or 0)
    dist = float(dados.get("distancia_min_km") or 0)
    fatores = []

    if total == 0:
        return 0.0, fatores

    pct_hist = area_hist / area_fazenda_km2 if area_fazenda_km2 > 0 else 0
    tendencia = recentes / max(antigos, 1)

    # Fator de proximidade: polígonos encostados (<100m) contam forte,
    # distantes (>5km) não contam. Entre 0-5km decai linearmente.
    fator_proximidade = max(0.0, min(1.0, 1.0 - dist / 5.0))

    # Componente por quantidade + proximidade (até 0.4 via densidade)
    componente_densidade = min(total / 20, 0.4) * fator_proximidade

    sub = min(1.0, pct_hist + min(tendencia / 3, 0.4) + componente_densidade)

    if area_hist > 0:
        ha = area_hist * 100
        fatores.append(f"{ha:.2f} ha de desmatamento histórico dentro do imóvel")
    else:
        fatores.append(f"{total} polígono(s) PRODES a {dist:.2f} km")
    if tendencia > 1.0:
        fatores.append("Tendência de desmatamento crescente (últimos 3 anos vs anteriores)")

    return sub, fatores


def _sub_score_terras_indigenas(dados: dict) -> tuple[float, list[str]]:
    """Sub-score 0-1 para terras indígenas — regra binária com piso."""
    fatores = []
    sobrepoe = bool(dados.get("sobrepoe"))
    sobreposicoes = dados.get("sobreposicoes") or []
    proximas = dados.get("proximas_10km") or []

    if sobrepoe and sobreposicoes:
        pct_sobreposicao_max = 0.0
        nomes = []
        for s in sobreposicoes:
            nomes.append(s.get("nome", ""))
            area_ha = float(s.get("area_sobreposicao_ha") or 0)
            pct_sobreposicao_max = max(pct_sobreposicao_max, area_ha / 100)
        sub = min(1.0, 0.6 + min(pct_sobreposicao_max * 0.4, 0.4))
        fatores.append(f"Sobreposição com terra(s) indígena(s): {', '.join(nomes)}")
        return sub, fatores

    if proximas:
        n = len(proximas) if isinstance(proximas, list) else int(proximas)
        sub = min(0.4, n * 0.15)
        fatores.append(f"{n} terra(s) indígena(s) em raio de 10 km")
        return sub, fatores

    return 0.0, fatores


def _sub_score_contexto(dados_ucs: dict, dados_ql: dict) -> tuple[float, list[str]]:
    """Sub-score 0-1 para contexto municipal (UCs + quilombolas)."""
    fatores = []
    total_ucs = int(dados_ucs.get("total") or 0)
    integral = int(dados_ucs.get("protecao_integral") or 0)
    sustentavel = int(dados_ucs.get("uso_sustentavel") or 0)
    total_ql = int(dados_ql.get("total") or 0)

    if total_ucs == 0 and total_ql == 0:
        return 0.0, fatores

    sub = min(1.0, integral * 0.2 + sustentavel * 0.1 + total_ql * 0.15)

    if integral > 0:
        fatores.append(f"{integral} UC(s) de proteção integral no município")
    if sustentavel > 0:
        fatores.append(f"{sustentavel} UC(s) de uso sustentável no município")
    if total_ql > 0:
        fatores.append(f"{total_ql} comunidade(s) quilombola(s) no município")

    return sub, fatores


def calcular_score_ahp(cruzamento: dict, area_fazenda_km2: float) -> dict:
    """Calcula score ASG via AHP a partir do cruzamento espacial.

    Args:
        cruzamento: dict retornado por repositorio.cruzamento_espacial_imovel()
        area_fazenda_km2: área do imóvel em km²

    Returns:
        Dict com nota (0-100), nível, fatores, sub-scores, pesos AHP e metadados.
    """
    pesos = obter_pesos_ahp()
    sub_scores_raw = {}
    fatores_todos = []

    # Calcula cada sub-score
    sub_q, fat_q = _sub_score_queimadas(
        cruzamento.get("queimadas", {}), area_fazenda_km2
    )
    sub_scores_raw["queimadas"] = sub_q
    fatores_todos.extend(fat_q)

    sub_d, fat_d = _sub_score_deter(cruzamento.get("deter", {}), area_fazenda_km2)
    sub_scores_raw["desmatamento_deter"] = sub_d
    fatores_todos.extend(fat_d)

    sub_t, fat_t = _sub_score_terras_indigenas(cruzamento.get("terras_indigenas", {}))
    sub_scores_raw["terras_indigenas"] = sub_t
    fatores_todos.extend(fat_t)

    sub_p, fat_p = _sub_score_prodes(cruzamento.get("prodes", {}), area_fazenda_km2)
    sub_scores_raw["desmatamento_prodes"] = sub_p
    fatores_todos.extend(fat_p)

    sub_c, fat_c = _sub_score_contexto(
        cruzamento.get("unidades_conservacao", {}),
        cruzamento.get("quilombolas", {}),
    )
    sub_scores_raw["contexto_municipal"] = sub_c
    fatores_todos.extend(fat_c)

    # Score final: soma ponderada (cada sub × peso_AHP) × 100
    score = sum(sub_scores_raw[c] * pesos[c] for c in CRITERIOS_ASG) * 100
    nota = round(score)

    # Classificação
    if nota == 0:
        nivel = "sem_dados"
    elif nota <= 20:
        nivel = "baixo"
    elif nota <= 40:
        nivel = "moderado"
    elif nota <= 60:
        nivel = "elevado"
    elif nota <= 80:
        nivel = "alto"
    else:
        nivel = "critico"

    # Contribuição de cada eixo (pontos no score final de 100)
    por_dimensao = {
        c: round(sub_scores_raw[c] * pesos[c] * 100, 1) for c in CRITERIOS_ASG
    }

    # Sub-scores brutos (0-100) por eixo, antes da ponderação
    sub_scores_pct = {c: round(sub_scores_raw[c] * 100, 1) for c in CRITERIOS_ASG}

    return {
        "nota": nota,
        "nivel": nivel,
        "fatores": fatores_todos,
        "por_dimensao": por_dimensao,
        "sub_scores": sub_scores_pct,
        "metodo_ahp": obter_info_ahp(),
    }
