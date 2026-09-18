-- Runs once, when the database volume is first created (docker-entrypoint-initdb.d).
-- Development credentials only: change the passwords for any shared or production database.

-- Owns the schema and runs migrations.
CREATE ROLE sourcely_owner LOGIN PASSWORD 'sourcely_owner';
-- What the API connects as. It owns no table, so row-level security always applies to it.
CREATE ROLE sourcely_app LOGIN PASSWORD 'sourcely_app';

CREATE DATABASE sourcely OWNER sourcely_owner;

\connect sourcely

-- Extensions need a superuser; migrations only check that they exist.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS citext;

GRANT USAGE ON SCHEMA public TO sourcely_app;
-- Tables and sequences the owner creates later are usable by the app role automatically.
ALTER DEFAULT PRIVILEGES FOR ROLE sourcely_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sourcely_app;
ALTER DEFAULT PRIVILEGES FOR ROLE sourcely_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO sourcely_app;
