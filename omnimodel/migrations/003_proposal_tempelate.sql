-- Adds each business's own proposal PDF (used as a template) to a database where schema.sql was already applied.
-- Safe to run more than once. New databases do not need it: schema.sql already includes it. Run it on a Neon BRANCH first.
create table if not exists proposal_templates (
  workspace_id  uuid primary key references workspaces(id) on delete cascade,   -- one proposal template per business
  filename      text not null,
  pdf           bytea not null,                 -- the uploaded PDF exactly as it was
  size_bytes    int not null,
  replacements  jsonb not null,                 -- [{"find": "Acme Ltd", "as": "company"}]: what to swap in the sample
  uploaded_by   uuid references users(id),
  uploaded_at   timestamptz not null default now()
);