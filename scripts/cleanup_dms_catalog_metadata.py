#!/usr/bin/env python3
"""清理已移除 dms_catalog 模組留下的資料庫 metadata。"""

from __future__ import annotations

import argparse
import subprocess
import sys
import textwrap
from pathlib import Path


CATALOG_ONLY_MODELS = (
    "dms.product.template",
    "dms.product.sku",
    "dms.price.version",
    "dms.price.line",
    "dms.installment.rule",
    "dms.installment.rule.line",
    "dms.fee.type",
    "dms.installment.rule.fee",
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
    return textwrap.dedent(
        f"""
        BEGIN;

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
            WHERE module = 'dms_catalog'
              AND model IN ('ir.actions.act_window', 'ir.actions.server')
        );

        DELETE FROM ir_ui_menu
        WHERE id IN (
            SELECT res_id
            FROM ir_model_data
            WHERE module = 'dms_catalog'
              AND model = 'ir.ui.menu'
        );

        DELETE FROM ir_ui_view
        WHERE id IN (
            SELECT res_id
            FROM ir_model_data
            WHERE module = 'dms_catalog'
              AND model = 'ir.ui.view'
        );

        DELETE FROM ir_model_access
        WHERE id IN (
            SELECT res_id
            FROM ir_model_data
            WHERE module = 'dms_catalog'
              AND model = 'ir.model.access'
        );

        DELETE FROM res_groups
        WHERE id IN (
            SELECT res_id
            FROM ir_model_data
            WHERE module = 'dms_catalog'
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

        DELETE FROM ir_model_data
        WHERE module = 'dms_catalog';

        COMMIT;
        """
    ).strip()


def print_header(title: str) -> None:
    print(f"[cleanup_dms_catalog_metadata] {title}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="清理 dms_catalog 已移除後殘留的 metadata。"
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

    state = query_value(
        repo_root,
        "select state from ir_module_module where name = 'dms_catalog';",
        args.database,
        args.user,
    )
    if not state:
        print_header("資料庫中找不到 dms_catalog 模組紀錄，無需清理。")
        return 0
    if state != "uninstalled":
        print_header(f"dms_catalog 狀態為 {state}，請先卸載模組再執行。")
        return 1

    counts_sql = """
    select model || '|' || count(*)
    from ir_model_data
    where module = 'dms_catalog'
    group by model
    order by model;
    """
    before_rows = query_rows(repo_root, counts_sql, args.database, args.user)
    print_header("目前 dms_catalog 殘留統計：")
    if before_rows:
        for row in before_rows:
            model, count = row.split("|", 1)
            print(f"  - {model}: {count}")
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

    if args.dry_run:
        print_header("dry-run 結束，未執行任何刪除。")
        return 0

    print_header("開始執行清理。")
    run_psql(repo_root, build_cleanup_sql(), args.database, args.user)

    after_count = query_value(
        repo_root,
        "select count(*) from ir_model_data where module = 'dms_catalog';",
        args.database,
        args.user,
    )
    after_models = query_rows(repo_root, stale_models_sql, args.database, args.user)
    print_header(f"清理後 dms_catalog ir_model_data 數量：{after_count}")
    if after_models:
        print_header("仍殘留以下 catalog-only ir.model：")
        for model in after_models:
            print(f"  - {model}")
        return 1

    print_header("清理完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
