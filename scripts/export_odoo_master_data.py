#!/usr/bin/env python3
"""Export the useful Odoo DMIS master data as a portable JSON document.

Run this inside the legacy Odoo container where psycopg2 and DB_* environment
variables are already available.  The export is read-only and intentionally
keeps legacy transaction counts separate from the master-data payload.
"""

from __future__ import annotations

import argparse
import datetime as dt
import decimal
import json
import os
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor


def _json_default(value):
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    raise TypeError(f"Unsupported JSON value: {type(value)!r}")


def _rows(connection, sql, params=()):
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


def _count(connection, table):
    allowed = {
        "dms_sale_order",
        "dms_incentive_rule",
        "dms_incentive_delivery",
        "dms_commission_volume_gift",
        "dms_commission_record",
        "dms_visit",
    }
    if table not in allowed:
        raise ValueError(f"Unsupported table: {table}")
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
        return cursor.fetchone()[0]


def build_payload(connection, database):
    dealers = _rows(
        connection,
        """
        SELECT d.*, st.name AS store_type_name, st.category AS store_type_category
          FROM dms_dealer d
          LEFT JOIN dms_store_type st ON st.id = d.store_type_id
         ORDER BY d.id
        """,
    )
    brands = _rows(connection, "SELECT * FROM dms_brand ORDER BY id")
    dealer_brand_auth = _rows(
        connection,
        """
        SELECT a.*, b.name AS brand_name
          FROM dms_dealer_brand_auth a
          JOIN dms_brand b ON b.id = a.brand_id
         ORDER BY a.id
        """,
    )
    legacy_dealer_brands = _rows(
        connection,
        """
        SELECT rel.dealer_id, rel.brand_id, b.name AS brand_name
          FROM dms_dealer_brand_rel rel
          JOIN dms_brand b ON b.id = rel.brand_id
         ORDER BY rel.dealer_id, rel.brand_id
        """,
    )
    products = _rows(
        connection,
        """
        SELECT p.*, b.name AS brand_name,
               COALESCE(p.engine_displacement, t.engine_displacement::text)
                   AS resolved_engine_displacement
          FROM dms_product p
          LEFT JOIN dms_brand b ON b.id = p.brand_id
          LEFT JOIN dms_product_template t ON t.id = p.template_id
         ORDER BY p.id
        """,
    )
    product_colors = _rows(
        connection,
        "SELECT * FROM dms_product_color ORDER BY product_id, sequence, id",
    )
    price_versions = _rows(
        connection,
        """
        SELECT pv.id AS version_id, pv.name AS version_name, pv.state,
               pv.effective_date, pv.note AS version_note,
               pl.id AS line_id, pl.product_id, pl.cash_price,
               pl.list_price, pl.is_promotion, pl.note AS line_note
          FROM dms_price_version pv
          JOIN dms_price_line pl ON pl.version_id = pv.id
         ORDER BY pl.product_id, pv.effective_date, pv.id, pl.id
        """,
    )
    installment_lines = _rows(
        connection,
        "SELECT * FROM dms_product_installment_line ORDER BY product_id, periods, id",
    )
    product_commissions = _rows(
        connection,
        """
        SELECT r.*, t.family_name, t.model_name,
               ARRAY(
                   SELECT p.id FROM dms_product p
                    WHERE p.template_id = r.product_tmpl_id ORDER BY p.id
               ) AS product_ids
          FROM dms_commission_product_rule r
          LEFT JOIN dms_product_template t ON t.id = r.product_tmpl_id
         ORDER BY r.id
        """,
    )
    dealer_commission_rules = _rows(
        connection,
        """
        SELECT r.*, b.name AS brand_name,
               ARRAY(
                   SELECT rel.dealer_id
                     FROM commission_dealer_rule_dealer_rel rel
                    WHERE rel.rule_id = r.id ORDER BY rel.dealer_id
               ) AS dealer_ids
          FROM dms_commission_dealer_rule r
          LEFT JOIN dms_brand b ON b.id = r.brand_id
         ORDER BY r.id
        """,
    )
    volume_rules = _rows(
        connection,
        """
        SELECT r.*, b.name AS brand_name,
               ARRAY(
                   SELECT rel.dealer_id
                     FROM commission_volume_rule_dealer_rel rel
                    WHERE rel.rule_id = r.id ORDER BY rel.dealer_id
               ) AS dealer_ids,
               ARRAY(
                   SELECT rel.tmpl_id
                     FROM commission_volume_rule_tmpl_rel rel
                    WHERE rel.rule_id = r.id ORDER BY rel.tmpl_id
               ) AS template_ids
          FROM dms_commission_volume_rule r
          LEFT JOIN dms_brand b ON b.id = r.brand_id
         ORDER BY r.id
        """,
    )
    holidays = _rows(
        connection,
        "SELECT id, date, name, note FROM dms_public_holiday ORDER BY date, id",
    )
    return {
        "schema_version": 1,
        "source": "Odoo DMIS",
        "source_database": database,
        "exported_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "dealers": dealers,
        "brands": brands,
        "dealer_brand_auth": dealer_brand_auth,
        "legacy_dealer_brands": legacy_dealer_brands,
        "products": products,
        "product_colors": product_colors,
        "price_versions": price_versions,
        "installment_lines": installment_lines,
        "product_commissions": product_commissions,
        "dealer_commission_rules": dealer_commission_rules,
        "volume_rules": volume_rules,
        "holidays": holidays,
        "legacy_only_counts": {
            table: _count(connection, table)
            for table in (
                "dms_sale_order",
                "dms_incentive_rule",
                "dms_incentive_delivery",
                "dms_commission_volume_gift",
                "dms_commission_record",
                "dms_visit",
            )
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="dmis_dev")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    connection = psycopg2.connect(
        host=os.environ.get("DB_HOST", "db"),
        port=os.environ.get("DB_PORT", "5432"),
        user=os.environ.get("DB_USER", "odoo"),
        password=os.environ.get("DB_PASSWORD", ""),
        dbname=args.database,
    )
    try:
        payload = build_payload(connection, args.database)
    finally:
        connection.close()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    print(
        "exported "
        f"dealers={len(payload['dealers'])} "
        f"products={len(payload['products'])} "
        f"holidays={len(payload['holidays'])} "
        f"to={output}"
    )


if __name__ == "__main__":
    main()
