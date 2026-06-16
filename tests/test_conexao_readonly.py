"""executar_consulta_readonly: aplica timeout, força read-only e faz rollback (sem DB)."""

import os

os.environ.setdefault("ASG_JWT_SEGREDO", "test-secret")

import asg_sistema.db.conexao as conexao


class _Res:
    def keys(self):
        return ["municipio", "total"]

    def fetchall(self):
        return [("Bauru", 3)]


class _Trans:
    def __init__(self, log):
        self.log = log

    def rollback(self):
        self.log.append("ROLLBACK")

    def commit(self):
        self.log.append("COMMIT")


class _Conn:
    def __init__(self, log):
        self.log = log

    def execute(self, stmt, params=None):
        self.log.append(str(stmt))
        return _Res()

    def begin(self):
        self.log.append("BEGIN")
        return _Trans(self.log)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Engine:
    def __init__(self, log):
        self.log = log

    def connect(self):
        return _Conn(self.log)


class TestReadonly:
    def test_retorna_dicts(self, monkeypatch):
        log = []
        monkeypatch.setattr(conexao, "_ro_engine", _Engine(log))
        linhas = conexao.executar_consulta_readonly(
            "SELECT municipio, COUNT(*) total FROM queimadas GROUP BY municipio"
        )
        assert linhas == [{"municipio": "Bauru", "total": 3}]

    def test_timeout_readonly_rollback(self, monkeypatch):
        log = []
        monkeypatch.setattr(conexao, "_ro_engine", _Engine(log))
        conexao.executar_consulta_readonly("SELECT 1", timeout_ms=7000)
        j = " | ".join(log)
        assert "statement_timeout = 7000" in j
        assert "TRANSACTION READ ONLY" in j
        assert "ROLLBACK" in j and "COMMIT" not in j

    def test_explain_ok_e_erro(self, monkeypatch):
        log = []
        monkeypatch.setattr(conexao, "_ro_engine", _Engine(log))
        assert conexao.explain_readonly("SELECT 1") is None
