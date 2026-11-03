-- For a database where schema.sql was already applied before the "snapshot" column existed.
-- Safe to run more than once. New databases do not need it: schema.sql already includes the column.
-- Run it on a Neon BRANCH first.
alter table leads add column if not exists snapshot jsonb;