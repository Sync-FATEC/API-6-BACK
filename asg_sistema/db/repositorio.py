from asg_sistema.db.conexao import executar_consulta


def busca_vetorial(
    embedding_str: str,
    fonte: str | None = None,
    fontes: list[str] | None = None,
    municipio: str | None = None,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    limite: int = 15,
) -> list[dict]:
    filtros = []
    params = {"emb": embedding_str, "limite": limite}

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
        "SELECT AVG(longitude) as lon, AVG(latitude) as lat FROM queimadas WHERE municipio ILIKE :mun",
        {"mun": f"%{nome}%"},
    )
    if not rows or not rows[0].get("lon"):
        return []
    lon = rows[0]["lon"]
    lat = rows[0]["lat"]
    uid_rows = executar_consulta(
        """SELECT uid FROM prodes_desmatamento
           WHERE geom IS NOT NULL
             AND ST_DWithin(geom::geography,
                            ST_SetSRID(ST_MakePoint(:lon, :lat), 4674)::geography,
                            :raio_m)""",
        {"lon": lon, "lat": lat, "raio_m": raio_graus * 111000},
    )
    return [str(r["uid"]) for r in uid_rows if r.get("uid") is not None]


def busca_vetorial_prodes_uids(
    embedding_str: str,
    uids: list[str],
    limite: int = 15,
) -> list[dict]:
    """Busca semântica no corpus PRODES filtrada por UIDs específicos."""
    if not uids:
        return []
    placeholders = ",".join(f":u{i}" for i in range(len(uids)))
    params = {"emb": embedding_str, "limite": limite}
    for i, u in enumerate(uids):
        params[f"u{i}"] = u
    sql = f"""
        SELECT id, fonte, tipo_registro, municipio, data_referencia,
               texto, metadados_json,
               1 - (embedding <=> :emb) AS similaridade
        FROM corpus_asg
        WHERE fonte = 'prodes'
          AND (metadados_json->>'uid') IN ({placeholders})
        ORDER BY embedding <=> :emb
        LIMIT :limite
    """
    return executar_consulta(sql, params)


def contar_por_tabela() -> dict:
    tabelas = ["queimadas", "terras_indigenas", "desmatamento_alertas",
               "unidades_conservacao", "prodes_desmatamento",
               "comunidades_quilombolas", "corpus_asg"]
    contagens = {}
    for t in tabelas:
        resultado = executar_consulta(f"SELECT COUNT(*) as total FROM {t}")
        contagens[t] = resultado[0]["total"] if resultado else 0
    return contagens


def buscar_fontes() -> list[dict]:
    return executar_consulta("SELECT * FROM fontes ORDER BY id")
