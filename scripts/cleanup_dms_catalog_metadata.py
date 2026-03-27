#!/usr/bin/env python3
"""清理已移除模組與重建 dms_product 前的殘留 metadata。"""

from __future__ import annotations

import argparse
import subprocess
import sys
import textwrap
from pathlib import Path


CATALOG_ONLY_MODELS = (
    "dms.product.sku",
)

REMOVED_MODULES = (
    "dms_catalog",
    "dms_pricelist",
)

MIGRATED_MODULES = (
    "dms_pricelist",
)

MIGRATED_METADATA_MODELS = (
    "ir.model",
    "ir.model.fields",
    "ir.model.fields.selection",
)

LEGACY_TOP_LEVEL_MENUS = (
    "產品目錄",
    "產品管理",
    "價目管理",
)


def sql_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def run_psql(repo_root: Path, sql: str, database: str, user: str) -> str:
    command = [
        "docker",
        "compose",
        "exec",
        "-T",
        "db",
        "psql",
        "-U",
        user,
        "-d",
        database,
        "-v",
        "ON_ERROR_STOP=1",
        "-At",
        "-F",
        "|",
        "-f",
        "-",
    ]
    completed = subprocess.run(
        command,
        cwd=repo_root,
        input=sql,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout.strip()


def query_value(repo_root: Path, sql: str, database: str, user: str) -> str:
    return run_psql(repo_root, sql, database, user).strip()


def query_rows(repo_root: Path, sql: str, database: str, user: str) -> list[str]:
    output = run_psql(repo_root, sql, database, user)
    if not output:
        return []
    return [line for line in output.splitlines() if line]


def build_cleanup_sql() -> str:
    catalog_only_models = sql_list(CATALOG_ONLY_MODELS)
    removed_modules = sql_list(REMOVED_MODULES)
    migrated_modules = sql_list(MIGRATED_MODULES)
    migrated_metadata_models = sql_list(MIGRATED_METADATA_MODELS)
    return textwrap.dedent(
        f"""
        BEGIN;

        DELETE FROM ir_model_data d
        WHERE d.module IN ({migrated_modules})
          AND d.model IN ({migrated_metadata_models})
          AND EXISTS (
              SELECT 1
              FROM ir_model_data s
              WHERE s.module = 'dms_sale'
                AND s.model = d.model
                AND s.res_id = d.res_id
          );

        DELETE FROM ir_model_data d
        WHERE d.module = 'dms_catalog'
          AND d.model = 'ir.model'
          AND EXISTS (
              SELECT 1
              FROM ir_model_data s
              WHERE s.module = 'dms_sale'
                AND s.model = 'ir.model'
                AND s.res_id = d.res_id
          );

        DELETE FROM ir_actions
        WHERE id IN (
            SELECT res_id
            FROM ir_model_data
            WHERE module IN ({removed_modules})
              AND model IN ('ir.actions.act_window', 'ir.actions.server')
        );

        DELETE FROM ir_ui_menu
        WHERE id IN (
            SELECT res_id
            FROM ir_model_data
            WHERE module IN ({removed_modules})
              AND model = 'ir.ui.menu'
        );

        DELETE FROM ir_ui_view
        WHERE id IN (
            SELECT res_id
            FROM ir_model_data
            WHERE module IN ({removed_modules})
              AND model = 'ir.ui.view'
        );

        DELETE FROM ir_model_access
        WHERE id IN (
            SELECT res_id
            FROM ir_model_data
            WHERE module IN ({removed_modules})
              AND model = 'ir.model.access'
        );

        DELETE FROM res_groups
        WHERE id IN (
            SELECT res_id
            FROM ir_model_data
            WHERE module IN ({removed_modules})
              AND model = 'res.groups'
        );

        DO $$
        BEGIN
            IF to_regclass('public.dms_fee_type') IS NOT NULL THEN
                DELETE FROM dms_fee_type
                WHERE id IN (
                    SELECT res_id
                    FROM ir_model_data
                    WHERE module = 'dms_catalog'
                      AND model = 'dms.fee.type'
                );
            END IF;
        END
        $$;

        DELETE FROM ir_model
        WHERE model IN ({catalog_only_models});

        DELETE FROM ir_model_data d
        WHERE d.module = 'base'
          AND d.name = 'module_dms_product'
          AND d.model = 'ir.module.module'
          AND NOT EXISTS (
              SELECT 1
              FROM ir_module_module m
              WHERE m.id = d.res_id
                AND m.name = 'dms_product'
          );

        DELETE FROM ir_model_data
        WHERE module IN ({removed_modules});

        DELETE FROM ir_module_module
        WHERE name IN ({removed_modules})
          AND state = 'uninstalled';

        COMMIT;
        """
    ).strip()


def print_header(title: str) -> None:
    print(f"[cleanup_dms_catalog_metadata] {title}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "清理 dms_catalog / dms_pricelist 已移除後殘留的 metadata、"
            "舊頂層選單、模組登記，以及重建 dms_product 前的孤兒模組 XML ID。"
        )
    )
    parser.add_argument("--database", default="dmis_dev", help="目標資料庫名稱")
    parser.add_argument("--user", default="odoo", help="PostgreSQL 使用者")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只列出目前殘留狀態，不執行清理",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]

    states_sql = f"""
    select name || '|' || state
    from ir_module_module
    where name in ({sql_list(REMOVED_MODULES)})
    order by name;
    """
    state_rows = query_rows(repo_root, states_sql, args.database, args.user)
    states = dict(row.split("|", 1) for row in state_rows)
    active_modules = [
        f"{module}: {state}"
        for module, state in states.items()
        if state != "uninstalled"
    ]
    if active_modules:
        print_header("以下模組尚未卸載，請先完成卸載再執行清理：")
        for module_state in active_modules:
            print(f"  - {module_state}")
        return 1

    counts_sql = f"""
    select module || '|' || model || '|' || count(*)
    from ir_model_data
    where module in ({sql_list(REMOVED_MODULES)})
    group by module, model
    order by module, model;
    """
    before_rows = query_rows(repo_root, counts_sql, args.database, args.user)
    print_header("目前已移除模組殘留統計：")
    if before_rows:
        for row in before_rows:
            module, model, count = row.split("|", 2)
            print(f"  - {module} / {model}: {count}")
    else:
        print("  - 無殘留 ir_model_data")

    stale_models_sql = f"""
    select model
    from ir_model
    where model in ({sql_list(CATALOG_ONLY_MODELS)})
    order by model;
    """
    stale_models = query_rows(repo_root, stale_models_sql, args.database, args.user)
    if stale_models:
        print_header("目前仍存在的 catalog-only ir.model：")
        for model in stale_models:
            print(f"  - {model}")
    else:
        print_header("目前無 catalog-only ir.model 殘留。")

    legacy_menus_sql = f"""
    select imd.module || '|' || imd.name || '|' ||
           coalesce(m.name->>'zh_TW', m.name->>'en_US', m.name::text)
    from ir_ui_menu m
    join ir_model_data imd
      on imd.model = 'ir.ui.menu'
     and imd.res_id = m.id
    where imd.module in ({sql_list(REMOVED_MODULES)})
      and m.parent_id is null
    order by imd.module, imd.name;
    """
    legacy_menus = query_rows(repo_root, legacy_menus_sql, args.database, args.user)
    if legacy_menus:
        print_header("目前仍存在的舊頂層選單：")
        for row in legacy_menus:
            module, xmlid, menu_name = row.split("|", 2)
            print(f"  - {module}.{xmlid}: {menu_name}")
    else:
        print_header("目前無舊頂層選單殘留。")

    unreplaced_metadata_sql = f"""
    select d.module || '|' || d.model || '|' || d.name || '|' || d.res_id
    from ir_model_data d
    left join ir_model_data s
      on s.res_id = d.res_id
     and s.model = d.model
     and s.module = 'dms_sale'
    where d.module in ({sql_list(MIGRATED_MODULES)})
      and d.model in ({sql_list(MIGRATED_METADATA_MODELS)})
      and s.res_id is null
    order by d.module, d.model, d.res_id;
    """
    unreplaced_metadata = query_rows(
        repo_root,
        unreplaced_metadata_sql,
        args.database,
        args.user,
    )
    if unreplaced_metadata:
        print_header("以下共享模型 metadata 尚未由 dms_sale 接手，已停止清理：")
        for row in unreplaced_metadata:
            module, model, name, res_id = row.split("|", 3)
            print(f"  - {module} / {model} / {name} / {res_id}")
        return 1

    if args.dry_run:
        print_header("dry-run 結束，未執行任何刪除。")
        return 0

    print_header("開始執行清理（含舊頂層選單、舊 xmlid 與模組登記）。")
    run_psql(repo_root, build_cleanup_sql(), args.database, args.user)

    after_count = query_value(
        repo_root,
        f"select count(*) from ir_model_data where module in ({sql_list(REMOVED_MODULES)});",
        args.database,
        args.user,
    )
    after_models = query_rows(repo_root, stale_models_sql, args.database, args.user)
    module_row_count = query_value(
        repo_root,
        f"select count(*) from ir_module_module where name in ({sql_list(REMOVED_MODULES)});",
        args.database,
        args.user,
    )
    legacy_menu_count = query_value(
        repo_root,
        f"""
        select count(*)
        from ir_ui_menu m
        left join ir_model_data imd
          on imd.model = 'ir.ui.menu'
         and imd.res_id = m.id
        where (imd.module in ({sql_list(REMOVED_MODULES)}) and imd.model = 'ir.ui.menu')
           or (
                m.parent_id is null
            and coalesce(m.name->>'zh_TW', m.name->>'en_US', m.name::text)
                in ({sql_list(LEGACY_TOP_LEVEL_MENUS)})
           );
        """,
        args.database,
        args.user,
    )
    print_header(f"清理後舊模組 ir_model_data 數量：{after_count}")
    if after_models:
        print_header("仍殘留以下 catalog-only ir.model：")
        for model in after_models:
            print(f"  - {model}")
        return 1
    if module_row_count != "0":
        print_header("已移除模組的登記仍存在於 ir_module_module，清理未完成。")
        return 1
    if legacy_menu_count != "0":
        print_header("舊頂層選單仍存在，清理未完成。")
        return 1

    print_header("清理完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
