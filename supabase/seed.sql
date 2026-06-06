-- Supabase seed data for mt5_bot trading system
-- Loaded during `supabase db reset`

-- Strategies catalog
insert into strategies (name, type, description, is_active) values
  ('S17-Scalp-LDN', 'scalp', 'London Silver Bullet scalping — M3 execution, 20-30 pip targets', true),
  ('S18-Scalp-NY', 'scalp', 'NY Silver Bullet scalping — M3 execution, 20-30 pip targets', true),
  ('S19-Breakout-LDN', 'scalp', 'London breakout scalper — M3 entry on H1 structure break', true),
  ('S20-Breakout-NY', 'scalp', 'NY breakout scalper — M3 entry on H1 structure break', true),
  ('S21-Momentum', 'scalp', 'Momentum/impulse scalper — M3 entry on volume+price surge', true),
  ('GSVP', 'swing', 'Global Session Volume Profile — H1/D1 swing trades', true),
  ('ICONIC', 'swing', 'ICT-based multi-timeframe swing strategy', true)
on conflict (name) do nothing;

-- Risk parameters
insert into risk_config (id, max_daily_dd_pct, max_concurrent_trades, max_trades_per_symbol_per_day, risk_per_trade_pct, min_rr)
values ('default', 6.0, 3, 2, 1.0, 2.0)
on conflict (id) do nothing;

-- Sync config
insert into sync_config (id, bridge_url, sync_interval_sec, enabled)
values ('default', 'http://localhost:8090', 5, false)
on conflict (id) do nothing;
