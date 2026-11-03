-- Adds our own sign-in (passwords) to a database where schema.sql was already applied.
-- Safe to run more than once. New databases do not need it: schema.sql already includes all of this.
-- Run it on a Neon BRANCH first.
alter table users add column if not exists password_hash text;
alter table users add column if not exists token_version int not null default 0;
alter table users add column if not exists failed_logins int not null default 0;
alter table users add column if not exists locked_until timestamptz;
create unique index if not exists users_local_email_uq on users (lower(email)) where password_hash is not null;