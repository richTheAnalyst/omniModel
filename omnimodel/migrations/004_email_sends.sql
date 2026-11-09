-- Adds the record of emails sent from the app (used for the daily limit and as a paper trail).
-- Safe to run more than once. New databases do not need it: schema.sql already includes it. Run it on a Neon BRANCH first.
create table if not exists email_sends (
  id            uuid primary key default gen_random_uuid(),
  workspace_id  uuid not null references workspaces(id) on delete cascade,
  user_id       uuid references users(id),
  lead_id       uuid references leads(id) on delete set null,
  to_address    text not null,
  subject       text not null,
  status        text not null default 'sending' check (status in ('sending', 'sent', 'failed')),
  error         text,
  created_at    timestamptz not null default now()
);
create index if not exists email_sends_recent on email_sends (workspace_id, created_at desc);