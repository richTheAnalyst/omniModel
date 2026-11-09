-- A contact email on a saved lead, so the send panel can prefill it.
begin;
alter table leads add column if not exists email text;
commit;