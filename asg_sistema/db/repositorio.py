import json
from datetime import datetime

from asg_sistema.db.conexao import executar_consulta, executar_sql


def buscar_municipio_por_cod_imovel(cod_imovel: str) -> str | None:
    """Município do imóvel SICAR (para restringir outras fontes quando o usuário informa o CAR)."""
    cod = (cod_imovel or "").strip()
    if not cod:
        return None
    rows = executar_consulta(
        """SELECT municipio FROM sicar_imoveis
           WHERE LOWER(TRIM(cod_imovel)) = LOWER(TRIM(:cod)) LIMIT 1""",
        {"cod": cod},
    )
    if not rows:
        return None
    m = rows[0].get("municipio")
    return str(m).strip() if m else None


def buscar_imovel_rural_por_cod(cod_imovel: str) -> dict | None:
    """Retorna um imóvel rural (SICAR) pelo cod_imovel, com geometria em GeoJSON."""
    cod = (cod_imovel or "").strip()
    if not cod:
        return None
    rows = executar_consulta(
        """SELECT id, fonte_id, cod_imovel, cod_tema, nom_tema, ind_status, ind_tipo,
                  des_condic, municipio, cod_estado, num_area, mod_fiscal,
                  dat_criacao, dat_atualizacao,
                  ST_AsGeoJSON(geom) AS geometry_json
           FROM sicar_imoveis
           WHERE LOWER(TRIM(cod_imovel)) = LOWER(TRIM(:cod))
           LIMIT 1""",
        {"cod": cod},
    )
    if not rows:
        return None
    row = dict(rows[0])
    gj = row.pop("geometry_json", None)
    if gj and isinstance(gj, str):
        try:
            row["geometry"] = json.loads(gj)
        except json.JSONDecodeError:
            row["geometry"] = None
    else:
        row["geometry"] = None
    return row


def busca_vetorial(
    embedding_str: str,
    fonte: str | None = None,
    fontes: list[str] | None = None,
    uf_sigla: str = "SP",
    municipio: str | None = None,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    limite: int = 15,
    cod_imovel: str | None = None,
) -> list[dict]:
    filtros = ["UPPER(TRIM(uf_sigla)) = :uf_sigla"]
    params = {"emb": embedding_str, "limite": limite, "uf_sigla": uf_sigla.upper().strip()}

    if fontes:
        placeholders = ",".join(f":f{i}" for i in range(len(fontes)))
        filtros.append(f"fonte IN ({placeholders})")
        for i, f in enumerate(fontes):
            params[f"f{i}"] = f
    elif fonte:
        filtros.append("fonte = :fonte")
        params["fonte"] = fonte
    if municipio:
        if fonte == "icmbio" or (fontes and "icmbio" in fontes):
            filtros.append("(municipio ILIKE :municipio OR texto ILIKE :municipio)")
        else:
            filtros.append("municipio ILIKE :municipio")
        params["municipio"] = f"%{municipio}%"
    if data_inicio:
        filtros.append("data_referencia >= :data_inicio")
        params["data_inicio"] = data_inicio
    if data_fim:
        filtros.append("data_referencia <= :data_fim")
        params["data_fim"] = data_fim
    if cod_imovel and fonte == "sicar":
        filtros.append("LOWER(TRIM(metadados_json->>'cod_imovel')) = LOWER(TRIM(:cod_imovel))")
        params["cod_imovel"] = cod_imovel.strip()

    where = ""
    if filtros:
        where = "WHERE " + " AND ".join(filtros)

    sql = f"""
        SELECT id, fonte, tipo_registro, municipio, data_referencia,
               texto, metadados_json,
               1 - (embedding <=> :emb) AS similaridade
        FROM corpus_asg
        {where}
        ORDER BY embedding <=> :emb
        LIMIT :limite
    """
    return executar_consulta(sql, params)


def buscar_uids_prodes_por_municipio(municipio: str, raio_graus: float = 0.3) -> list[str]:
    """Retorna UIDs de registros PRODES cujos polígonos estão dentro do raio do centroide do município."""
    import re
    nome = re.sub(r"\s*\([A-Z]{2}\)\s*$", "", municipio.split(",")[0].strip())
    # pega centroide aproximado do município via tabela de queimadas
    rows = executar_consulta(
                """SELECT AVG(longitude) as lon, AVG(latitude) as lat
                     FROM queimadas
                     WHERE municipio ILIKE :mun
                         AND UPPER(TRIM(estado)) IN ('SP', 'SAO PAULO', 'SÃO PAULO')""",
        {"mun": f"%{nome}%"},
    )
    if not rows or not rows[0].get("lon"):
        return []
    lon = rows[0]["lon"]
    lat = rows[0]["lat"]
    uid_rows = executar_consulta(
        """SELECT uid FROM prodes_desmatamento
           WHERE geom IS NOT NULL
                         AND UPPER(TRIM(estado)) IN ('SP', 'SAO PAULO', 'SÃO PAULO')
             AND ST_DWithin(geom::geography,
                            ST_SetSRID(ST_MakePoint(:lon, :lat), 4674)::geography,
                            :raio_m)""",
        {"lon": lon, "lat": lat, "raio_m": raio_graus * 111000},
    )
    return [str(r["uid"]) for r in uid_rows if r.get("uid") is not None]


def busca_vetorial_prodes_uids(
    embedding_str: str,
    uids: list[str],
    uf_sigla: str = "SP",
    limite: int = 15,
) -> list[dict]:
    """Busca semântica no corpus PRODES filtrada por UIDs específicos."""
    if not uids:
        return []
    placeholders = ",".join(f":u{i}" for i in range(len(uids)))
    params = {"emb": embedding_str, "limite": limite, "uf_sigla": uf_sigla.upper().strip()}
    for i, u in enumerate(uids):
        params[f"u{i}"] = u
    sql = f"""
        SELECT id, fonte, tipo_registro, municipio, data_referencia,
               texto, metadados_json,
               1 - (embedding <=> :emb) AS similaridade
        FROM corpus_asg
        WHERE fonte = 'prodes'
                    AND UPPER(TRIM(uf_sigla)) = :uf_sigla
          AND (metadados_json->>'uid') IN ({placeholders})
        ORDER BY embedding <=> :emb
        LIMIT :limite
    """
    return executar_consulta(sql, params)


def buscar_imovel_por_car(cod_imovel: str) -> dict | None:
    """Busca imóvel SICAR pelo código CAR. Retorna dados + geometria GeoJSON."""
    rows = executar_consulta(
        """SELECT cod_imovel, nom_tema, ind_status, ind_tipo, des_condic,
                  municipio, cod_estado, num_area, mod_fiscal,
                  dat_criacao, dat_atualizacao,
                  ST_AsGeoJSON(geom) as geometry,
                  ST_Area(geom::geography) / 10000 as area_ha_calc
           FROM sicar_imoveis
           WHERE cod_imovel = :cod AND geom IS NOT NULL
           LIMIT 1""",
        {"cod": cod_imovel},
    )
    if not rows:
        return None
    row = rows[0]
    import json
    row["geometry"] = json.loads(row["geometry"]) if row.get("geometry") else None
    return row


def cruzamento_espacial_imovel(geom_geojson: str, municipio: str) -> dict:
    """Cruza a geometria de um imóvel com todas as fontes ambientais.

    Otimizações:
    - Usa ST_Expand (bbox) como pré-filtro antes de ST_DWithin (evita geography cast em linhas irrelevantes)
    - Combina query de stats + geo em uma única consulta por fonte
    - Evita ST_Intersection/ST_Area pesados — usa ST_Area dos polígonos originais quando intersectam
    """
    import json as _json

    params_base = {"geom": geom_geojson}

    # Pré-calcula bbox expandida em graus (~5km ≈ 0.045°, ~10km ≈ 0.09°)
    _BUFFER_5KM_DEG = 0.045
    _BUFFER_10KM_DEG = 0.09

    # --- Queimadas (stats + geo em uma query) ---
    queimadas_all = executar_consulta(
        f"""WITH fazenda AS (
                SELECT ST_SetSRID(ST_GeomFromGeoJSON(:geom), 4674) AS geom
            )
            SELECT q.id, q.municipio, q.satelite, q.data_hora, q.frp, q.bioma,
                   ST_AsGeoJSON(q.geom) as geometry,
                   ST_Contains(f.geom, q.geom) as dentro,
                   ST_Distance(f.geom::geography, q.geom::geography) / 1000 as distancia_km
            FROM queimadas q, fazenda f
            WHERE q.geom IS NOT NULL
              AND q.geom && ST_Expand(f.geom, {_BUFFER_5KM_DEG})
              AND ST_DWithin(f.geom::geography, q.geom::geography, 5000)
            ORDER BY ST_Distance(f.geom::geography, q.geom::geography)
            LIMIT 50""",
        {**params_base},
    )

    focos_internos = sum(1 for r in queimadas_all if r.get("dentro"))
    focos_total = len(queimadas_all)
    frps = [float(r["frp"]) for r in queimadas_all if r.get("frp")]
    focos_recentes = sum(1 for r in queimadas_all if r.get("data_hora") and str(r["data_hora"]) >= _data_6m_atras())
    dist_min_q = float(queimadas_all[0]["distancia_km"]) if queimadas_all else 0

    # --- DETER (stats + geo, área de interseção real nos que cruzam) ---
    deter_all = executar_consulta(
        f"""WITH fazenda AS (
                SELECT ST_SetSRID(ST_GeomFromGeoJSON(:geom), 4674) AS geom
            )
            SELECT d.id, d.classe, d.municipio, d.data_avistamento, d.area_total_km2,
                   ST_AsGeoJSON(d.geom) as geometry,
                   ST_Intersects(f.geom, d.geom) as intersecta,
                   CASE WHEN ST_Intersects(f.geom, d.geom)
                        THEN ST_Area(ST_Intersection(f.geom, d.geom)::geography) / 1000000
                        ELSE 0 END as area_intersecao_km2,
                   ST_Distance(f.geom::geography, d.geom::geography) / 1000 as distancia_km
            FROM desmatamento_alertas d, fazenda f
            WHERE d.geom IS NOT NULL
              AND d.geom && ST_Expand(f.geom, {_BUFFER_5KM_DEG})
              AND ST_DWithin(f.geom::geography, d.geom::geography, 5000)
            ORDER BY ST_Distance(f.geom::geography, d.geom::geography)
            LIMIT 20""",
        {**params_base},
    )

    deter_intersecta = [r for r in deter_all if r.get("intersecta")]
    area_deter_km2 = sum(float(r.get("area_intersecao_km2") or 0) for r in deter_intersecta)
    alertas_12m = sum(1 for r in deter_all if r.get("data_avistamento") and str(r["data_avistamento"]) >= _data_12m_atras())
    dist_min_d = float(deter_all[0]["distancia_km"]) if deter_all else 0

    # --- PRODES (stats + geo, calcula área de interseção só nos que cruzam) ---
    prodes_all = executar_consulta(
        f"""WITH fazenda AS (
                SELECT ST_SetSRID(ST_GeomFromGeoJSON(:geom), 4674) AS geom
            )
            SELECT p.uid, p.ano, p.area_km, p.classe_nome,
                   ST_AsGeoJSON(p.geom) as geometry,
                   ST_Intersects(f.geom, p.geom) as intersecta,
                   CASE WHEN ST_Intersects(f.geom, p.geom)
                        THEN ST_Area(ST_Intersection(f.geom, p.geom)::geography) / 1000000
                        ELSE 0 END as area_intersecao_km2,
                   ST_Distance(f.geom::geography, p.geom::geography) / 1000 as distancia_km
            FROM prodes_desmatamento p, fazenda f
            WHERE p.geom IS NOT NULL
              AND p.geom && ST_Expand(f.geom, {_BUFFER_5KM_DEG})
              AND ST_DWithin(f.geom::geography, p.geom::geography, 5000)
            ORDER BY ST_Distance(f.geom::geography, p.geom::geography)
            LIMIT 20""",
        {**params_base},
    )

    prodes_intersecta = [r for r in prodes_all if r.get("intersecta")]
    area_prodes_km2 = sum(float(r.get("area_intersecao_km2") or 0) for r in prodes_intersecta)
    ano_atual = _ano_atual()
    prodes_recentes = sum(1 for r in prodes_all if (r.get("ano") or 0) >= ano_atual - 3)
    prodes_antigos = sum(1 for r in prodes_all if (r.get("ano") or 0) < ano_atual - 3)
    dist_min_p = float(prodes_all[0]["distancia_km"]) if prodes_all else 0

    # --- Terras Indígenas (uma query com flag de sobreposição) ---
    ti_all = executar_consulta(
        f"""WITH fazenda AS (
                SELECT ST_SetSRID(ST_GeomFromGeoJSON(:geom), 4674) AS geom
            )
            SELECT t.nome, t.etnia, t.fase,
                   ST_Intersects(f.geom, t.geom) as sobrepoe,
                   ST_Distance(f.geom::geography, t.geom::geography) / 1000 as distancia_km,
                   CASE WHEN ST_Intersects(f.geom, t.geom)
                        THEN ST_Area(ST_Intersection(f.geom, t.geom)::geography) / 10000
                        ELSE 0 END as area_sobreposicao_ha,
                   ST_AsGeoJSON(t.geom) as geometry
            FROM terras_indigenas t, fazenda f
            WHERE t.geom IS NOT NULL
              AND t.geom && ST_Expand(f.geom, {_BUFFER_10KM_DEG})
              AND ST_DWithin(f.geom::geography, t.geom::geography, 10000)
            ORDER BY ST_Distance(f.geom::geography, t.geom::geography)""",
        {**params_base},
    )

    ti_sobreposicao = [r for r in ti_all if r.get("sobrepoe")]
    ti_proximas = [r for r in ti_all if not r.get("sobrepoe")]

    # --- UCs + Quilombolas (textuais, rápidos) ---
    ucs = []
    quilombolas = []
    if municipio:
        ucs = executar_consulta(
            """SELECT nome, categoria, grupo, esfera, area_ha
               FROM unidades_conservacao
               WHERE municipio ILIKE :mun
               ORDER BY nome""",
            {"mun": f"%{municipio}%"},
        )
        # Sem coluna geom no banco, usamos apenas a contagem municipal.
        # Para evitar a nota 14 automática, a calculadora agora dará nota mínima (1 ponto).
        quilombolas_municipio = executar_consulta(
            """SELECT comunidade, municipio, ano_certificacao
               FROM comunidades_quilombolas
               WHERE municipio ILIKE :mun
               ORDER BY comunidade""",
            {"mun": f"%{municipio}%"},
        )
        
        quilombolas_data = {
            "total": len(quilombolas_municipio), # Compatibilidade
            "lista": quilombolas_municipio,       # Compatibilidade
            "total_municipio": len(quilombolas_municipio),
            "sobrepoe": False, # Requer coluna geom para ser True
            "sobreposicoes": [],
            "proximas_10km": [],
            "lista_municipio": quilombolas_municipio
        }
    else:
        quilombolas_data = {
            "total": 0,
            "lista": [],
            "total_municipio": 0,
            "sobrepoe": False,
            "sobreposicoes": [],
            "proximas_10km": [],
            "lista_municipio": []
        }

    # Parsear geometrias GeoJSON
    for lista in [queimadas_all, deter_all, prodes_all, ti_sobreposicao, ti_proximas]:
        for item in lista:
            if item.get("geometry") and isinstance(item["geometry"], str):
                item["geometry"] = _json.loads(item["geometry"])

    return {
        "queimadas": {
            "focos_internos": focos_internos,
            "focos_total": focos_total,
            "frp_medio": round(sum(frps) / len(frps), 2) if frps else 0,
            "focos_recentes_6m": focos_recentes,
            "distancia_min_km": round(dist_min_q, 2),
            "geo": queimadas_all,
        },
        "deter": {
            "total_alertas": len(deter_all),
            "area_intersecao_km2": round(area_deter_km2, 4),
            "alertas_recentes_12m": alertas_12m,
            "distancia_min_km": round(dist_min_d, 2),
            "geo": deter_all,
        },
        "prodes": {
            "total_poligonos": len(prodes_all),
            "area_hist_km2": round(area_prodes_km2, 4),
            "poligonos_recentes": prodes_recentes,
            "poligonos_antigos": prodes_antigos,
            "distancia_min_km": round(dist_min_p, 2),
            "geo": prodes_all,
        },
        "terras_indigenas": {
            "sobrepoe": len(ti_sobreposicao) > 0,
            "sobreposicoes": [
                {"nome": r["nome"], "etnia": r["etnia"], "fase": r["fase"],
                 "area_sobreposicao_ha": round(float(r.get("area_sobreposicao_ha") or 0), 2),
                 "geometry": r.get("geometry")}
                for r in ti_sobreposicao
            ],
            "proximas_10km": [
                {"nome": r["nome"], "etnia": r["etnia"],
                 "distancia_km": round(float(r.get("distancia_km") or 0), 2),
                 "geometry": r.get("geometry")}
                for r in ti_proximas
            ],
        },
        "unidades_conservacao": {
            "total": len(ucs),
            "protecao_integral": sum(
                1 for u in ucs if u.get("grupo") and "integral" in u["grupo"].lower()
            ),
            "uso_sustentavel": sum(
                1 for u in ucs if u.get("grupo") and "sustent" in u["grupo"].lower()
            ),
            "lista": ucs,
        },
        "quilombolas": quilombolas_data,
    }


def _data_6m_atras() -> str:
    from datetime import datetime, timedelta
    return (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")


def _data_12m_atras() -> str:
    from datetime import datetime, timedelta
    return (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")


def _ano_atual() -> int:
    from datetime import datetime
    return datetime.now().year


def contar_por_tabela() -> dict:
    """Retorna resumo das contagens por tabela filtrando por São Paulo."""
    tabelas_uf = {
        "queimadas": "estado",
        "terras_indigenas": "uf",
        "desmatamento_alertas": "uf",
        "unidades_conservacao": "uf",
        "prodes_desmatamento": "estado",
        "comunidades_quilombolas": "uf",
        "sicar_imoveis": "cod_estado",
    }
    contagens = {}
    for t, col_uf in tabelas_uf.items():
        # Filtro padrão robusto para SP
        filtro = f"WHERE UPPER(TRIM(COALESCE({col_uf}, ''))) IN ('SP', 'SAO PAULO', 'SÃO PAULO', '35')"
        
        # Ajustes específicos
        if t == "unidades_conservacao":
            filtro = "WHERE UPPER(COALESCE(uf, '')) LIKE '%SP%'"
        elif t == "sicar_imoveis":
            filtro = "WHERE UPPER(TRIM(cod_estado)) IN ('SP', '35')"
            
        try:
            resultado = executar_consulta(f"SELECT COUNT(*) as total FROM {t} {filtro}")
            val = resultado[0]["total"] if resultado else 0
            contagens[t] = val
        except Exception as e:
            # Fallback silencioso para contagem zero em caso de erro de coluna
            contagens[t] = 0
    
    # Corpus ASG (Imóveis Rurais no Dashboard)
    try:
        res_corpus = executar_consulta("SELECT COUNT(*) as total FROM corpus_asg WHERE uf_sigla = 'SP'")
        contagens["corpus_asg"] = res_corpus[0]["total"] if res_corpus else 0
    except Exception:
        contagens["corpus_asg"] = 0
    
    return contagens


def buscar_fontes() -> list[dict]:
    return executar_consulta("SELECT * FROM fontes ORDER BY id")

def atualizar_data_coleta_fontes(entidades: list[str], data_atualizacao: datetime):
    """
    Atualiza a data_coleta na tabela 'fontes' baseado nas entidades que foram processadas.
    Se nenhuma entidade for encontrada ou lista estiver vazia, atualiza todas as fontes.
    """
    mapa_nomes = {
        "queimadas": "Queimadas (INPE)",
        "terras_indigenas": "Terras Indígenas (FUNAI)",
        "desmatamento_alertas": "Alertas DETER",
        "unidades_conservacao": "Unidades de Conservação",
        "prodes_desmatamento": "PRODES (INPE)",
        "comunidades_quilombolas": "Quilombos",
        "sicar": "SICAR SP"
    }

    # Se lista vazia ou não especificada, atualiza tudo
    if not entidades:
        sql_data = "UPDATE fontes SET data_coleta = :dt"
        executar_sql(sql_data, {"dt": data_atualizacao})
        return

    foi_atualizado_algo = False
    
    for ent in entidades:
        if ent == "tudo":
            sql_data = "UPDATE fontes SET data_coleta = :dt"
            executar_sql(sql_data, {"dt": data_atualizacao})
            foi_atualizado_algo = True
            continue

        nome_na_fonte = mapa_nomes.get(ent)
        if nome_na_fonte:
            sql_update = """
                UPDATE fontes 
                SET data_coleta = :dt 
                WHERE nome ILIKE :nome
            """
            executar_sql(sql_update, {"dt": data_atualizacao, "nome": f"%{nome_na_fonte}%"})
            foi_atualizado_algo = True
    
    # Se nenhuma entidade foi encontrada no mapa (entidade desconhecida), atualiza tudo como fallback
    if not foi_atualizado_algo:
        sql_data = "UPDATE fontes SET data_coleta = :dt"
        executar_sql(sql_data, {"dt": data_atualizacao})

def obter_resumo_fontes() -> dict:
    """
    Retorna o resumo lendo diretamente da tabela Fontes.
    """
    rows = executar_consulta("SELECT nome, data_coleta, total_registros FROM fontes")
    
    resumo = {}
    for r in rows:
        nome_chave = r["nome"].lower().replace(" ", "_")
        resumo[nome_chave] = {
            "contagem": r["total_registros"] or 0,
            "ultima_atualizacao": r["data_coleta"].isoformat() if r["data_coleta"] else "N/A"
        }
    return resumo