# Metodologia — Nota de Risco Socioambiental ASG

## O que e

Dado o poligono de uma propriedade rural (SICAR/CAR), o sistema cruza espacialmente essa area com todas as fontes de dados ambientais e sociais do banco. Cada cruzamento gera uma sub-nota. A soma das sub-notas produz o **score final de 0 a 100**.

```
0 = nenhum risco detectado
100 = risco maximo em todos os eixos
```

---

## Visao Geral dos Eixos

```
              SCORE TOTAL (0 a 100)
 ┌──────────┬──────────┬─────────┬──────────┬──────────┐
 │Queimadas │  DETER   │ PRODES  │  Areas   │ Contexto │
 │  (INPE)  │  (INPE)  │ (INPE)  │Protegidas│ Municipal│
 │ 0-25 pts │ 0-25 pts │ 0-20pts │ 0-20 pts │ 0-10 pts │
 │ peso 25% │ peso 25% │ peso 20%│ peso 20% │ peso 10% │
 └──────────┴──────────┴─────────┴──────────┴──────────┘
```

---

## Eixo A — Queimadas (0 a 25 pontos)

**Fonte:** INPE/Queimadas

**Cruzamento:** focos de incendio DENTRO da fazenda + raio de 5 km ao redor.

| Fator | O que mede | Como calcula | Pontos |
|-------|-----------|--------------|--------|
| Densidade | Focos por km² | focos_dentro / area_km² x 10 | ate 10 |
| Intensidade | Forca do fogo (FRP em MW) | min(FRP_medio / 100, 1) x 8 | ate 8 |
| Recencia | Proporcao de focos recentes (6 meses) | focos_6m / total x 7 | ate 7 |

**Exemplo:** fazenda de 10 km², 20 focos dentro, FRP medio 50 MW, 15 recentes

- Densidade: (20/10) x 10 = 10.0
- Intensidade: (50/100) x 8 = 4.0
- Recencia: (15/20) x 7 = 5.25
- **Total: 19.25 / 25**

---

## Eixo B — Desmatamento DETER (0 a 25 pontos)

**Fonte:** INPE/DETER (alertas recentes de desmatamento)

**Cruzamento:** intersecao geometrica — calcula a area REAL de sobreposicao entre o alerta e a fazenda.

| Fator | O que mede | Como calcula | Pontos |
|-------|-----------|--------------|--------|
| % area afetada | Quanto da fazenda tem alerta | area_intersecao / area_fazenda x 50 | ate 15 |
| Quantidade | Numero de alertas distintos | total_alertas x 2 | ate 10 |

**Multiplicador temporal:** se todos os alertas sao dos ultimos 12 meses, score integral. Se nenhum e recente, score cortado pela metade.

```
score_final = score_bruto x (0.5 + 0.5 x recentes/total)
```

**Exemplo:** 3 alertas, 6.4% da area afetada, 2 recentes

- % afetada: min(6.4 x 50, 15) = 15.0
- Quantidade: min(3 x 2, 10) = 6.0
- Multiplicador: 0.5 + 0.5 x (2/3) = 0.83
- **Total: (15 + 6) x 0.83 = 17.4 / 25**

---

## Eixo C — Desmatamento PRODES (0 a 20 pontos)

**Fonte:** INPE/PRODES (desmatamento anual consolidado, Mata Atlantica)

**Cruzamento:** intersecao geometrica — area historica desmatada dentro da fazenda.

| Fator | O que mede | Como calcula | Pontos |
|-------|-----------|--------------|--------|
| % historico | Quanto da fazenda ja foi desmatado | area_hist / area_fazenda x 30 | ate 12 |
| Tendencia | Esta piorando? (3 anos recentes vs anteriores) | recentes / antigos x 4 | ate 8 |

Tendencia > 1 significa que o desmatamento esta acelerando.

**Exemplo:** 25.6% da fazenda com PRODES, 5 poligonos recentes, 3 antigos

- % historico: min(25.6 x 30, 12) = 12.0
- Tendencia: min((5/3) x 4, 8) = 6.67
- **Total: 18.67 / 20**

---

## Eixo D — Areas Protegidas: Terras Indigenas (0 a 20 pontos)

**Fonte:** FUNAI (poligonos oficiais de terras indigenas)

**Cruzamento:** intersecao direta + buffer de 10 km para proximidade.

**Logica:**

```
SE a fazenda SOBREPOE uma terra indigena:
    score = 12 pontos fixos + (% sobreposicao x 8)
    minimo 12, maximo 20
    retorna: nome da TI, etnia, area de sobreposicao

SE NAO sobrepoe, mas esta PERTO (ate 10 km):
    score = numero de TIs proximas x 2
    maximo 8
```

Sobreposicao com TI e um dos riscos legais mais graves — por isso o score minimo de 12/20.

**Exemplo 1 (sobreposicao):** fazenda sobrepoe TI "Boa Vista" (Guarani), 5.2% de overlap
- Score = 12 + 0.052 x 8 = **12.4 / 20**

**Exemplo 2 (proximidade):** sem sobreposicao, 2 TIs a menos de 10 km
- Score = 2 x 2 = **4.0 / 20**

---

## Eixo E — Contexto Municipal (0 a 10 pontos)

**Fonte:** ICMBio (Unidades de Conservacao) + Fundacao Cultural Palmares (Quilombolas)

**Cruzamento:** por municipio (essas fontes nao possuem geometria no banco).

| Fator | Pontos por ocorrencia | Maximo |
|-------|----------------------|--------|
| UCs de Protecao Integral (parques, reservas biologicas) | 3 pts cada | 5 |
| UCs de Uso Sustentavel (APAs, florestas nacionais) | 1 pt cada | 2 |
| Comunidades quilombolas certificadas | 2 pts cada | 3 |

**Exemplo:** municipio com 1 UC integral, 2 UCs sustentaveis, 0 quilombolas
- 1x3 + 2x1 + 0 = **5.0 / 10**

---

## Calculo Final

```
SCORE = Queimadas + DETER + PRODES + Areas Protegidas + Contexto
         (0-25)    (0-25)   (0-20)      (0-20)           (0-10)
```

## Classificacao

| Score | Classificacao | Significado |
|-------|--------------|-------------|
| 0 — 20 | Baixo Risco | Nenhum ou poucos eventos detectados |
| 21 — 40 | Risco Moderado | Alguns eventos, sem gravidade imediata |
| 41 — 60 | Risco Elevado | Eventos significativos, requer atencao |
| 61 — 80 | Risco Alto | Multiplos fatores graves combinados |
| 81 — 100 | Risco Critico | Sobreposicao de problemas serios |

---

## Transparencia da Resposta

Para cada eixo o sistema retorna:

1. A nota do eixo (ex: 18.5 / 25)
2. Os dados brutos que geraram a nota (ex: 23 focos, FRP medio 42.3 MW)
3. As fontes consultadas (INPE, FUNAI, ICMBio, Palmares)
4. GeoJSON com todos os cruzamentos para visualizar no mapa

---

## Pontos em Aberto para Validacao

1. **Os pesos estao adequados?** Queimadas e DETER com 25% cada, PRODES e TI com 20%, contexto municipal 10%.

2. **Os raios de buffer fazem sentido?** 5 km para queimadas, 10 km para terras indigenas. Podem ser configuraveis.

3. **Periodo de tendencia PRODES:** 3 anos e suficiente ou deveria ser 5?

4. **Sobreposicao com TI como score minimo 12/20** — faz sentido pela gravidade legal?

5. **Status do SICAR:** imovel com CAR cancelado/suspenso deveria receber penalizacao adicional?

6. **UCs e quilombolas sem geometria:** cruzamento por municipio e aceitavel ou precisa de outra fonte com poligonos?
