"""Testes da camada de normalizacao da pergunta.

Regras cobertas:
1. Apelidos de municipio sao expandidos (caragua -> Caraguatatuba).
2. Typos comuns sao corrigidos (situasao -> situação).
3. Texto sem alteracoes passa intacto.
4. Maiusculas/minusculas e acentos sao tratados consistentemente.
"""

from asg_sistema.motor.normalizacao import normalizar_pergunta


class TestApelidosMunicipio:
    def test_deve_expandir_caragua_para_caraguatatuba(self):
        assert "Caraguatatuba" in normalizar_pergunta("situasao em caragua")

    def test_deve_expandir_sjc_para_sao_jose_dos_campos(self):
        assert "São José dos Campos" in normalizar_pergunta("queimadas em SJC")

    def test_deve_ser_case_insensitive_no_apelido(self):
        assert "Caraguatatuba" in normalizar_pergunta("dados de CARAGUA")

    def test_deve_so_substituir_palavras_inteiras_quando_apelido_curto(self):
        # "abc" nao deve transformar "fabrica" em "fSanto Andréica"
        out = normalizar_pergunta("fabrica de abc em sp")
        assert "fabrica" in out
        assert "Santo André" in out


class TestTypos:
    def test_deve_corrigir_situasao_para_situacao_com_acento(self):
        assert "situação" in normalizar_pergunta("situasao em ubatuba")

    def test_deve_corrigir_situacao_sem_acento(self):
        assert "situação" in normalizar_pergunta("situacao de campinas")

    def test_deve_corrigir_imovel_para_imovel_com_acento(self):
        assert "imóvel" in normalizar_pergunta("imovel rural em campinas")

    def test_deve_corrigir_conservacao_sem_acento(self):
        assert "conservação" in normalizar_pergunta("unidades de conservacao em sp")


class TestFuzzyMatching:
    def test_deve_corrigir_typo_com_letra_faltando(self):
        # "situsao" tem 1 letra a menos que "situacao"
        assert "situação" in normalizar_pergunta("situsao em ubatuba")

    def test_deve_corrigir_typo_com_letras_trocadas(self):
        # "queimasas" (s no lugar de d) -> queimadas
        assert "queimadas" in normalizar_pergunta("quantas queimasas teve")

    def test_deve_corrigir_imoveis_sem_acento_via_fuzzy(self):
        assert "imóveis" in normalizar_pergunta("imoveis em sp")

    def test_deve_nao_corrigir_palavras_muito_curtas(self):
        # Palavras < 5 chars nao passam pelo fuzzy (evita falsos positivos)
        out = normalizar_pergunta("sim em sp")
        assert out == "sim em sp"

    def test_deve_nao_corrigir_palavras_sem_match_proximo(self):
        out = normalizar_pergunta("brasileiro feliz aqui")
        assert "brasileiro" in out
        assert "feliz" in out


class TestPreservacao:
    def test_deve_manter_texto_quando_nao_ha_match(self):
        original = "qual o panorama atual?"
        # "panorama" eh mapeado, entao o resto deve ficar
        out = normalizar_pergunta(original)
        assert out != ""
        assert "atual" in out

    def test_deve_retornar_string_vazia_quando_entrada_vazia(self):
        assert normalizar_pergunta("") == ""

    def test_deve_tolerar_pergunta_apenas_com_codigo_car(self):
        out = normalizar_pergunta("SP-3501301-380B209ED7C14AF594ABA61225399956")
        assert "SP-3501301-380B209ED7C14AF594ABA61225399956" in out
