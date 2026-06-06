-- Migration: 00001_init_trading_schema.sql
-- Initial Supabase schema for mt5_bot trading system

-- =========================================================================
-- 1. EXTENSIONS
-- =========================================================================
create extension if not exists "pgcrypto";
create extension if not exists "pg_stat_statements";

-- =========================================================================
-- 2. TRADES
-- =========================================================================
create table if not exists trades (
  id            uuid primary key default gen_random_uuid(),
  symbol        text not null,
  direction     text not null check (direction in ('buy', 'sell')),
  size          numeric not null,
  entry_price   numeric not null,
  stop_loss     numeric,
  take_profit   numeric,
  strategy      text,
  agent         text,
  opened_at     timestamptz default now(),
  closed_at     timestamptz,
  pnl           numeric,
  pnl_pct       numeric,
  status        text default 'open' check (status in ('open', 'closed', 'canceled', 'pending')),
  close_reason  text,
  metadata      jsonb default '{}'::jsonb
);

-- Indexes for trade queries
create index if not exists idx_trades_symbol on trades(symbol);
create index if not exists idx_trades_status on trades(status);
create index if not exists idx_trades_strategy on trades(strategy);
create index if not exists idx_trades_opened_at on trades(opened_at desc);
create index if not exists idx_trades_agent on trades(agent);

-- =========================================================================
-- 3. SIGNALS
-- =========================================================================
create table if not exists signals (
  id            uuid primary key default gen_random_uuid(),
  symbol        text not null,
  direction     text not null check (direction in ('buy', 'sell')),
  strategy      text not null,
  agent         text not null,
  price         numeric not null,
  confidence    numeric check (confidence >= 0 and confidence <= 100),
  timeframe     text,
  reason        text,
  confluence    integer default 0,
  executed      boolean default false,
  trade_id      uuid references trades(id) on delete set null,
  created_at    timestamptz default now(),
  expires_at    timestamptz
);

create index if not exists idx_signals_symbol on signals(symbol);
create index if not exists idx_signals_strategy on signals(strategy);
create index if not exists idx_signals_created_at on signals(created_at desc);
create index if not exists idx_signals_executed on signals(executed);

-- =========================================================================
-- 4. STRATEGIES CATALOG
-- =========================================================================
create table if not exists strategies (
  id            uuid primary key default gen_random_uuid(),
  name          text unique not null,
  type          text not null check (type in ('scalp', 'swing', 'grid', 'custom')),
  description   text,
  is_active     boolean default true,
  config        jsonb default '{}'::jsonb,
  created_at    timestamptz default now(),
  updated_at    timestamptz default now()
);

-- =========================================================================
-- 5. AGENT LOGS
-- =========================================================================
create table if not exists agent_logs (
  id            bigserial primary key,
  agent         text not null,
  level         text not null check (level in ('DEBUG', 'INFO', 'WARN', 'ERROR', 'CRITICAL')),
  message       text not null,
  metadata      jsonb default '{}'::jsonb,
  created_at    timestamptz default now()
);

create index if not exists idx_agent_logs_agent on agent_logs(agent);
create index if not exists idx_agent_logs_level on agent_logs(level);
create index if not exists idx_agent_logs_created_at on agent_logs(created_at desc);

-- =========================================================================
-- 6. RISK CONFIG
-- =========================================================================
create table if not exists risk_config (
  id                              text primary key default 'default',
  max_daily_dd_pct                numeric not null default 6.0,
  max_concurrent_trades           integer not null default 3,
  max_trades_per_symbol_per_day   integer not null default 2,
  risk_per_trade_pct              numeric not null default 1.0,
  min_rr                          numeric not null default 2.0,
  updated_at                      timestamptz default now()
);

-- =========================================================================
-- 7. ACCOUNT SNAPSHOTS
-- =========================================================================
create table if not exists account_snapshots (
  id              uuid primary key default gen_random_uuid(),
  balance         numeric not null,
  equity          numeric not null,
  margin          numeric,
  free_margin     numeric,
  margin_level    numeric,
  floating_pnl    numeric,
  daily_pnl       numeric,
  daily_dd_pct    numeric,
  account_currency text default 'USD',
  server          text,
  login           text,
  snapshot_at     timestamptz default now()
);

create index if not exists idx_account_snapshots_at on account_snapshots(snapshot_at desc);

-- =========================================================================
-- 8. JTCC TRADES TABLE (used by existing _push_supabase code)
-- =========================================================================
create table if not exists jtcc_trades (
  id            uuid primary key default gen_random_uuid(),
  symbol        text not null,
  direction     text,
  volume        numeric,
  entry_price   numeric,
  exit_price    numeric,
  pnl           numeric,
  strategy      text,
  agent         text,
  opened_at     timestamptz,
  closed_at     timestamptz,
  metadata      jsonb default '{}'::jsonb,
  created_at    timestamptz default now()
);

create index if not exists idx_jtcc_trades_created_at on jtcc_trades(created_at desc);
create index if not exists idx_jtcc_trades_symbol on jtcc_trades(symbol);

-- =========================================================================
-- 9. SYNC CONFIG (bridge sync state)
-- =========================================================================
create table if not exists sync_config (
  id                text primary key default 'default',
  bridge_url        text,
  sync_interval_sec integer default 5,
  last_sync_at      timestamptz,
  enabled           boolean default false,
  updated_at        timestamptz default now()
);

-- =========================================================================
-- 10. ROW LEVEL SECURITY
-- =========================================================================
alter table trades enable row level security;
alter table signals enable row level security;
alter table strategies enable row level security;
alter table agent_logs enable row level security;
alter table risk_config enable row level security;
alter table account_snapshots enable row level security;
alter table jtcc_trades enable row level security;
alter table sync_config enable row level security;

-- Service role (backend) has full access
create policy "Service role has full access to trades"
  on trades for all to service_role using (true) with check (true);
create policy "Service role has full access to signals"
  on signals for all to service_role using (true) with check (true);
create policy "Service role has full access to strategies"
  on strategies for all to service_role using (true) with check (true);
create policy "Service role has full access to agent_logs"
  on agent_logs for all to service_role using (true) with check (true);
create policy "Service role has full access to jtcc_trades"
  on jtcc_trades for all to service_role using (true) with check (true);

-- Anon key can insert trades (for the performance_tracker)
create policy "Anon can insert jtcc_trades"
  on jtcc_trades for insert to anon with check (true);
create policy "Anon can select jtcc_trades"
  on jtcc_trades for select to anon using (true);
