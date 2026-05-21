"""Testes do extrator de municipios.

Regras cobertas:
1. Match exato de municipio.
2. Match por substring (nome do municipio contido no texto).
3. Fuzzy match para typos (sorocab -> Sorocaba).
4. Acentos sao normalizados.
5. Tokens muito curtos nao disparam fuzzy.
6. Multiplos municipios no mesmo texto.
"""

from asg_sistema.motor.entidades import ExtratorEntidades


# --------------------------------------------------------------------------
# Builder
# --------------------------------------------------------------------------

def um_extrator(municipios: list[str] | None = None) -> ExtratorEntidades:
    return ExtratorEntidades(municipios or [
        "Campinas",
        "Sorocaba",
        "Ubatuba",
        "Caraguatatuba",
        "São José dos Campos",
        "Ribeirão Preto",
    ])


def _municipios(texto: str, ext: ExtratorEntidades | None = None) -> list[str]:
    return (ext or um_extrator()).extrair(texto).get("municipios") or []


# --------------------------------------------------------------------------
# Match exato e por substring
# --------------------------------------------------------------------------

class TestMatchSubstring:
    def test_deve_encontrar_municipio_quando_nome_aparece_literalmente(self):
        assert "Sorocaba" in _municipios("queimadas em sorocaba")

    def test_deve_normalizar_acentos_quando_usuario_escreve_sem(self):
        assert "São José dos Campos" in _municipios("imoveis em sao jose dos campos")

    def test_deve_ser_case_insensitive(self):
        assert "Campinas" in _municipios("SITUAÇÃO EM CAMPINAS")


# --------------------------------------------------------------------------
# Fuzzy match
# --------------------------------------------------------------------------

class TestFuzzyMunicipio:
    def test_deve_encontrar_sorocaba_quando_usuario_escreve_sorocab(self):
        assert "Sorocaba" in _municipios("queimadas em sorocab")

    def test_deve_encontrar_caraguatatuba_quando_usuario_escreve_caraguatuba(self):
        assert "Caraguatatuba" in _municipios("situacao em caraguatuba")

    def test_deve_ignorar_token_muito_curto_para_evitar_falso_positivo(self):
        # "sim" tem 3 chars — nao passa pelo fuzzy
        assert _municipios("sim em sp") == []

    def test_deve_nao_corrigir_quando_palavra_eh_muito_diferente(self):
        # "brasileiro" nao deve virar nenhum municipio
        assert _municipios("brasileiro feliz") == []


# --------------------------------------------------------------------------
# Multiplos municipios
# --------------------------------------------------------------------------

class TestMultiplosMunicipios:
    def test_deve_encontrar_dois_municipios_no_mesmo_texto(self):
        result = _municipios("queimadas em campinas e sorocaba")
        assert "Campinas" in result
        assert "Sorocaba" in result

    def test_deve_nao_duplicar_quando_municipio_aparece_duas_vezes(self):
        result = _municipios("campinas e campinas de novo")
        assert result.count("Campinas") == 1

    def test_deve_combinar_substring_e_fuzzy_quando_um_dos_municipios_tem_typo(self):
        # Caso real: usuario escreveu "sorocab" (typo) ao lado de "campinas".
        # Substring acha Campinas; fuzzy precisa achar Sorocaba mesmo apos substring.
        result = _municipios("queimadas e desmatamento em campinas e sorocab")
        assert "Campinas" in result
        assert "Sorocaba" in result
