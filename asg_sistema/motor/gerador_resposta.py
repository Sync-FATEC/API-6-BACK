"""Gera respostas rastreavies com resumo, estatisticas, fontes e GeoJSON."""

import json


MAPA_FONTE_NOME = {
    "queimadas": "INPE/Queimadas",
    "funai": "FUNAI",
    "deter": "INPE/DETER",
    "icmbio": "MMA/ICMBio",
    "palmares": "Fundação Cultural Palmares",
    "prodes": "INPE/PRODES",
}


class GeradorResposta:
    def gerar(self, pergunta: str, intencao: str, confianca: float,
              entidades: dict, resultados: list[dict],
              resultados_geo: list[dict] | None = None) -> dict:
        geo_source = resultados_geo if resultados_geo is not None else resultados
        # Gera GeoJSON primeiro para usar o count real de features como total
        geojson = self._gerar_geojson(geo_source)
        total_geo = len(geojson["features"]) if geojson else 0
        return {
            "pergunta": pergunta,
            "intencao_detectada": intencao,
            "confianca": round(confianca, 3),
            "entidades": entidades,
            "resumo": self._gerar_resumo(intencao, total_geo, entidades),
            "estatisticas": self._calcular_estatisticas(intencao, resultados, total_geo),
            "dados": [self._parse_metadados(r) for r in resultados],
            "fontes": self._extrair_fontes(resultados),
            "geojson": geojson,
            "total_resultados": total_geo,
        }

    def _gerar_resumo(self, intencao: str, total: int, entidades: dict) -> str:
        municipios = entidades.get("municipios", [])
        local = f" no município de {municipios[0]}" if municipios else " no Estado de São Paulo"

        if total == 0:
            return f"Nenhum resultado encontrado para sua consulta{local}."

        resumos = {
            "consultar_queimadas": f"Foram encontrados {total} registros de focos de queimada{local}.",
            "consultar_desmatamento": f"Foram encontrados {total} registros de desmatamento (DETER/PRODES){local}.",
            "consultar_terra_indigena": f"Foram encontradas {total} terras indígenas{local}.",
            "consultar_unidade_conservacao": f"Foram encontradas {total} unidades de conservação{local}.",
            "consultar_quilombola": f"Foram encontradas {total} comunidades quilombolas{local}.",
            "consultar_prodes": f"Foram encontrados {total} registros de desmatamento PRODES{local}.",
            "resumo_municipal": f"Foram encontrados {total} registros ASG{local}.",
        }
        return resumos.get(intencao, f"Foram encontrados {total} resultados{local}.")

    def _calcular_estatisticas(self, intencao: str, resultados: list[dict],
                               total_geo: int = 0) -> dict:
        if not resultados and total_geo == 0:
            return {}

        stats = {"total": total_geo}

        if intencao == "consultar_queimadas":
            frps = []
            for r in resultados:
                meta = self._parse_metadados(r)
                frp = meta.get("frp")
                if frp and frp != "":
                    try:
                        frps.append(float(frp))
                    except (ValueError, TypeError):
                        pass
            if frps:
                stats["frp_medio"] = round(sum(frps) / len(frps), 2)

        return stats

    def _extrair_fontes(self, resultados: list[dict]) -> list[dict]:
        fontes_vistas = set()
        fontes = []
        for r in resultados:
            fonte = r.get("fonte", "")
            if fonte not in fontes_vistas:
                fontes_vistas.add(fonte)
                fontes.append({
                    "nome": MAPA_FONTE_NOME.get(fonte, fonte),
                    "identificador": fonte,
                })
        return fontes

    def _gerar_geojson(self, resultados: list[dict]) -> dict | None:
        features = []

        import math

        nomes_ti = []
        municipios_sem_geo = set()
        uids_prodes = []
        for r in resultados:
            fonte = r.get("fonte", "")
            if fonte == "funai":
                meta = self._parse_metadados(r)
                nome = meta.get("nome", "")
                if nome:
                    nomes_ti.append(nome)
            elif fonte in ("icmbio", "palmares"):
                mun = r.get("municipio", "")
                if mun:
                    municipios_sem_geo.add(mun)
            elif fonte == "prodes":
                meta = self._parse_metadados(r)
                uid = meta.get("uid")
                if uid:
                    uids_prodes.append(str(uid))

        geometrias_ti = {}
        if nomes_ti:
            geometrias_ti = self._buscar_geometrias_terras_indigenas(nomes_ti)

        centroides_municipio = {}
        if municipios_sem_geo:
            centroides_municipio = self._buscar_centroides_municipios(municipios_sem_geo)

        centroides_prodes = {}
        if uids_prodes:
            centroides_prodes = self._buscar_geometrias_prodes(uids_prodes)

        # rastreia coordenadas já usadas para aplicar spiral offset em pontos idênticos
        _coord_count: dict = {}

        for r in resultados:
            meta = self._parse_metadados(r)
            geometry = None
            fonte = r.get("fonte", "")

            if fonte == "funai" and meta.get("nome"):
                chave = meta["nome"] + "_" + (meta.get("fase") or "")
                if chave in geometrias_ti:
                    geometry = geometrias_ti[chave]
                elif meta["nome"] + "_" in geometrias_ti:
                    geometry = geometrias_ti[meta["nome"] + "_"]
            elif fonte == "prodes" and meta.get("uid"):
                uid_str = str(meta["uid"])
                if uid_str in centroides_prodes:
                    geometry = centroides_prodes[uid_str]
            elif meta.get("geometry"):
                geometry = meta["geometry"]
            elif meta.get("latitude") and meta.get("longitude"):
                try:
                    geometry = {
                        "type": "Point",
                        "coordinates": [float(meta["longitude"]), float(meta["latitude"])],
                    }
                except (ValueError, TypeError):
                    pass
            elif meta.get("centroid_lon") and meta.get("centroid_lat"):
                try:
                    geometry = {
                        "type": "Point",
                        "coordinates": [float(meta["centroid_lon"]), float(meta["centroid_lat"])],
                    }
                except (ValueError, TypeError):
                    pass

            # fallback: busca centroide do município para icmbio/palmares
            if geometry is None and fonte in ("icmbio", "palmares"):
                mun = r.get("municipio", "")
                if mun and mun in centroides_municipio:
                    lon, lat = centroides_municipio[mun]
                    geometry = {"type": "Point", "coordinates": [lon, lat]}

            # aplica spiral offset em pontos com coordenadas idênticas (qualquer fonte)
            if geometry and geometry.get("type") == "Point":
                coords = geometry["coordinates"]
                coord_key = (round(coords[0], 4), round(coords[1], 4))
                count = _coord_count.get(coord_key, 0)
                _coord_count[coord_key] = count + 1
                if count > 0:
                    angle = count * 2.399  # golden angle em radianos
                    radius = 0.04 * (count ** 0.5)
                    geometry = {
                        "type": "Point",
                        "coordinates": [
                            round(coords[0] + radius * math.cos(angle), 6),
                            round(coords[1] + radius * math.sin(angle), 6),
                        ],
                    }

            if geometry:
                props = {
                    "texto": r.get("texto", "")[:200],
                    "fonte": fonte,
                    "municipio": r.get("municipio", ""),
                    "data_referencia": str(r.get("data_referencia", "") or ""),
                }
                for key, value in meta.items():
                    if key not in ("geometry", "latitude", "longitude",
                                   "centroid_lon", "centroid_lat"):
                        props[key] = value
                features.append({
                    "type": "Feature",
                    "geometry": geometry,
                    "properties": props,
                })

        if not features:
            return None
        return {"type": "FeatureCollection", "features": features}

    def _buscar_geometrias_prodes(self, uids: list[str]) -> dict:
        """Retorna {uid: geometry_dict} com polígono completo dos registros PRODES."""
        import json as _json
        from asg_sistema.db.conexao import executar_consulta
        geometrias = {}
        try:
            placeholders = ",".join(f":uid{i}" for i in range(len(uids)))
            params = {f"uid{i}": int(u) for i, u in enumerate(uids)}
            rows = executar_consulta(
                f"SELECT uid, ST_AsGeoJSON(geom) as geometry "
                f"FROM prodes_desmatamento WHERE uid IN ({placeholders}) AND geom IS NOT NULL",
                params,
            )
            for row in rows:
                if row.get("geometry"):
                    geometrias[str(row["uid"])] = _json.loads(row["geometry"])
        except Exception:
            pass
        return geometrias

    def _buscar_centroides_municipios(self, municipios: set) -> dict:
        """Retorna {municipio: (lon, lat)} tentando múltiplas tabelas como fallback."""
        import re
        from asg_sistema.db.conexao import executar_consulta

        def _nome_simples(mun: str) -> str:
            """Extrai primeiro município da string, remove estado e normaliza."""
            primeiro = mun.split(",")[0].strip()
            primeiro = re.sub(r"\s*\([A-Z]{2}\)\s*$", "", primeiro).strip()
            return primeiro

        # Queries em ordem de prioridade para encontrar centroide
        _queries = [
            "SELECT AVG(longitude) as lon, AVG(latitude) as lat "
            "FROM queimadas WHERE municipio ILIKE :mun",
            "SELECT ST_X(ST_Centroid(ST_Collect(geom))) as lon, "
            "ST_Y(ST_Centroid(ST_Collect(geom))) as lat "
            "FROM terras_indigenas WHERE municipio ILIKE :mun AND geom IS NOT NULL",
            "SELECT AVG(ST_X(ST_Centroid(geom))) as lon, AVG(ST_Y(ST_Centroid(geom))) as lat "
            "FROM desmatamento_alertas WHERE municipio ILIKE :mun AND geom IS NOT NULL",
        ]

        centroides = {}
        for mun in municipios:
            nome = _nome_simples(mun)
            params = {"mun": f"%{nome}%"}
            for query in _queries:
                try:
                    rows = executar_consulta(query, params)
                    if rows and rows[0].get("lon") and rows[0].get("lat"):
                        centroides[mun] = (round(rows[0]["lon"], 6), round(rows[0]["lat"], 6))
                        break
                except Exception:
                    continue
        return centroides

    def _buscar_geometrias_terras_indigenas(self, nomes: list[str]) -> dict:
        """Busca poligonos reais das terras indigenas pelo nome."""
        import json as _json
        from asg_sistema.db.conexao import executar_consulta

        geometrias = {}
        for nome in nomes:
            try:
                rows = executar_consulta(
                    "SELECT ST_AsGeoJSON(geom) as geometry, nome, fase "
                    "FROM terras_indigenas WHERE nome = :nome AND geom IS NOT NULL",
                    {"nome": nome},
                )
                for row in rows:
                    if row.get("geometry"):
                        chave = nome + "_" + (row.get("fase") or "")
                        geometrias[chave] = _json.loads(row["geometry"])
            except Exception:
                pass
        return geometrias

    def _parse_metadados(self, registro: dict) -> dict:
        meta = registro.get("metadados_json")
        if meta is None:
            return {}
        if isinstance(meta, str):
            try:
                return json.loads(meta)
            except json.JSONDecodeError:
                return {}
        return meta
