-- Initial schema migration: users + trades

create extension if not exists pgcrypto;

create table if not exists users (
  id uuid primary key default gen_random_uuid(),
  email text unique not null,
  created_at timestamptz default now()
);

create table if not exists trades (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete set null,
  symbol text not null,
  size numeric,
  direction text,
  opened_at timestamptz default now()
);
