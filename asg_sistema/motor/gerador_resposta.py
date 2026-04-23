"""Gera respostas rastreavies com resumo, estatisticas, fontes e GeoJSON."""

import json
from datetime import datetime


SP_BBOX = (-53.2, -25.4, -44.1, -19.8)


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

        # Nota de risco apenas em consultas por código CAR (gerar_resposta_car).
        # Consultas gerais não recebem score — não há objeto de análise definido.
        nota_risco_vazia = {
            "nota": 0,
            "nivel": "sem_dados",
            "fatores": [],
            "por_dimensao": {},
        }
        resposta = {
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
            "nota_risco": None,
        }
        resposta["exportacao_relatorio"] = self._montar_exportacao_relatorio(
            pergunta=pergunta,
            intencao=intencao,
            resumo=resumo,
            nota_risco=nota_risco_vazia,
            dados_origem=resultados,
            dados=self._normalizar_linhas_tabela(resultados),
            fontes=resposta["fontes"],
            total_resultados=total_geo,
            entidades=entidades,
        )
        return resposta

    def gerar_resposta_car(self, pergunta: str, imovel: dict, cruzamento: dict) -> dict:
        """Gera resposta completa para consulta por código CAR com cruzamento espacial."""
        cod = imovel.get("cod_imovel", "")
        mun = imovel.get("municipio", "")
        area = round(float(imovel.get("area_ha_calc") or imovel.get("num_area") or 0), 1)
        status_map = {"AT": "Ativo", "PE": "Pendente", "SU": "Suspenso", "CA": "Cancelado"}
        status = status_map.get(imovel.get("ind_status", ""), imovel.get("ind_status", ""))

        # Montar ameaças
        ameacas = []
        q = cruzamento["queimadas"]
        if q["focos_total"] > 0:
            ameacas.append({
                "tipo": "queimada", "quantidade": q["focos_total"],
                "dentro_imovel": q["focos_internos"],
                "distancia_min_km": q["distancia_min_km"],
                "frp_medio": round(q["frp_medio"], 1) if q["frp_medio"] else 0,
            })

        d = cruzamento["deter"]
        if d["total_alertas"] > 0:
            ameacas.append({
                "tipo": "desmatamento_deter", "quantidade": d["total_alertas"],
                "area_intersecao_km2": d["area_intersecao_km2"],
                "distancia_min_km": d["distancia_min_km"],
            })

        p = cruzamento["prodes"]
        if p["total_poligonos"] > 0:
            ameacas.append({
                "tipo": "desmatamento_prodes", "quantidade": p["total_poligonos"],
                "area_hist_km2": p["area_hist_km2"],
                "distancia_min_km": p["distancia_min_km"],
            })

        ti = cruzamento["terras_indigenas"]
        if ti["sobrepoe"] or ti["proximas_10km"]:
            ameacas.append({
                "tipo": "terra_indigena",
                "sobrepoe": ti["sobrepoe"],
                "sobreposicoes": ti["sobreposicoes"],
                "proximas_10km": len(ti["proximas_10km"]),
            })

        uc = cruzamento["unidades_conservacao"]
        if uc["total"] > 0:
            ameacas.append({
                "tipo": "unidade_conservacao", "quantidade": uc["total"],
                "protecao_integral": uc["protecao_integral"],
                "no_municipio": True,
            })

        ql = cruzamento["quilombolas"]
        if ql["total"] > 0:
            ameacas.append({
                "tipo": "quilombola", "quantidade": ql["total"],
                "no_municipio": True,
            })

        # Resumo textual
        partes_resumo = []
        if q["focos_total"] > 0:
            txt = f"{q['focos_total']} focos de queimada"
            if q["focos_internos"] > 0:
                txt += f" ({q['focos_internos']} dentro do imóvel)"
            else:
                txt += f" a {q['distancia_min_km']}km"
            partes_resumo.append(txt)
        if d["total_alertas"] > 0:
            partes_resumo.append(f"{d['total_alertas']} alertas DETER a {d['distancia_min_km']}km")
        if p["total_poligonos"] > 0:
            partes_resumo.append(f"{p['total_poligonos']} polígonos PRODES a {p['distancia_min_km']}km")
        if ti["sobrepoe"]:
            nomes = ", ".join(s["nome"] for s in ti["sobreposicoes"])
            partes_resumo.append(f"sobreposição com terra indígena: {nomes}")
        elif ti["proximas_10km"]:
            partes_resumo.append(f"{len(ti['proximas_10km'])} terras indígenas a menos de 10km")
        if uc["total"] > 0:
            partes_resumo.append(f"{uc['total']} unidades de conservação no município")
        if ql["total"] > 0:
            partes_resumo.append(f"{ql['total']} comunidades quilombolas no município")

        if partes_resumo:
            detalhes = ", ".join(partes_resumo)
            resumo = f"O imóvel {cod} ({area} ha, {mun}) apresenta: {detalhes}."
        else:
            resumo = f"O imóvel {cod} ({area} ha, {mun}) não apresenta problemas ambientais detectados na região."

        features = []

        if imovel.get("geometry"):
            features.append({
                "type": "Feature",
                "geometry": imovel["geometry"],
                "properties": {
                    "texto": f"Imóvel rural cadastrado no SICAR/CAR com código {cod}. Situação: {status}.",
                    "fonte": "sicar",
                    "cod_imovel": cod,
                    "municipio": mun,
                    "num_area": area,
                    "ind_status": imovel.get("ind_status", status),
                    "ind_tipo": imovel.get("ind_tipo", "IRU"),
                    "des_condic": imovel.get("des_condic", ""),
                    "mod_fiscal": imovel.get("mod_fiscal", ""),
                    "data_referencia": imovel.get("dat_atualizacao", ""),
                },
            })

            for item in q.get("geo", []):
                if item.get("geometry"):
                    features.append({
                        "type": "Feature",
                        "geometry": item["geometry"],
                        "properties": {
                            "texto": f"Foco de queimada detectado a {round(float(item.get('distancia_km') or 0), 2)}km.",
                            "fonte": "queimadas",
                            "satelite": item.get("satelite", ""),
                            "data_referencia": str(item.get("data_hora", "")),
                            "frp": item.get("frp"),
                            "bioma": item.get("bioma", ""),
                            "risco_fogo": item.get("risco_fogo", ""),
                            "distancia_km": round(float(item.get("distancia_km") or 0), 2),
                        },
                    })
                    
            for item in d.get("geo", []):
                if item.get("geometry"):
                    features.append({
                        "type": "Feature",
                        "geometry": item["geometry"],
                        "properties": {
                            "texto": f"Alerta DETER da classe {item.get('classe', '')}.",
                            "fonte": "deter",
                            "classe": item.get("classe", ""),
                            "data_referencia": str(item.get("data_avistamento", "")),
                            "area_total_km2": item.get("area_total_km2"),
                            "distancia_km": round(float(item.get("distancia_km") or 0), 2),
                        },
                    })
                    
            for item in p.get("geo", []):
                if item.get("geometry"):
                    features.append({
                        "type": "Feature",
                        "geometry": item["geometry"],
                        "properties": {
                            "texto": f"Polígono PRODES de desmatamento do ano {item.get('ano', '')}.",
                            "fonte": "prodes",
                            "ano": item.get("ano"),
                            "classe_nome": item.get("classe_nome", f"d{item.get('ano')}"),
                            "area_km": item.get("area_km"),
                            "distancia_km": round(float(item.get("distancia_km") or 0), 2),
                        },
                    })
                    
            for item in ti.get("sobreposicoes", []):
                if item.get("geometry"):
                    features.append({
                        "type": "Feature",
                        "geometry": item["geometry"],
                        "properties": {
                            "texto": f"Terra Indígena {item.get('nome', '')}.",
                            "fonte": "funai",
                            "nome": item.get("nome", ""),
                            "etnia": item.get("etnia", ""),
                            "fase": item.get("fase", ""),
                            "area_ha": item.get("area_ha", ""),
                            "sobreposicao_ha": item.get("area_sobreposicao_ha", 0),
                        },
                    })
                    
            for item in ti.get("proximas_10km", []):
                if item.get("geometry"):
                    features.append({
                        "type": "Feature",
                        "geometry": item["geometry"],
                        "properties": {
                            "texto": f"Terra Indígena {item.get('nome', '')}.",
                            "fonte": "funai",
                            "nome": item.get("nome", ""),
                            "etnia": item.get("etnia", ""),
                            "fase": item.get("fase", ""),
                            "area_ha": item.get("area_ha", ""),
                            "distancia_km": item.get("distancia_km", 0),
                        },
                    })

        geojson = {"type": "FeatureCollection", "features": features} if features else None

        fontes_usadas = []
        fontes_set = set()
        for a in ameacas:
            fonte_id = a["tipo"]
            if fonte_id not in fontes_set:
                fontes_set.add(fonte_id)
                nome = {
                    "queimada": "INPE/Queimadas",
                    "desmatamento_deter": "INPE/DETER",
                    "desmatamento_prodes": "INPE/PRODES",
                    "terra_indigena": "FUNAI",
                    "unidade_conservacao": "MMA/ICMBio",
                    "quilombola": "Fundação Cultural Palmares",
                }.get(fonte_id, fonte_id)
                fontes_usadas.append({"nome": nome, "identificador": fonte_id})

        resposta = {
            "pergunta": pergunta,
            "intencao_detectada": "consultar_imovel_rural",
            "confianca": 0.95,
            "entidades": {"codigos_car": [cod]},
            "imovel": {
                "cod_imovel": cod,
                "municipio": mun,
                "area_ha": area,
                "status": status,
                "ind_tipo": imovel.get("ind_tipo", ""),
                "des_condic": imovel.get("des_condic", ""),
                "dat_criacao": imovel.get("dat_criacao", ""),
                "dat_atualizacao": imovel.get("dat_atualizacao", ""),
            },
            "ameacas_encontradas": ameacas,
            "cruzamento": cruzamento,
            "resumo": resumo,
            "estatisticas": {"total_ameacas": len(ameacas)},
            "dados": [],
            "fontes": fontes_usadas,
            "geojson": geojson,
            "total_resultados": len(features),
        }
        # Nota de risco via AHP (substitui a versão heurística)
        from asg_sistema.motor.calculadora_risco import calcular_score_ahp
        area_km2 = area / 100 if area else 0.01  # ha -> km²
        nota_risco = calcular_score_ahp(cruzamento, area_km2)
        resposta["nota_risco"] = nota_risco
        resposta["exportacao_relatorio"] = self._montar_exportacao_relatorio(
            pergunta=pergunta,
            intencao="consultar_imovel_rural",
            resumo=resumo,
            nota_risco=nota_risco,
            dados_origem=ameacas,
            dados=self._normalizar_linhas_tabela_car(ameacas),
            fontes=fontes_usadas,
            total_resultados=len(ameacas),
            entidades={"codigos_car": [cod]},
            imovel=imovel,
        )
        return resposta

    def _normalizar_linhas_tabela(self, resultados: list[dict]) -> list[dict]:
        linhas = []
        for r in resultados:
            meta = self._parse_metadados(r)
            linhas.append({
                "fonte": r.get("fonte", ""),
                "tipo_registro": r.get("tipo_registro", ""),
                "municipio": r.get("municipio", ""),
                "data_referencia": str(r.get("data_referencia", "") or ""),
                "similaridade": round(float(r.get("similaridade") or 0), 4),
                "descricao": r.get("texto", ""),
                "metadados": meta,
            })
        return linhas

    def _normalizar_linhas_tabela_car(self, ameacas: list[dict]) -> list[dict]:
        linhas = []
        for item in ameacas:
            linhas.append({
                "fonte": item.get("tipo", ""),
                "tipo_registro": item.get("tipo", ""),
                "municipio": "",
                "data_referencia": "",
                "similaridade": None,
                "descricao": json.dumps(item, ensure_ascii=False, default=str),
                "metadados": item,
            })
        return linhas

    def _montar_exportacao_relatorio(
        self,
        pergunta: str,
        intencao: str,
        resumo: str,
        nota_risco: dict,
        dados_origem: list[dict],
        dados: list[dict],
        fontes: list[dict],
        total_resultados: int,
        entidades: dict,
        imovel: dict | None = None,
    ) -> dict:
        """Payload estável para geração de relatório via Jinja2/PDF."""
        tabela = {
            "colunas": [
                "fonte",
                "tipo_registro",
                "municipio",
                "data_referencia",
                "similaridade",
                "descricao",
                "metadados",
            ],
            "linhas": dados,
            "total_linhas": len(dados),
        }
        metadados = {
            "gerado_em": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "versao_payload": "1.0",
            "pergunta_original": pergunta,
            "intencao_detectada": intencao,
            "total_resultados": total_resultados,
            "total_registros_origem": len(dados_origem),
            "fontes_consideradas": [f.get("identificador") for f in fontes],
            "fontes_detalhes": fontes,
            "entidades": entidades,
        }
        if imovel:
            metadados["imovel"] = {
                "cod_imovel": imovel.get("cod_imovel", ""),
                "municipio": imovel.get("municipio", ""),
                "area_ha": round(float(imovel.get("area_ha_calc") or imovel.get("num_area") or 0), 2),
                "status": imovel.get("ind_status", ""),
            }

        return {
            "resumo": {
                "texto": resumo,
                "total_itens": total_resultados,
            },
            "nota_asg": {
                "valor": int(nota_risco.get("nota") or 0),
                "nivel": nota_risco.get("nivel", "sem_dados"),
                "fatores": nota_risco.get("fatores", []),
                "por_dimensao": nota_risco.get("por_dimensao", {}),
            },
            "tabela": tabela,
            "metadados": metadados,
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
            "consultar_imovel_rural": "imóveis rurais (CAR/SICAR)",
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
            "consultar_imovel_rural": {"sicar"},
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

        cod_car = entidades.get("cod_imovel")
        sufixo_car = f" (imóvel CAR {cod_car})" if cod_car else ""

        resumos = {
            "consultar_queimadas": f"Foram encontrados {total} registros de focos de queimada{local}.",
            "consultar_desmatamento": f"Foram encontrados {total} registros de desmatamento (DETER/PRODES){local}.",
            "consultar_terra_indigena": f"Foram encontradas {total} terras indígenas{local}.",
            "consultar_unidade_conservacao": f"Foram encontradas {total} unidades de conservação{local}.",
            "consultar_quilombola": f"Foram encontradas {total} comunidades quilombolas{local}.",
            "consultar_prodes": f"Foram encontrados {total} registros de desmatamento PRODES{local}.",
            "consultar_imovel_rural": (
                f"Foram encontrados {total} imóveis rurais cadastrados no CAR{local}{sufixo_car}."
            ),
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

            if geometry and not self._geometry_em_sp(geometry):
                continue

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
                "WHERE municipio ILIKE :mun "
                "AND geom IS NOT NULL "
                "AND UPPER(TRIM(uf)) IN ('SP', 'SAO PAULO', 'SÃO PAULO')"
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
                f"FROM prodes_desmatamento "
                f"WHERE uid IN ({placeholders}) "
                f"AND geom IS NOT NULL "
                f"AND UPPER(TRIM(estado)) IN ('SP', 'SAO PAULO', 'SÃO PAULO')",
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
            "FROM queimadas "
            "WHERE municipio ILIKE :mun "
            "AND UPPER(TRIM(estado)) IN ('SP', 'SAO PAULO', 'SÃO PAULO')",
            "SELECT ST_X(ST_Centroid(ST_Collect(geom))) as lon, "
            "ST_Y(ST_Centroid(ST_Collect(geom))) as lat "
            "FROM terras_indigenas "
            "WHERE municipio ILIKE :mun "
            "AND geom IS NOT NULL "
            "AND UPPER(TRIM(uf)) IN ('SP', 'SAO PAULO', 'SÃO PAULO')",
            "SELECT AVG(ST_X(ST_Centroid(geom))) as lon, AVG(ST_Y(ST_Centroid(geom))) as lat "
            "FROM desmatamento_alertas "
            "WHERE municipio ILIKE :mun "
            "AND geom IS NOT NULL "
            "AND UPPER(TRIM(uf)) IN ('SP', 'SAO PAULO', 'SÃO PAULO')",
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
                    "FROM terras_indigenas "
                    "WHERE nome = :nome "
                    "AND geom IS NOT NULL "
                    "AND UPPER(TRIM(uf)) IN ('SP', 'SAO PAULO', 'SÃO PAULO')",
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
                f"FROM sicar_imoveis "
                f"WHERE cod_imovel IN ({placeholders}) "
                f"AND geom IS NOT NULL "
                f"AND CAST(cod_estado AS TEXT) IN ('35', 'SP')",
                params,
            )
            for row in rows:
                if row.get("geometry"):
                    geometrias[row["cod_imovel"]] = _json.loads(row["geometry"])
        except Exception:
            pass
        return geometrias

    def _geometry_em_sp(self, geometry: dict | None) -> bool:
        if not isinstance(geometry, dict):
            return False

        if geometry.get("type") == "GeometryCollection":
            for geom in geometry.get("geometries", []):
                if self._geometry_em_sp(geom):
                    return True
            return False

        limites = self._limites_geometria(geometry.get("coordinates"))
        if limites is None:
            return False

        min_lon, min_lat, max_lon, max_lat = limites
        sp_min_lon, sp_min_lat, sp_max_lon, sp_max_lat = SP_BBOX
        return not (
            max_lon < sp_min_lon
            or min_lon > sp_max_lon
            or max_lat < sp_min_lat
            or min_lat > sp_max_lat
        )

    def _limites_geometria(self, coords) -> tuple[float, float, float, float] | None:
        limites = {"min_lon": None, "min_lat": None, "max_lon": None, "max_lat": None}

        def _varrer(nodo):
            if not isinstance(nodo, list) or not nodo:
                return

            primeiro = nodo[0]
            if isinstance(primeiro, (int, float)):
                if len(nodo) < 2:
                    return
                lon = float(nodo[0])
                lat = float(nodo[1])
                limites["min_lon"] = lon if limites["min_lon"] is None else min(limites["min_lon"], lon)
                limites["max_lon"] = lon if limites["max_lon"] is None else max(limites["max_lon"], lon)
                limites["min_lat"] = lat if limites["min_lat"] is None else min(limites["min_lat"], lat)
                limites["max_lat"] = lat if limites["max_lat"] is None else max(limites["max_lat"], lat)
                return

            for item in nodo:
                _varrer(item)

        _varrer(coords)

        if limites["min_lon"] is None:
            return None
        return (
            limites["min_lon"],
            limites["min_lat"],
            limites["max_lon"],
            limites["max_lat"],
        )

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
