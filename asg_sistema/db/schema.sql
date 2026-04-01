CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;

-- Rastreabilidade das fontes de dados
CREATE TABLE IF NOT EXISTS fontes (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(100) NOT NULL,
    descricao TEXT,
    url_origem TEXT,
    data_coleta TIMESTAMP,
    total_registros INTEGER,
    escopo VARCHAR(100) DEFAULT 'Estado de São Paulo'
);

-- Terras Indigenas (FUNAI)
CREATE TABLE IF NOT EXISTS terras_indigenas (
    id SERIAL PRIMARY KEY,
    fonte_id INTEGER REFERENCES fontes(id),
    codigo INTEGER,
    nome VARCHAR(200),
    etnia VARCHAR(300),
    municipio VARCHAR(200),
    uf VARCHAR(5),
    area_ha DOUBLE PRECISION,
    fase VARCHAR(100),
    modalidade VARCHAR(100),
    geom GEOMETRY(MultiPolygon, 4674)
);

CREATE INDEX IF NOT EXISTS idx_ti_geom ON terras_indigenas USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_ti_municipio ON terras_indigenas(municipio);

-- Focos de Queimadas (INPE)
CREATE TABLE IF NOT EXISTS queimadas (
    id SERIAL PRIMARY KEY,
    fonte_id INTEGER REFERENCES fontes(id),
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    data_hora TIMESTAMP,
    satelite VARCHAR(50),
    municipio VARCHAR(200),
    estado VARCHAR(100),
    bioma VARCHAR(100),
    frp DOUBLE PRECISION,
    risco_fogo DOUBLE PRECISION,
    precipitacao DOUBLE PRECISION,
    geom GEOMETRY(Point, 4674)
);

CREATE INDEX IF NOT EXISTS idx_queimadas_geom ON queimadas USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_queimadas_municipio ON queimadas(municipio);
CREATE INDEX IF NOT EXISTS idx_queimadas_data ON queimadas(data_hora);

-- Alertas de Desmatamento (DETER)
CREATE TABLE IF NOT EXISTS desmatamento_alertas (
    id SERIAL PRIMARY KEY,
    fonte_id INTEGER REFERENCES fontes(id),
    classe VARCHAR(100),
    municipio VARCHAR(200),
    uf VARCHAR(5),
    data_avistamento DATE,
    sensor VARCHAR(50),
    satelite VARCHAR(50),
    area_total_km2 DOUBLE PRECISION,
    area_uc_km2 DOUBLE PRECISION,
    nome_uc VARCHAR(300),
    geom GEOMETRY(MultiPolygon, 4674)
);

CREATE INDEX IF NOT EXISTS idx_demat_geom ON desmatamento_alertas USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_demat_municipio ON desmatamento_alertas(municipio);

-- Unidades de Conservacao (ICMBio/MMA)
CREATE TABLE IF NOT EXISTS unidades_conservacao (
    id SERIAL PRIMARY KEY,
    fonte_id INTEGER REFERENCES fontes(id),
    nome VARCHAR(300),
    categoria VARCHAR(200),
    grupo VARCHAR(100),
    esfera VARCHAR(50),
    uf VARCHAR(200),
    municipio TEXT,
    area_ha DOUBLE PRECISION,
    situacao VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_uc_municipio ON unidades_conservacao(municipio);

-- Desmatamento Anual PRODES (INPE/Mata Atlantica)
CREATE TABLE IF NOT EXISTS prodes_desmatamento (
    id SERIAL PRIMARY KEY,
    fonte_id INTEGER REFERENCES fontes(id),
    uid INTEGER,
    estado VARCHAR(5),
    classe_principal VARCHAR(50),
    classe_nome VARCHAR(50),
    data_imagem DATE,
    ano INTEGER,
    area_km DOUBLE PRECISION,
    fonte_bioma VARCHAR(100),
    satelite VARCHAR(50),
    sensor VARCHAR(20),
    geom GEOMETRY(MultiPolygon, 4674)
);

CREATE INDEX IF NOT EXISTS idx_prodes_geom ON prodes_desmatamento USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_prodes_ano ON prodes_desmatamento(ano);

-- Comunidades Quilombolas (Fundacao Cultural Palmares)
CREATE TABLE IF NOT EXISTS comunidades_quilombolas (
    id SERIAL PRIMARY KEY,
    fonte_id INTEGER REFERENCES fontes(id),
    municipio VARCHAR(200),
    uf VARCHAR(5),
    comunidade VARCHAR(300),
    codigo_ibge VARCHAR(20),
    processo_fcp VARCHAR(100),
    ano_certificacao INTEGER,
    processo_incra VARCHAR(100),
    regiao VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_quilombola_municipio ON comunidades_quilombolas(municipio);

-- SICAR - Cadastro Ambiental Rural (SP)
CREATE TABLE IF NOT EXISTS sicar_imoveis (
    id SERIAL PRIMARY KEY,
    fonte_id INTEGER REFERENCES fontes(id),
    cod_imovel VARCHAR(254),
    cod_tema VARCHAR(254),
    nom_tema VARCHAR(254),
    ind_status VARCHAR(10),
    ind_tipo VARCHAR(10),
    des_condic VARCHAR(254),
    municipio VARCHAR(254),
    cod_estado VARCHAR(5),
    num_area DOUBLE PRECISION,
    mod_fiscal DOUBLE PRECISION,
    dat_criacao VARCHAR(20),
    dat_atualizacao VARCHAR(20),
    geom GEOMETRY(Geometry, 4674)
);

CREATE INDEX IF NOT EXISTS idx_sicar_geom ON sicar_imoveis USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_sicar_municipio ON sicar_imoveis(municipio);
CREATE INDEX IF NOT EXISTS idx_sicar_cod_imovel ON sicar_imoveis(cod_imovel);
CREATE INDEX IF NOT EXISTS idx_sicar_status ON sicar_imoveis(ind_status);

-- Corpus textualizado + embeddings para busca semantica
CREATE TABLE IF NOT EXISTS corpus_asg (
    id SERIAL PRIMARY KEY,
    fonte VARCHAR(100) NOT NULL,
    tipo_registro VARCHAR(100),
    municipio TEXT,
    data_referencia DATE,
    texto TEXT NOT NULL,
    texto_preprocessado TEXT,
    registro_id INTEGER,
    embedding vector(384),
    metadados_json JSONB
);

CREATE INDEX IF NOT EXISTS idx_corpus_fonte ON corpus_asg(fonte);
CREATE INDEX IF NOT EXISTS idx_corpus_municipio ON corpus_asg(municipio);
CREATE INDEX IF NOT EXISTS idx_corpus_data ON corpus_asg(data_referencia);
