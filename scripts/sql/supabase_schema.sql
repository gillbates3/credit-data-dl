-- ============================================================
-- credit-data-dl — Schema Supabase (versão final)
-- Execute no SQL Editor do seu projeto Supabase
-- ============================================================

-- Extensão vetorial para doc_chunks_qualitativo
create extension if not exists vector;

-- ── Tabela: emissores ─────────────────────────────────────────
create table if not exists emissores (
    cnpj                text primary key,
    cod_cvm             text,
    nome                text not null,
    categoria_cvm       text,           -- A | B
    ticker_acao         text,
    -- Grupo econômico: preenchido manualmente uma vez por emissor
    -- Ex: "Aegea", "BRK Ambiental", "Iguá", "Rialma"
    grupo_economico     text,
    setor               text,           -- saneamento | energia | telecom | rodovias | portos
    observacao          text,
    criado_em           timestamptz default now(),
    atualizado_em       timestamptz default now()
);

comment on table emissores is
    'Cadastro central de empresas monitoradas (abertas e fechadas). '
    'grupo_economico é o único campo preenchido manualmente.';

create index if not exists idx_emissores_grupo
    on emissores (grupo_economico);

-- ── Tabela: demonstracoes_financeiras ──────────────────────────────
create table if not exists demonstracoes_financeiras (
    id              bigserial primary key,
    cnpj            text not null references emissores(cnpj),
    data_ref        date not null,
    tipo_doc        text not null,      -- DFP | ITR
    demonstracao    text not null,      -- BPA | BPP | DRE | DFC | DVA
    cd_conta        text not null,
    ds_conta        text,
    valor           numeric,
    criado_em       timestamptz default now(),

    unique (cnpj, data_ref, tipo_doc, demonstracao, cd_conta)
);

comment on table demonstracoes_financeiras is
    'Dados financeiros estruturados — uma linha por conta por período. '
    'Populado automaticamente pelo script 04_parser_silver + 06_upsert_supabase.';

create index if not exists idx_dem_cnpj_data
    on demonstracoes_financeiras (cnpj, data_ref desc);
create index if not exists idx_dem_demonstracao
    on demonstracoes_financeiras (demonstracao, cd_conta);

-- ── Tabela: deb_caracteristicas ─────────────────────────────────────────
create table if not exists deb_caracteristicas (
    id                      bigserial primary key,

    -- Identificação
    cnpj                    text not null references emissores(cnpj),
    ticker_deb              text unique not null,
    nome_emissor            text,           -- cache para queries rápidas
    tipo                    text,           -- debenture | ccb | cri | cra | outros
    serie                   text,           -- "1ª série", "2ª série"
    numero_emissao          integer,

    -- Datas
    data_emissao            date,
    data_vencimento         date,
    data_primeiro_pagamento date,
    prazo_anos              numeric,

    -- Volume
    volume_emissao          numeric,        -- R$ total da série
    valor_unitario_emissao  numeric,        -- PU na emissão
    quantidade_debentures   integer,

    -- Remuneração
    indexador               text,           -- IPCA | CDI | IGPM | prefixado
    spread_emissao          numeric,        -- % a.a.
    taxa_prefixada          numeric,        -- se prefixado
    periodicidade_juros     text,           -- semestral | anual | mensal
    periodicidade_amort     text,           -- bullet | semestral | anual

    -- Estrutura e garantias
    especie                 text,           -- quirografaria | com garantia real | subordinada
    garantias               text,           -- descrição: alienação fiduciária de ações, etc.
    garantidores            text,           -- fiadores / avalistas
    lei_incentivo           text,           -- Lei 12.431 | Lei 14.801 | não incentivada

    -- Partes
    banco_coordenador       text,
    banco_estruturador      text,
    agente_fiduciario       text,
    banco_liquidante        text,

    -- Rating (último)
    rating_emissao          text,           -- ex: AAA(bra), brAA+
    agencia_rating          text,           -- Fitch | S&P | Moody's
    data_ultimo_rating      date,
    perspectiva_rating      text,           -- estável | positiva | negativa | em revisão

    -- Status e identificadores
    status                  text default 'ativo',   -- ativo | resgatado | vencido | default
    isin                    text unique,
    codigo_cetip            text,

    -- Payload ANBIMA completo (fonte primária de preenchimento automático)
    dados_anbima            jsonb,

    criado_em               timestamptz default now(),
    atualizado_em           timestamptz default now()
);

comment on table deb_caracteristicas is
    'Uma linha por série de debênture/instrumento. '
    'Campos populados automaticamente via ANBIMA Data + parser de escrituras (Skill 1). '
    'grupo_economico fica em emissores, não aqui.';

create index if not exists idx_op_cnpj       on deb_caracteristicas (cnpj);
create index if not exists idx_op_vencimento on deb_caracteristicas (data_vencimento);
create index if not exists idx_op_indexador  on deb_caracteristicas (indexador);
create index if not exists idx_op_status     on deb_caracteristicas (status);

-- ── Tabela: doc_chunks_qualitativo ────────────────────────────────────────
create table if not exists doc_chunks_qualitativo (
    id              bigserial primary key,
    cnpj            text not null references emissores(cnpj),
    tipo_doc        text not null,
    -- Tipos: relatorio_rating | fre | escritura | apresentacao |
    --        notas_explicativas | release | dou | outros
    fonte           text,           -- Ex: "Fitch 2024-03", "FRE 2023", "DFP notas 2023"
    data_ref        date,
    chunk_index     integer not null,
    texto           text not null,
    embedding       vector(1536),   -- text-embedding-3-small (OpenAI)
    criado_em       timestamptz default now(),

    unique (cnpj, tipo_doc, fonte, chunk_index)
);

comment on table doc_chunks_qualitativo is
    'Chunks de documentos qualitativos com embedding vetorial. '
    'Populado pelo pipeline de parsing de PDFs (Fase 4). '
    'Usado pelo context builder da Skill 3 via busca semântica.';

-- Índice vetorial — descomentar após ter ≥ 200 chunks inseridos
-- create index on doc_chunks_qualitativo using ivfflat (embedding vector_cosine_ops)
--     with (lists = 100);

create index if not exists idx_chunks_cnpj      on doc_chunks_qualitativo (cnpj);
create index if not exists idx_chunks_tipo      on doc_chunks_qualitativo (cnpj, tipo_doc);

-- ── Funções e triggers ────────────────────────────────────────
create or replace function set_atualizado_em()
returns trigger language plpgsql as $$
begin
    new.atualizado_em = now();
    return new;
end;
$$;

create or replace trigger trg_emissores_atualizado
    before update on emissores
    for each row execute function set_atualizado_em();

create or replace trigger trg_deb_caracteristicas_atualizado
    before update on deb_caracteristicas
    for each row execute function set_atualizado_em();

-- ── Views úteis ───────────────────────────────────────────────
create or replace view v_ultimo_periodo as
select distinct on (cnpj)
    cnpj, data_ref, tipo_doc
from demonstracoes_financeiras
order by cnpj, data_ref desc;

comment on view v_ultimo_periodo is 'Último período disponível por empresa';

-- Vista do portfólio ativo com emissor
create or replace view v_portfolio_ativo as
select
    o.ticker_deb,
    o.nome_emissor,
    e.grupo_economico,
    e.setor,
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
from deb_caracteristicas o
join emissores e on e.cnpj = o.cnpj
where o.status = 'ativo'
order by o.data_vencimento;

comment on view v_portfolio_ativo is
    'Portfólio de operações ativas com dados do emissor — visão principal do sistema';


-- ── Tabela: deb_agenda ─────────────────────────────────
-- Adicionada após análise dos payloads ANBIMA (ALAR14 e PETR26)
create table if not exists deb_agenda (
    id                  bigserial primary key,
    ticker_deb          text not null references deb_caracteristicas(ticker_deb),
    cnpj                text not null references emissores(cnpj),

    -- Datas (distintas conforme payload ANBIMA)
    data_evento         date not null,
    data_liquidacao     date,
    data_base           date,

    -- Tipo do evento
    evento              text not null,   -- "PAGAMENTO DE JUROS" | "AMORTIZACAO" | "VENCIMENTO (RESGATE)"
    evento_arc          text,            -- categoria simplificada: "Juros" | "Amortização"

    -- Valores
    taxa                numeric,         -- percentual (ex: 33.3333 para amortização parcial)
    valor               numeric,         -- valor unitário pago — null se ainda previsto

    -- Status
    status              text,            -- "Previsto" | "Liquidado"
    grupo_status        text,            -- "Planejado" | "Positivo"

    criado_em           timestamptz default now(),

    unique (ticker_deb, data_evento, evento)
);

comment on table deb_agenda is
    'Fluxo de eventos de cada debênture — juros, amortizações e resgates. '
    'Populado via scraping ANBIMA. Status Liquidado indica evento já pago.';

create index if not exists idx_agenda_data
    on deb_agenda (data_evento);
create index if not exists idx_agenda_ticker
    on deb_agenda (ticker_deb, data_evento);
create index if not exists idx_agenda_status
    on deb_agenda (status, data_evento);

-- ── Tabela: deb_historico_diario ──────────────────────────────────────
-- Série temporal de mercado por debênture
create table if not exists deb_historico_diario (
    id                      bigserial primary key,
    ticker_deb              text not null references deb_caracteristicas(ticker_deb),
    data_referencia         date not null,

    -- Valores Teóricos / Curva do Papel (da Escritura)
    pu_par                  numeric,
    vna                     numeric,
    juros                   numeric,
    prazo_remanescente      integer,

    -- Marcação a Mercado (Indicativos ANBIMA)
    pu_indicativo           numeric,
    taxa_indicativa         numeric,
    taxa_compra             numeric,
    taxa_venda              numeric,
    duration_dias_uteis     numeric,
    desvio_padrao           numeric,
    percentual_pu_par       numeric,
    percentual_vne          numeric,
    intervalo_indicativo_min numeric,
    intervalo_indicativo_max numeric,
    referencia_ntnb         text,
    spread_indicativo       numeric,

    -- Dados de Negociação / Mercado Secundário (API Paga / Futuro)
    volume_financeiro       numeric,
    quantidade_negocios     integer,
    quantidade_titulos      integer,
    taxa_media_negocios     numeric,
    pu_medio_negocios       numeric,

    -- Metadados / Flags
    reune                   text,
    percentual_reune        numeric,
    pu_indicativo_status    text,
    taxa_indicativa_status  text,
    flag_status             text,
    data_ultima_atualizacao date,
    criado_em               timestamptz default now(),

    unique (ticker_deb, data_referencia)
);

comment on table deb_historico_diario is
    'Série temporal consolidada e fotografias do mercado secundário por debênture.';

create index if not exists idx_hist_ticker_data
    on deb_historico_diario (ticker_deb, data_referencia desc);

-- ── View: próximos pagamentos ─────────────────────────────────
create or replace view v_proximos_pagamentos as
select
    a.data_evento,
    a.ticker_deb,
    em.nome        as emissor,
    em.grupo_economico,
    a.evento,
    a.evento_arc,
    a.taxa,
    a.valor,
    a.status,
    (a.data_evento - current_date) as dias_para_evento
from deb_agenda a
join deb_caracteristicas o  on o.ticker_deb = a.ticker_deb
join emissores em on em.cnpj = o.cnpj
where a.data_evento >= current_date
  and a.status = 'Previsto'
order by a.data_evento;

comment on view v_proximos_pagamentos is
    'Próximos eventos de pagamento de todas as debêntures monitoradas';