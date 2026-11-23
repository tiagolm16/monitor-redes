-- Executado uma unica vez, na criacao do volume do Postgres.
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- Usuario somente de monitoramento: o papel pg_monitor le as views de estatistica sem ser superusuario
CREATE ROLE monitor LOGIN PASSWORD 'monitor' IN ROLE pg_monitor;

-- Tabela usada pelo loadgen para gerar leitura e escrita
CREATE TABLE pedidos (
    id        SERIAL PRIMARY KEY,
    cliente   TEXT NOT NULL,
    valor     NUMERIC(10,2) NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO pedidos (cliente, valor)
SELECT 'cliente' || (i % 50), (random() * 500)::numeric(10,2)
FROM generate_series(1, 1000) AS i;
