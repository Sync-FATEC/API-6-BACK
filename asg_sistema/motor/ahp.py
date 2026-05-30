"""Analytic Hierarchy Process (AHP) — cálculo de pesos e consistência.

Método científico de Saaty para tomada de decisão com múltiplos critérios.
Em vez de pesos arbitrários, deriva os pesos a partir de uma matriz de
comparação par a par entre os critérios (escala 1-9 de Saaty).
"""


# Critérios do score ASG (ordem importa — é a mesma da matriz)
CRITERIOS_ASG = [
    "queimadas",
    "desmatamento_deter",
    "terras_indigenas",
    "terras_quilombolas",
    "desmatamento_prodes",
    "contexto_municipal",
]


# Matriz de comparação par a par (escala de Saaty 1-9)
#
# Leitura: elemento [i][j] = quantas vezes critério i é mais importante que j
#   1   = igual importância
#   3   = moderadamente mais importante
#   5   = fortemente mais importante
#   7   = muito fortemente mais importante
#   9   = extremamente mais importante
#   2,4,6,8 = valores intermediários
#
# Justificativa dos julgamentos:
# - Queimadas e DETER (eventos ativos/recentes) > TI (risco legal com geometria
#   FUNAI) > Quilombolas (risco legal análogo, mas dado municipal sem geometria) >
#   PRODES (histórico) > Contexto municipal (UCs, fator indireto)
# - Queimadas e DETER têm importância equivalente (peso 1 entre eles)
# - TI vs Quilombola = 2: TI tem polígono oficial e jurisprudência consolidada;
#   Quilombola hoje é só "comunidades certificadas no município" (sinal mais
#   fraco). Quando o banco incorporar geometrias do INCRA, revisar para 1.
#
#                    Q     D     T     QL    P     C
MATRIZ_COMPARACAO = [
    [1.0,  1.0,  2.0,  2.0,  1.0,  5.0],   # Queimadas
    [1.0,  1.0,  2.0,  2.0,  1.0,  5.0],   # DETER
    [0.5,  0.5,  1.0,  2.0,  1.0,  4.0],   # Terras Indígenas
    [0.5,  0.5,  0.5,  1.0,  0.5,  4.0],   # Quilombolas
    [1.0,  1.0,  1.0,  2.0,  1.0,  5.0],   # PRODES
    [0.2,  0.2,  0.25, 0.25, 0.2,  1.0],   # Contexto municipal
]


# Random Index (RI) para matrizes de tamanho n (tabela do Saaty)
RI_TABLE = {1: 0, 2: 0, 3: 0.58, 4: 0.9, 5: 1.12, 6: 1.24, 7: 1.32}


def calcular_pesos_ahp(matriz: list[list[float]]) -> list[float]:
    """Calcula pesos normalizados via método da média geométrica por linha.

    É uma aproximação do autovetor principal, adequada quando a matriz
    é consistente (CR < 0.10). Evita dependência de numpy.
    """
    n = len(matriz)
    # Média geométrica de cada linha
    medias_geom = []
    for i in range(n):
        produto = 1.0
        for j in range(n):
            produto *= matriz[i][j]
        medias_geom.append(produto ** (1.0 / n))

    # Normaliza para que a soma seja 1
    total = sum(medias_geom)
    return [m / total for m in medias_geom]


def calcular_lambda_max(matriz: list[list[float]], pesos: list[float]) -> float:
    """Calcula o autovalor principal λmax da matriz de comparação."""
    n = len(matriz)
    # Vetor Aw = matriz × pesos
    aw = []
    for i in range(n):
        soma = sum(matriz[i][j] * pesos[j] for j in range(n))
        aw.append(soma)
    # λmax = média de (Aw_i / w_i)
    return sum(aw[i] / pesos[i] for i in range(n)) / n


def calcular_consistencia(matriz: list[list[float]], pesos: list[float]) -> dict:
    """Calcula Razão de Consistência (CR) da matriz.

    CR < 0.10 indica matriz consistente (julgamentos coerentes).
    CR >= 0.10 indica inconsistência e a matriz deve ser revisada.
    """
    n = len(matriz)
    lambda_max = calcular_lambda_max(matriz, pesos)
    ci = (lambda_max - n) / (n - 1) if n > 1 else 0
    ri = RI_TABLE.get(n, 1.49)
    cr = ci / ri if ri > 0 else 0
    return {
        "lambda_max": round(lambda_max, 4),
        "ci": round(ci, 4),
        "ri": ri,
        "cr": round(cr, 4),
        "consistente": cr < 0.10,
    }


# Pesos pré-calculados da matriz ASG (evita recalcular a cada request)
PESOS_ASG = calcular_pesos_ahp(MATRIZ_COMPARACAO)
CONSISTENCIA_ASG = calcular_consistencia(MATRIZ_COMPARACAO, PESOS_ASG)


def obter_pesos_ahp() -> dict[str, float]:
    """Retorna dict {criterio: peso} com os pesos AHP pré-calculados."""
    return {CRITERIOS_ASG[i]: PESOS_ASG[i] for i in range(len(CRITERIOS_ASG))}


def obter_info_ahp() -> dict:
    """Retorna metadados completos do cálculo AHP para transparência na API."""
    pesos_dict = obter_pesos_ahp()
    return {
        "metodo": "AHP (Analytic Hierarchy Process)",
        "escala": "Saaty 1-9",
        "criterios": CRITERIOS_ASG,
        "pesos": {k: round(v, 4) for k, v in pesos_dict.items()},
        "pesos_percentual": {k: round(v * 100, 1) for k, v in pesos_dict.items()},
        "matriz_comparacao": [[round(v, 4) for v in linha] for linha in MATRIZ_COMPARACAO],
        "consistencia": CONSISTENCIA_ASG,
        "justificativa": (
            "Queimadas e DETER (eventos ativos) têm peso equivalente e maior, "
            "seguidos por Terras Indígenas (risco legal com geometria FUNAI), "
            "Terras Quilombolas (risco legal análogo, dado municipal Palmares), "
            "PRODES (histórico) e Contexto Municipal (UCs, fator indireto)."
        ),
    }

