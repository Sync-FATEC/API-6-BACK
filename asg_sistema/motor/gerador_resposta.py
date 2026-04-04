"""Gera respostas rastreavies com resumo, estatisticas, fontes e GeoJSON."""

import json


MAPA_FONTE_NOME = {
    "queimadas": "INPE/Queimadas",
    "funai": "FUNAI",
    "deter": "INPE/DETER",
    "icmbio": "MMA/ICMBio",
    "palmares": "Fundação Cultural Palmares",
    "prodes": "INPE/PRODES",
    "sicar": "SICAR/CAR",
}


class GeradorResposta:
    def gerar(self, pergunta: str, intencao: str, confianca: float,
              entidades: dict, resultados: list[dict],
              resultados_geo: list[dict] | None = None,
              intencoes_detectadas: list[dict] | None = None) -> dict:
        geo_source = resultados_geo if resultados_geo is not None else resultados
        # Gera GeoJSON primeiro para usar o count real de features como total
        geojson = self._gerar_geojson(geo_source)
        total_geo = len(geojson["features"]) if geojson else 0

        if intencoes_detectadas and len(intencoes_detectadas) > 1:
            resumo = self._gerar_resumo_multiplo(intencoes_detectadas, total_geo, entidades, resultados)
        else:
            resumo = self._gerar_resumo(intencao, total_geo, entidades)

        return {
            "pergunta": pergunta,
            "intencao_detectada": intencao,
            "confianca": round(confianca, 3),
            "entidades": entidades,
            "resumo": resumo,
            "estatisticas": self._calcular_estatisticas(intencao, resultados, total_geo),
            "dados": [self._parse_metadados(r) for r in resultados],
            "fontes": self._extrair_fontes(resultados),
            "geojson": geojson,
            "total_resultados": total_geo,
        }

    def _gerar_resumo_multiplo(self, intencoes: list[dict], total: int,
                               entidades: dict, resultados: list[dict]) -> str:
        municipios = entidades.get("municipios", [])
        local = f" no município de {municipios[0]}" if municipios else " no Estado de São Paulo"

        if total == 0:
            return f"Nenhum resultado encontrado para sua consulta{local}."

        NOMES_INTENCAO = {
            "consultar_queimadas": "focos de queimada",
            "consultar_desmatamento": "desmatamento (DETER/PRODES)",
            "consultar_terra_indigena": "terras indígenas",
            "consultar_unidade_conservacao": "unidades de conservação",
            "consultar_quilombola": "comunidades quilombolas",
            "consultar_prodes": "desmatamento PRODES",
            "resumo_municipal": "dados ASG",
        }

        # Mapa intenção -> fontes esperadas no corpus
        _FONTES_INTENCAO = {
            "consultar_queimadas": {"queimadas"},
            "consultar_desmatamento": {"deter", "prodes"},
            "consultar_terra_indigena": {"funai"},
            "consultar_unidade_conservacao": {"icmbio"},
            "consultar_quilombola": {"palmares"},
            "consultar_prodes": {"prodes"},
            "resumo_municipal": set(),
        }

        fontes_por_intencao = {}
        for intent_info in intencoes:
            intent = intent_info["intencao"]
            fontes_validas = _FONTES_INTENCAO.get(intent, set())
            count = sum(1 for r in resultados if r.get("fonte") in fontes_validas)
            fontes_por_intencao[intent] = count

        partes = []
        for intent_info in intencoes:
            intent = intent_info["intencao"]
            nome = NOMES_INTENCAO.get(intent, intent)
            count = fontes_por_intencao.get(intent, 0)
            if count > 0:
                partes.append(f"{count} registros de {nome}")

        if partes:
            lista = " e ".join(partes)
            return f"Foram encontrados {lista}{local}."
        return f"Foram encontrados {total} resultados{local}."

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
            "consultar_imovel_rural": f"Foram encontrados {total} imóveis rurais cadastrados no CAR{local}.",
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
        deter_resultados = []
        cods_sicar = []
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
            elif fonte == "deter":
                deter_resultados.append(r)
            elif fonte == "sicar":
                meta = self._parse_metadados(r)
                cod = meta.get("cod_imovel")
                if cod:
                    cods_sicar.append(cod)

        geometrias_ti = {}
        if nomes_ti:
            geometrias_ti = self._buscar_geometrias_terras_indigenas(nomes_ti)

        centroides_municipio = {}
        if municipios_sem_geo:
            centroides_municipio = self._buscar_centroides_municipios(municipios_sem_geo)

        centroides_prodes = {}
        if uids_prodes:
            centroides_prodes = self._buscar_geometrias_prodes(uids_prodes)

        geometrias_deter = {}
        if deter_resultados:
            geometrias_deter = self._buscar_geometrias_deter(deter_resultados)

        geometrias_sicar = {}
        if cods_sicar:
            geometrias_sicar = self._buscar_geometrias_sicar(cods_sicar)

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
            elif fonte == "sicar" and meta.get("cod_imovel"):
                geometry = geometrias_sicar.get(meta["cod_imovel"])
            elif fonte == "prodes" and meta.get("uid"):
                uid_str = str(meta["uid"])
                if uid_str in centroides_prodes:
                    geometry = centroides_prodes[uid_str]
            elif fonte == "deter" and r["id"] in geometrias_deter:
                geometry = geometrias_deter[r["id"]]
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

    def _buscar_geometrias_deter(self, resultados_deter: list[dict]) -> dict:
        """Retorna {corpus_id: geometry_dict} buscando polígonos da tabela desmatamento_alertas."""
        import json as _json
        import re as _re
        from asg_sistema.db.conexao import executar_consulta

        geometrias = {}
        for r in resultados_deter:
            mun = r.get("municipio", "")
            data_ref = str(r.get("data_referencia", "") or "")
            if not mun:
                continue
            nome = _re.sub(r"\s*\([A-Z]{2}\)\s*$", "", mun.split(",")[0].strip())
            params = {"mun": f"%{nome}%"}
            sql = (
                "SELECT ST_AsGeoJSON(geom) as geometry "
                "FROM desmatamento_alertas "
                "WHERE municipio ILIKE :mun AND geom IS NOT NULL"
            )
            if data_ref:
                sql += " AND CAST(data_avistamento AS TEXT) LIKE :data"
                params["data"] = f"{data_ref}%"
            sql += " LIMIT 1"
            try:
                rows = executar_consulta(sql, params)
                if rows and rows[0].get("geometry"):
                    geometrias[r["id"]] = _json.loads(rows[0]["geometry"])
            except Exception:
                pass
        return geometrias

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

    def _buscar_geometrias_sicar(self, cods: list[str]) -> dict:
        """Retorna {cod_imovel: geometry_dict} com polígono do imóvel rural."""
        import json as _json
        from asg_sistema.db.conexao import executar_consulta
        geometrias = {}
        try:
            placeholders = ",".join(f":c{i}" for i in range(len(cods)))
            params = {f"c{i}": c for i, c in enumerate(cods)}
            rows = executar_consulta(
                f"SELECT cod_imovel, ST_AsGeoJSON(geom) as geometry "
                f"FROM sicar_imoveis WHERE cod_imovel IN ({placeholders}) AND geom IS NOT NULL",
                params,
            )
            for row in rows:
                if row.get("geometry"):
                    geometrias[row["cod_imovel"]] = _json.loads(row["geometry"])
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
