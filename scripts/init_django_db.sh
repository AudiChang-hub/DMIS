#!/usr/bin/env bash
set -Eeuo pipefail

# PostgreSQL 官方 image 只會在全新的資料 volume 執行此檔。管理角色保留給
# 初始化／備份；Django runtime 改用資料庫 owner、但非 cluster superuser 的角色。
: "${POSTGRES_USER:?缺少 POSTGRES_USER}"
: "${POSTGRES_DB:?缺少 POSTGRES_DB}"
: "${POSTGRES_PASSWORD:?缺少 POSTGRES_PASSWORD}"
: "${DJANGO_DB_USER:?缺少 DJANGO_DB_USER}"
: "${DJANGO_DB_PASSWORD:?缺少 DJANGO_DB_PASSWORD}"

if [[ "$DJANGO_DB_USER" == "$POSTGRES_USER" ]]; then
    echo "ERROR: DJANGO_DB_USER 不可與 PostgreSQL 管理角色相同" >&2
    exit 1
fi
if [[ "$DJANGO_DB_PASSWORD" == "$POSTGRES_PASSWORD" ]]; then
    echo "ERROR: 應用程式與 PostgreSQL 管理角色不可使用相同密碼" >&2
    exit 1
fi

psql \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    --set ON_ERROR_STOP=1 \
    --set admin_user="$POSTGRES_USER" \
    --set app_user="$DJANGO_DB_USER" \
    --set app_password="$DJANGO_DB_PASSWORD" \
    --set db_name="$POSTGRES_DB" <<'SQL'
SELECT format(
    'CREATE ROLE %I WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD %L',
    :'app_user',
    :'app_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user')
\gexec

-- 既有角色也必須收斂；只保留登入能力，不在腳本中自動輪替既有密碼。
SELECT format(
    'ALTER ROLE %I WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION',
    :'app_user'
)
\gexec

-- REASSIGN OWNED 也會移交其他 database／tablespace 等 shared objects，不能用於
-- 只服務單一應用程式的角色切割。以下只移交目前 database 的非系統物件。
SELECT set_config('dmis.app_user', :'app_user', false);

DO $dmis$
DECLARE
    item record;
    alter_kind text;
BEGIN
    FOR item IN
        SELECT namespace.nspname, relation.relname, relation.relkind
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        JOIN pg_roles AS owner_role ON owner_role.oid = relation.relowner
        WHERE namespace.nspname NOT IN ('pg_catalog', 'information_schema')
          AND namespace.nspname !~ '^pg_toast'
          AND owner_role.rolname = current_user
          AND relation.relkind IN ('r', 'p', 'S', 'v', 'm', 'f')
          AND NOT EXISTS (
              SELECT 1
              FROM pg_depend AS dependency
              WHERE dependency.classid = 'pg_class'::regclass
                AND dependency.objid = relation.oid
                AND dependency.deptype = 'e'
          )
    LOOP
        alter_kind := CASE item.relkind
            WHEN 'S' THEN 'SEQUENCE'
            WHEN 'v' THEN 'VIEW'
            WHEN 'm' THEN 'MATERIALIZED VIEW'
            ELSE 'TABLE'
        END;
        EXECUTE format(
            'ALTER %s %I.%I OWNER TO %I',
            alter_kind,
            item.nspname,
            item.relname,
            current_setting('dmis.app_user')
        );
    END LOOP;
END
$dmis$;

DO $dmis$
DECLARE
    item record;
    alter_kind text;
BEGIN
    FOR item IN
        SELECT
            namespace.nspname,
            routine.proname,
            routine.prokind,
            pg_get_function_identity_arguments(routine.oid) AS identity_arguments
        FROM pg_proc AS routine
        JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
        JOIN pg_roles AS owner_role ON owner_role.oid = routine.proowner
        WHERE namespace.nspname NOT IN ('pg_catalog', 'information_schema')
          AND namespace.nspname !~ '^pg_toast'
          AND owner_role.rolname = current_user
          AND NOT EXISTS (
              SELECT 1
              FROM pg_depend AS dependency
              WHERE dependency.classid = 'pg_proc'::regclass
                AND dependency.objid = routine.oid
                AND dependency.deptype = 'e'
          )
    LOOP
        alter_kind := CASE item.prokind
            WHEN 'p' THEN 'PROCEDURE'
            WHEN 'a' THEN 'AGGREGATE'
            ELSE 'FUNCTION'
        END;
        EXECUTE format(
            'ALTER %s %I.%I(%s) OWNER TO %I',
            alter_kind,
            item.nspname,
            item.proname,
            item.identity_arguments,
            current_setting('dmis.app_user')
        );
    END LOOP;
END
$dmis$;

DO $dmis$
DECLARE
    item record;
BEGIN
    FOR item IN
        SELECT namespace.nspname, data_type.typname
        FROM pg_type AS data_type
        JOIN pg_namespace AS namespace ON namespace.oid = data_type.typnamespace
        JOIN pg_roles AS owner_role ON owner_role.oid = data_type.typowner
        WHERE namespace.nspname NOT IN ('pg_catalog', 'information_schema')
          AND namespace.nspname !~ '^pg_toast'
          AND owner_role.rolname = current_user
          AND data_type.typrelid = 0
          AND data_type.typelem = 0
          AND data_type.typtype NOT IN ('b', 'p')
          AND NOT EXISTS (
              SELECT 1
              FROM pg_depend AS dependency
              WHERE dependency.classid = 'pg_type'::regclass
                AND dependency.objid = data_type.oid
                AND dependency.deptype = 'e'
          )
    LOOP
        EXECUTE format(
            'ALTER TYPE %I.%I OWNER TO %I',
            item.nspname,
            item.typname,
            current_setting('dmis.app_user')
        );
    END LOOP;
END
$dmis$;

DO $dmis$
DECLARE
    item record;
BEGIN
    FOR item IN
        SELECT namespace.nspname
        FROM pg_namespace AS namespace
        JOIN pg_roles AS owner_role ON owner_role.oid = namespace.nspowner
        WHERE namespace.nspname NOT IN ('pg_catalog', 'information_schema')
          AND namespace.nspname !~ '^pg_toast'
          AND owner_role.rolname = current_user
    LOOP
        EXECUTE format(
            'ALTER SCHEMA %I OWNER TO %I',
            item.nspname,
            current_setting('dmis.app_user')
        );
    END LOOP;
END
$dmis$;

SELECT format('ALTER DATABASE %I OWNER TO %I', :'db_name', :'app_user')
\gexec

GRANT USAGE, CREATE ON SCHEMA public TO :"app_user";
SQL
