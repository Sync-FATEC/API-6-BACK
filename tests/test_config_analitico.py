"""Config do caminho analítico: campos novos com defaults seguros."""

import os

os.environ.setdefault("ASG_JWT_SEGREDO", "test-secret")

from asg_sistema.config import Configuracao


class TestConfigAnalitico:
    def test_defaults(self):
        cfg = Configuracao()
        # modelo_spacy é controlado por .env; o caminho analítico usa MiniLM (linker)
        # e regex (slots), então não depende de vetores spaCy.
        assert isinstance(cfg.modelo_spacy, str)
        assert cfg.sql_timeout_ms == 5000
        assert cfg.sql_max_limit == 100
        assert cfg.analitico_confianca_minima == 0.35
        assert cfg.gerador_local_ativo is False           # OFF por padrão
        assert cfg.usuario_ro == cfg.db_usuario           # cai p/ credencial principal

    def test_db_url_readonly(self):
        cfg = Configuracao(db_usuario_ro="asg_readonly", db_senha_ro="ro")
        assert "asg_readonly:ro@" in cfg.db_url_readonly
        assert cfg.db_url_readonly.startswith("postgresql://")
