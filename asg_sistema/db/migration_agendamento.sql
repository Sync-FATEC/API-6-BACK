-- Migration: cria tabela de agendamentos de atualização da base ASG
-- Executar após o schema.sql existente

CREATE TABLE IF NOT EXISTS agendamentos_atualizacao (
    id                  SERIAL PRIMARY KEY,

    -- Recorrência em linguagem simples
    intervalo           INTEGER NOT NULL,               -- ex: 1, 2, 3
    unidade             VARCHAR(10) NOT NULL,           -- 'hora' | 'dia' | 'semana' | 'mes'
    horario             VARCHAR(5) NOT NULL DEFAULT '02:00',  -- 'HH:MM'

    -- Expressão cron derivada automaticamente
    cron_expressao      VARCHAR(100) NOT NULL,

    ativo               BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em           TIMESTAMP DEFAULT NOW(),
    atualizado_em       TIMESTAMP DEFAULT NOW(),
    ultima_execucao_em  TIMESTAMP,
    ultimo_status       VARCHAR(20),                    -- 'sucesso' | 'erro' | 'executando'
    ultima_mensagem     TEXT
);