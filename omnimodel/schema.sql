
Schema · SQL
-- omniModel database schema for Neon (Postgres). Run it on a Neon BRANCH first, never straight on production.
-- Guests never touch this database: their data stays in the browser. Everything here belongs to a signed-in user's workspace.
-- Every table that holds business data carries workspace_id, so one business can never see another's data.
 
begin;
 
-- ------------------------------------------------------------------ who
create table workspaces (                       -- one business (company) using the tool
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  created_at  timestamptz not null default now()
);
 
create table users (
  id            uuid primary key default gen_random_uuid(),
  auth_subject  text not null unique,           -- the user id given by the sign-in provider (never store passwords here)
  email         text,
  display_name  text,
  created_at    timestamptz not null default now(),
  last_seen_at  timestamptz
);
 
create table workspace_members (                -- officers of a business share one dashboard
  workspace_id  uuid not null references workspaces(id) on delete cascade,
  user_id       uuid not null references users(id) on delete cascade,
  role          text not null default 'member' check (role in ('owner', 'admin', 'member')),
  created_at    timestamptz not null default now(),
  primary key (workspace_id, user_id)
);
 
create table profile_versions (                 -- the business profile (services, industries, playbook, weights), versioned
  id            uuid primary key default gen_random_uuid(),
  workspace_id  uuid not null references workspaces(id) on delete cascade,
  version       int not null,
  profile       jsonb not null,
  created_by    uuid references users(id),
  created_at    timestamptz not null default now(),
  unique (workspace_id, version)
);
 
-- ------------------------------------------------------------------ searching
create table searches (
  id                  uuid primary key default gen_random_uuid(),
  workspace_id        uuid not null references workspaces(id) on delete cascade,
  user_id             uuid references users(id),
  profile_version_id  uuid references profile_versions(id),
  country             text,
  region              text,
  city                text,
  sector              text,
  max_results         int,
  shuffled            boolean not null default false,
  result_count        int,
  created_at          timestamptz not null default now()
);
create index on searches (workspace_id, created_at desc);
 
create table leads (                            -- one row per company per business
  id                    uuid primary key default gen_random_uuid(),
  workspace_id          uuid not null references workspaces(id) on delete cascade,
  place_id              text not null,          -- Google place id
  name                  text,
  address               text,
  city                  text,
  region                text,
  country               text,
  sector                text,
  phone                 text,
  website               text,
  lat                   double precision,       -- Google-derived fields: check Google's terms on how long they may be stored
  lng                   double precision,
  google_types          text[],
  rating                numeric(2, 1),
  review_count          int,
  details_fetched_at    timestamptz,            -- when the Google details were last refreshed
  ownership             text check (ownership in ('government', 'non_government')),
  ownership_confidence  text check (ownership_confidence in ('high', 'assumed', 'ai')),
  status                text not null default 'new'
                        check (status in ('new', 'contacted', 'meeting', 'proposal', 'won', 'lost', 'not_interested')),
  status_changed_at     timestamptz not null default now(),
  do_not_contact        boolean not null default false,
  assigned_to           uuid references users(id),
  contact_attempts      int not null default 0,
  last_contacted_at     timestamptz,
  next_follow_up_at     timestamptz,
  first_search_id       uuid references searches(id),
  first_seen_at         timestamptz not null default now(),
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  unique (workspace_id, place_id)
);
create index on leads (workspace_id, status);
create index on leads (workspace_id, next_follow_up_at) where next_follow_up_at is not null;
 
create table search_results (                   -- every lead shown in every search: who was seen, in what position
  search_id    uuid not null references searches(id) on delete cascade,
  lead_id      uuid not null references leads(id) on delete cascade,
  workspace_id uuid not null references workspaces(id) on delete cascade,
  position     int not null,
  best_offering text,
  score        numeric(5, 4),
  primary key (search_id, lead_id)
);
 
-- ------------------------------------------------------------------ what happened to a lead
create table lead_events (                      -- append-only history: every call, email, status change, note
  id            bigint generated always as identity primary key,
  workspace_id  uuid not null references workspaces(id) on delete cascade,
  lead_id       uuid not null references leads(id) on delete cascade,
  user_id       uuid references users(id),
  type          text not null check (type in (
                  'call_attempt', 'call_answered', 'email_sent', 'whatsapp_sent', 'visit', 'meeting',
                  'proposal_sent', 'status_change', 'note', 'analyzed', 'fit_override',
                  'do_not_contact_on', 'do_not_contact_off', 'won', 'lost')),
  detail        jsonb not null default '{}'::jsonb,
  occurred_at   timestamptz not null default now()
);
create index on lead_events (workspace_id, occurred_at desc);
create index on lead_events (lead_id, occurred_at);
 
create table outcomes (                         -- the ground truth for model building: did this lead become a client?
  lead_id          uuid primary key references leads(id) on delete cascade,
  workspace_id     uuid not null references workspaces(id) on delete cascade,
  result           text not null check (result in ('won', 'lost')),
  decided_on       date not null default current_date,
  offerings_sold   text[],                      -- which services they bought
  deal_value       numeric(14, 2),
  currency         text,
  contract_months  int,
  lost_reason      text check (lost_reason in ('price', 'competitor', 'no_need', 'no_budget', 'no_response', 'timing', 'other')),
  competitor_name  text,
  notes            text,
  recorded_by      uuid references users(id),
  recorded_at      timestamptz not null default now()
);
 
-- ------------------------------------------------------------------ what the scorer saw and said (training data)
create table lead_scores (                      -- a snapshot every time a lead is scored, so training data matches what the model saw
  id                  bigint generated always as identity primary key,
  workspace_id        uuid not null references workspaces(id) on delete cascade,
  lead_id             uuid not null references leads(id) on delete cascade,
  profile_version_id  uuid references profile_versions(id),
  stage               text not null check (stage in ('search', 'analyze')),
  scorer_version      text not null,            -- e.g. 'rules-v1'; change it whenever the formula changes
  best_offering       text,
  scores              jsonb not null,           -- per offering: score and breakdown
  inputs              jsonb not null,           -- the exact numbers fed to the formula (size, footprint, signals ...)
  computed_at         timestamptz not null default now()
);
create index on lead_scores (lead_id, computed_at desc);
 
create table lead_analyses (                    -- website analysis results (facts, not the whole page)
  id              bigint generated always as identity primary key,
  workspace_id    uuid not null references workspaces(id) on delete cascade,
  lead_id         uuid not null references leads(id) on delete cascade,
  url             text,
  signals         jsonb,
  evidence        jsonb,                        -- playbook keyword evidence
  ai_fit          jsonb,                        -- the AI's rating and reason per offering
  ownership       jsonb,
  llm_backend     text,
  llm_model       text,
  prompt_version  text,
  text_chars      int,
  text_sha256     text,                         -- fingerprint of the page text so we can tell if it changed
  warning         text,
  analyzed_at     timestamptz not null default now()
);
create index on lead_analyses (lead_id, analyzed_at desc);
 
create table officer_labels (                   -- a person's verdict on the suggested best fit
  id                 bigint generated always as identity primary key,
  workspace_id       uuid not null references workspaces(id) on delete cascade,
  lead_id            uuid not null references leads(id) on delete cascade,
  user_id            uuid references users(id),
  lead_score_id      bigint references lead_scores(id),
  suggested_offering text,
  chosen_offering    text,
  agreed             boolean not null,
  reason             text,
  labelled_at        timestamptz not null default now()
);
 
create table outreach (                         -- drafts and what happened to them
  id            uuid primary key default gen_random_uuid(),
  workspace_id  uuid not null references workspaces(id) on delete cascade,
  lead_id       uuid not null references leads(id) on delete cascade,
  user_id       uuid references users(id),
  kind          text check (kind in ('email', 'proposal', 'followup')),
  offering      text,
  channel       text check (channel in ('email', 'whatsapp', 'sms', 'call', 'visit', 'other')),
  draft_text    text,
  final_text    text,
  edited        boolean not null default false,
  sent_at       timestamptz,
  response      text check (response in ('none', 'replied', 'meeting_booked', 'declined')),
  responded_at  timestamptz,
  created_at    timestamptz not null default now()
);
create index on outreach (lead_id, created_at desc);
 
-- ------------------------------------------------------------------ limits and billing
create table usage_events (                     -- every billable action, for per-business limits and costs (guests: user_id null)
  id                bigint generated always as identity primary key,
  workspace_id      uuid references workspaces(id) on delete cascade,
  user_id           uuid references users(id),
  guest_hash        text,                       -- hashed device or IP for guests; never the raw value
  action            text not null check (action in ('search', 'analyze', 'suggest_fit', 'suggest_playbook', 'outreach', 'export')),
  google_requests   int not null default 0,
  llm_model         text,
  llm_input_tokens  int,
  llm_output_tokens int,
  created_at        timestamptz not null default now()
);
create index on usage_events (workspace_id, created_at desc);
 
-- ------------------------------------------------------------------ dashboard helpers
create view v_pipeline as
  select workspace_id, status, count(*) as leads
  from leads
  group by workspace_id, status;
 
create view v_daily_activity as
  select workspace_id,
         date_trunc('day', occurred_at) as day,
         count(*) filter (where type in ('call_attempt', 'call_answered')) as calls,
         count(*) filter (where type in ('email_sent', 'whatsapp_sent')) as messages,
         count(*) filter (where type = 'meeting') as meetings,
         count(*) filter (where type = 'won') as wins
  from lead_events
  group by workspace_id, date_trunc('day', occurred_at);
 
create view v_conversion_by_sector as
  select l.workspace_id, l.sector,
         count(*) as leads,
         count(*) filter (where o.result = 'won') as won,
         count(*) filter (where o.result = 'lost') as lost
  from leads l
  left join outcomes o on o.lead_id = l.id
  group by l.workspace_id, l.sector;
 
commit;
 
Claude finished the response
