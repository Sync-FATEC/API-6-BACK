-- Role somente-leitura para execução de SQL gerado pelo caminho analítico.
-- Troque a senha antes de aplicar. O database padrão é asg_sp (ver config.db_nome).

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'asg_readonly') THEN
    CREATE ROLE asg_readonly LOGIN PASSWORD 'troque_esta_senha';
  END IF;
END $$;

GRANT CONNECT ON DATABASE asg_sp TO asg_readonly;
GRANT USAGE ON SCHEMA public TO asg_readonly;

-- SELECT apenas nas tabelas/views consultáveis
-- (NUNCA usuarios/conversas/mensagens/corpus_asg).
GRANT SELECT ON
  queimadas, desmatamento_alertas, prodes_desmatamento, sicar_imoveis,
  terras_indigenas, unidades_conservacao, comunidades_quilombolas, fontes,
  vw_desmatamento_municipio, vw_queimadas_municipio, vw_prodes_ano
TO asg_readonly;

-- Defesa em profundidade: o role nunca escreve e tem timeout.
ALTER ROLE asg_readonly SET default_transaction_read_only = on;
ALTER ROLE asg_readonly SET statement_timeout = '5s';
