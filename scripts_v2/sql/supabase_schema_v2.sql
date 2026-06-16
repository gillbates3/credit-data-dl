-- ============================================================
-- credit-data-dl — Schema Supabase V2
-- DROP completo + recriação. Execute no SQL Editor do Supabase.
-- ============================================================

-- ── 1. DROP (ordem inversa de dependências FK) ──────────────

DROP VIEW  IF EXISTS v_jobs_recentes               CASCADE;
DROP VIEW  IF EXISTS v_emissor_debentures          CASCADE;
DROP VIEW  IF EXISTS v_ultima_analise_credito      CASCADE;
DROP VIEW  IF EXISTS v_proximos_pagamentos         CASCADE;
DROP VIEW  IF EXISTS v_portfolio_ativo             CASCADE;
DROP VIEW  IF EXISTS v_ultimo_periodo              CASCADE;

DROP TABLE IF EXISTS pipeline_jobs                  CASCADE;
DROP TABLE IF EXISTS emissor_analise_credito       CASCADE;
DROP TABLE IF EXISTS emissor_compendio_qualitativo  CASCADE;
DROP TABLE IF EXISTS emissor_compendio_quantitativo CASCADE;
DROP TABLE IF EXISTS doc_chunks_qualitativo         CASCADE;  -- descartada no V2
DROP TABLE IF EXISTS deb_historico_diario           CASCADE;
DROP TABLE IF EXISTS deb_agenda                     CASCADE;
DROP TABLE IF EXISTS demonstracoes_financeiras      CASCADE;
DROP TABLE IF EXISTS deb_caracteristicas            CASCADE;
DROP TABLE IF EXISTS emissores                      CASCADE;

DROP FUNCTION IF EXISTS set_atualizado_em() CASCADE;

-- ── 2. FUNÇÃO UTILITÁRIA ────────────────────────────────────

CREATE FUNCTION set_atualizado_em()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.atualizado_em = now();
    RETURN NEW;
END;
$$;

-- ── 3. emissores ─────────────────────────────────────────────

CREATE TABLE public.emissores (
    cnpj            text PRIMARY KEY,
    cod_cvm         text,
    nome            text NOT NULL,
    categoria_cvm   text,           -- A | B
    tipo_capital    text,           -- Aberto | Fechado  [novo V2]
    ticker_acao     text,
    grupo_economico text,           -- preenchido manualmente
    setor           text,
    observacao      text,
    criado_em       timestamptz DEFAULT now(),
    atualizado_em   timestamptz DEFAULT now()
);

COMMENT ON TABLE public.emissores IS
    'Cadastro central de empresas monitoradas. '
    'tipo_capital distingue S/A Aberta (CVM ativa) de S/A Fechada. '
    'grupo_economico é o único campo preenchido manualmente.';

CREATE INDEX idx_emissores_grupo ON public.emissores (grupo_economico);

CREATE TRIGGER trg_emissores_atualizado
    BEFORE UPDATE ON public.emissores
    FOR EACH ROW EXECUTE FUNCTION set_atualizado_em();

-- ── 4. demonstracoes_financeiras ─────────────────────────────

CREATE TABLE public.demonstracoes_financeiras (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cnpj         text NOT NULL REFERENCES public.emissores(cnpj),
    data_ref     date NOT NULL,
    tipo_doc     text NOT NULL,     -- DFP | ITR
    demonstracao text NOT NULL,     -- BPA | BPP | DRE | DFC | DVA
    cd_conta     text NOT NULL,
    ds_conta     text,
    valor        numeric,
    criado_em    timestamptz DEFAULT now(),

    CONSTRAINT uq_demonstracoes UNIQUE (cnpj, data_ref, tipo_doc, demonstracao, cd_conta)
);

COMMENT ON TABLE public.demonstracoes_financeiras IS
    'Dados financeiros estruturados — uma linha por conta por período. '
    'Populado por servico_cvm.py e servico_ia_quantitativa.py.';

CREATE INDEX idx_dem_cnpj_data    ON public.demonstracoes_financeiras (cnpj, data_ref DESC);
CREATE INDEX idx_dem_demonstracao ON public.demonstracoes_financeiras (demonstracao, cd_conta);

-- ── 5. deb_caracteristicas ───────────────────────────────────

CREATE TABLE public.deb_caracteristicas (
    id                      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cnpj                    text NOT NULL REFERENCES public.emissores(cnpj),
    ticker_deb              text UNIQUE NOT NULL,
    nome_emissor            text,
    tipo                    text,           -- debenture | ccb | cri | cra | outros
    serie                   text,
    numero_emissao          integer,

    data_emissao            date,
    data_vencimento         date,
    data_primeiro_pagamento date,
    prazo_anos              numeric,

    volume_emissao          numeric,
    valor_unitario_emissao  numeric,
    quantidade_debentures   integer,

    indexador               text,           -- IPCA | CDI | IGPM | prefixado
    spread_emissao          numeric,
    taxa_prefixada          numeric,
    periodicidade_juros     text,
    periodicidade_amort     text,

    especie                 text,
    garantias               text,
    garantidores            text,
    lei_incentivo           text,

    banco_coordenador       text,
    banco_estruturador      text,
    agente_fiduciario       text,
    banco_liquidante        text,

    rating_emissao          text,
    agencia_rating          text,
    data_ultimo_rating      date,
    perspectiva_rating      text,

    status                  text DEFAULT 'ativo',   -- ativo | resgatado | vencido | default
    isin                    text UNIQUE,
    codigo_cetip            text,

    dados_anbima            jsonb,          -- payload ANBIMA completo

    criado_em               timestamptz DEFAULT now(),
    atualizado_em           timestamptz DEFAULT now()
);

COMMENT ON TABLE public.deb_caracteristicas IS
    'Uma linha por série de debênture/instrumento. '
    'Populado via scraping ANBIMA pelo servico_mercado.py.';

CREATE INDEX idx_op_cnpj       ON public.deb_caracteristicas (cnpj);
CREATE INDEX idx_op_vencimento ON public.deb_caracteristicas (data_vencimento);
CREATE INDEX idx_op_indexador  ON public.deb_caracteristicas (indexador);
CREATE INDEX idx_op_status     ON public.deb_caracteristicas (status);

CREATE TRIGGER trg_deb_caracteristicas_atualizado
    BEFORE UPDATE ON public.deb_caracteristicas
    FOR EACH ROW EXECUTE FUNCTION set_atualizado_em();

-- ── 6. deb_agenda ────────────────────────────────────────────

CREATE TABLE public.deb_agenda (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticker_deb      text NOT NULL REFERENCES public.deb_caracteristicas(ticker_deb),
    cnpj            text NOT NULL REFERENCES public.emissores(cnpj),

    data_evento     date NOT NULL,
    data_liquidacao date,
    data_base       date,

    evento          text NOT NULL,   -- "PAGAMENTO DE JUROS" | "AMORTIZACAO" | "VENCIMENTO (RESGATE)"
    evento_arc      text,            -- "Juros" | "Amortização"

    taxa            numeric,
    valor           numeric,

    status          text,            -- "Previsto" | "Liquidado"
    grupo_status    text,

    criado_em       timestamptz DEFAULT now(),

    -- NULLS NOT DISTINCT: dois NULL em data_base são tratados como iguais
    CONSTRAINT uq_agenda UNIQUE NULLS NOT DISTINCT (ticker_deb, data_evento, evento, data_base)
);

COMMENT ON TABLE public.deb_agenda IS
    'Fluxo de eventos de cada debênture — juros, amortizações e resgates. '
    'Populado via scraping ANBIMA pelo servico_mercado.py.';

CREATE INDEX idx_agenda_data   ON public.deb_agenda (data_evento);
CREATE INDEX idx_agenda_ticker ON public.deb_agenda (ticker_deb, data_evento);
CREATE INDEX idx_agenda_status ON public.deb_agenda (status, data_evento);

-- ── 7. deb_historico_diario ──────────────────────────────────

CREATE TABLE public.deb_historico_diario (
    id                       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticker_deb               text NOT NULL REFERENCES public.deb_caracteristicas(ticker_deb),
    data_referencia          date NOT NULL,

    -- Valores teóricos / curva do papel
    pu_par                   numeric,
    vna                      numeric,
    juros                    numeric,
    prazo_remanescente       integer,

    -- Marcação a mercado (indicativos ANBIMA)
    pu_indicativo            numeric,
    taxa_indicativa          numeric,
    taxa_compra              numeric,
    taxa_venda               numeric,
    duration_dias_uteis      numeric,
    desvio_padrao            numeric,
    percentual_pu_par        numeric,
    percentual_vne           numeric,
    intervalo_indicativo_min numeric,
    intervalo_indicativo_max numeric,
    referencia_ntnb          text,
    spread_indicativo        numeric,

    -- Dados de negociação secundária
    volume_financeiro        numeric,
    quantidade_negocios      integer,
    quantidade_titulos       integer,
    taxa_media_negocios      numeric,
    pu_medio_negocios        numeric,

    -- Metadados ANBIMA
    reune                    text,
    percentual_reune         numeric,
    pu_indicativo_status     text,
    taxa_indicativa_status   text,
    flag_status              text,
    data_ultima_atualizacao  date,
    criado_em                timestamptz DEFAULT now(),

    CONSTRAINT uq_historico_diario UNIQUE (ticker_deb, data_referencia)
);

COMMENT ON TABLE public.deb_historico_diario IS
    'Série temporal de marcação a mercado e negociação por debênture. '
    'Populado por servico_mercado.py no modo deep.';

CREATE INDEX idx_hist_ticker_data ON public.deb_historico_diario (ticker_deb, data_referencia DESC);

-- ── 8. emissor_compendio_qualitativo  [novo V2] ──────────────

CREATE TABLE public.emissor_compendio_qualitativo (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cnpj              text NOT NULL REFERENCES public.emissores(cnpj),
    nome_arquivo      text NOT NULL,
    hash_md5          text NOT NULL,
    markdown_conteudo text NOT NULL,
    criado_em         timestamptz DEFAULT now(),

    CONSTRAINT uq_qualitativo_cnpj_hash UNIQUE (cnpj, hash_md5)
);

COMMENT ON TABLE public.emissor_compendio_qualitativo IS
    'Uma linha por PDF qualitativo processado por emissor. '
    'hash_md5 do arquivo original é a chave de idempotência (Peek Before Leap). '
    'Upsert padrão: ON CONFLICT DO NOTHING. '
    'force_reprocess: ON CONFLICT DO UPDATE SET markdown_conteudo = EXCLUDED.markdown_conteudo.';

CREATE INDEX idx_qual_cnpj ON public.emissor_compendio_qualitativo (cnpj);

-- ── 9. emissor_compendio_quantitativo  [novo V2] ─────────────

CREATE TABLE public.emissor_compendio_quantitativo (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cnpj         text NOT NULL REFERENCES public.emissores(cnpj),
    nome_arquivo text NOT NULL,
    hash_md5     text NOT NULL,
    criado_em    timestamptz DEFAULT now(),

    CONSTRAINT uq_quantitativo_cnpj_hash UNIQUE (cnpj, hash_md5)
);

COMMENT ON TABLE public.emissor_compendio_quantitativo IS
    'Manifesto dos PDFs quantitativos processados por emissor. '
    'Os dados financeiros resultantes ficam em demonstracoes_financeiras. '
    'hash_md5 é a chave de idempotência (Peek Before Leap).';

CREATE INDEX idx_quant_cnpj ON public.emissor_compendio_quantitativo (cnpj);

-- ── 10. emissor_analise_credito  [novo V2] ───────────────────

CREATE TABLE public.emissor_analise_credito (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cnpj             text NOT NULL REFERENCES public.emissores(cnpj),
    analise_markdown text NOT NULL,
    delta_markdown   text,       -- NULL na primeira análise; preenchido nas subsequentes
    metadados        jsonb,      -- modelo, versão, debentures do emissor no momento da geração, etc.
    criado_em        timestamptz DEFAULT now()
    -- Sem UNIQUE: insert-only para preservar histórico completo de versões
);

COMMENT ON TABLE public.emissor_analise_credito IS
    'Análises de crédito geradas pelo servico_analise_credito.py (Passo 6). '
    'Granularidade: emissor (CNPJ), não debênture. '
    'Insert-only: nunca atualiza — cada geração cria uma nova linha. '
    'delta_markdown NULL indica primeira análise do emissor. '
    'Debentures do emissor no momento da geração ficam em metadados.tickers_deb.';

CREATE INDEX idx_analise_cnpj ON public.emissor_analise_credito (cnpj, criado_em DESC);

-- ── 10b. pipeline_jobs  [novo V2 — fila + status para o front] ─

CREATE TABLE public.pipeline_jobs (
    id            text PRIMARY KEY,          -- UUID gerado na aplicação (portável: NÃO usa gen_random_uuid())
    tipo          text NOT NULL,             -- ingestao | analise
    alvo          text NOT NULL,             -- ticker (ingestao) ou cnpj (analise)
    status        text NOT NULL DEFAULT 'pendente',  -- pendente | rodando | concluido | concluido_com_erros | erro
    etapa_atual   text,                      -- identidade | cvm | mercado | ia_quant | ia_qual | persistencia | analise
    progresso     jsonb,                     -- {passos_concluidos:[...], novos_qualitativos:N, novos_periodos:N}
    erro          text,
    criado_em     timestamptz DEFAULT now(),
    atualizado_em timestamptz DEFAULT now()
);

COMMENT ON TABLE public.pipeline_jobs IS
    'Fila + status dos disparos de pipeline para o front (polling). '
    'id é UUID gerado na aplicação para não amarrar a geração de ID ao banco. '
    'tipo=ingestao roda P1..P5; tipo=analise roda o Passo 6. '
    'status: pendente | rodando | concluido | concluido_com_erros | erro. '
    'O orquestrador atualiza etapa_atual a cada passo concluído.';

CREATE INDEX idx_jobs_status ON public.pipeline_jobs (status, criado_em DESC);
CREATE INDEX idx_jobs_alvo   ON public.pipeline_jobs (alvo, criado_em DESC);

CREATE TRIGGER trg_jobs_atualizado
    BEFORE UPDATE ON public.pipeline_jobs
    FOR EACH ROW EXECUTE FUNCTION set_atualizado_em();

-- ── 11. VIEWS ────────────────────────────────────────────────

CREATE VIEW v_ultimo_periodo AS
SELECT DISTINCT ON (cnpj)
    cnpj, data_ref, tipo_doc
FROM public.demonstracoes_financeiras
ORDER BY cnpj, data_ref DESC;

COMMENT ON VIEW v_ultimo_periodo IS
    'Último período financeiro disponível por emissor.';


CREATE VIEW v_portfolio_ativo AS
SELECT
    o.ticker_deb,
    o.nome_emissor,
    e.grupo_economico,
    e.setor,
    e.tipo_capital,
    o.tipo,
    o.data_emissao,
    o.data_vencimento,
    o.volume_emissao,
    o.indexador,
    o.spread_emissao,
    o.especie,
    o.rating_emissao,
    o.agencia_rating,
    o.perspectiva_rating,
    o.lei_incentivo,
    o.agente_fiduciario,
    o.status
FROM public.deb_caracteristicas o
JOIN public.emissores e ON e.cnpj = o.cnpj
WHERE o.status = 'ativo'
ORDER BY o.data_vencimento;

COMMENT ON VIEW v_portfolio_ativo IS
    'Portfólio de operações ativas com dados do emissor — visão principal do sistema.';


CREATE VIEW v_proximos_pagamentos AS
SELECT
    a.data_evento,
    a.ticker_deb,
    em.nome             AS emissor,
    em.grupo_economico,
    a.evento,
    a.evento_arc,
    a.taxa,
    a.valor,
    a.status,
    (a.data_evento - current_date) AS dias_para_evento
FROM public.deb_agenda a
JOIN public.deb_caracteristicas o  ON o.ticker_deb = a.ticker_deb
JOIN public.emissores em            ON em.cnpj = o.cnpj
WHERE a.data_evento >= current_date
  AND a.status = 'Previsto'
ORDER BY a.data_evento;

COMMENT ON VIEW v_proximos_pagamentos IS
    'Próximos eventos de pagamento de todas as debêntures monitoradas.';


CREATE VIEW v_ultima_analise_credito AS
SELECT DISTINCT ON (cnpj)
    id,
    cnpj,
    analise_markdown,
    delta_markdown,
    metadados,
    criado_em
FROM public.emissor_analise_credito
ORDER BY cnpj, criado_em DESC;

COMMENT ON VIEW v_ultima_analise_credito IS
    'Versão mais recente da análise de crédito por emissor (CNPJ).';


CREATE VIEW v_emissor_debentures AS
SELECT
    e.cnpj,
    e.nome,
    e.grupo_economico,
    e.tipo_capital,
    d.ticker_deb,
    d.status,
    d.indexador,
    d.spread_emissao,
    d.data_vencimento,
    d.rating_emissao,
    d.agencia_rating,
    d.lei_incentivo
FROM public.emissores e
JOIN public.deb_caracteristicas d ON d.cnpj = e.cnpj
ORDER BY e.nome, d.data_vencimento;

COMMENT ON VIEW v_emissor_debentures IS
    'Mapeamento emissor → debêntures. Substitui a necessidade de uma tabela de junção '
    'separada — a FK cnpj em deb_caracteristicas já é a fonte de verdade do vínculo.';


CREATE VIEW v_jobs_recentes AS
SELECT
    id, tipo, alvo, status, etapa_atual, progresso, erro,
    criado_em, atualizado_em
FROM public.pipeline_jobs
ORDER BY criado_em DESC
LIMIT 100;

COMMENT ON VIEW v_jobs_recentes IS
    'Últimos 100 jobs para o painel de acompanhamento do front (polling).';
