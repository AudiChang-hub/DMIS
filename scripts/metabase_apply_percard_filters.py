#!/usr/bin/env python3
"""Phase 2b：為 P17/P18/P19 / P22 依 card name 注入 per-card 硬編碼篩選。

用法：
    python3 scripts/metabase_apply_percard_filters.py             # dry-run
    python3 scripts/metabase_apply_percard_filters.py --apply     # 寫入

規則：
- P17/P18/P19：card name "P## <MODEL_TOKEN>-..." → starts-with(model, MODEL_TOKEN)
- P22：card name "P22 <AGE>歲<SEX>" → age_group=<AGE>歲 AND sex=<SEX>
"""
from __future__ import annotations
import copy
import re
import sys
import uuid as _uuid
import requests
from metabase_credentials import load_metabase_credentials

BASE, EMAIL, PASSWORD = load_metabase_credentials()
F_MODEL = 1632
F_AGE_GROUP = 1644
F_SEX = 1642


def uu():
    return str(_uuid.uuid4())


def field_ref(fid, bt="type/Text"):
    return ["field", {"lib/uuid": uu(), "base-type": bt, "effective-type": bt}, fid]


def starts_with(fid, val):
    return ["starts-with", {"lib/uuid": uu(), "case-sensitive": False}, field_ref(fid), val]


def eq(fid, val):
    return ["=", {"lib/uuid": uu()}, field_ref(fid), val]


def sig(c):
    if not isinstance(c, list) or not c:
        return ""
    op = c[0]
    fid = None
    val = None
    for item in c:
        if isinstance(item, list) and item and item[0] == "field":
            fid = item[-1]
        elif isinstance(item, (str, int, float, bool)) and item != op:
            val = item
    return f"{op}|{fid}|{val}"


def sigs(filters):
    return {sig(f) for f in (filters or []) if isinstance(f, list)}


def rules_for_card(card):
    name = (card.get("name") or "").strip()
    rules = []

    # P17 / P18 / P19 → starts-with(model, <TOKEN>)
    m = re.match(r"^P(17|18|19)\s+([A-Za-z0-9]+)\s*-", name)
    if m:
        token = m.group(2)
        rules.append(starts_with(F_MODEL, token))
        return rules

    # P22 <AGE>歲<SEX>
    m = re.match(r"^P22\s+(\d{2}-\d{2})歲(男性|女性)", name)
    if m:
        rules.append(eq(F_AGE_GROUP, f"{m.group(1)}歲"))
        rules.append(eq(F_SEX, m.group(2)))
        return rules

    return rules


def login():
    r = requests.post(f"{BASE}/session", json={"username": EMAIL, "password": PASSWORD})
    r.raise_for_status()
    return r.json()["id"]


def get(tok, path):
    r = requests.get(f"{BASE}{path}", headers={"X-Metabase-Session": tok})
    r.raise_for_status()
    return r.json()


def put(tok, path, body):
    r = requests.put(f"{BASE}{path}", headers={"X-Metabase-Session": tok}, json=body)
    r.raise_for_status()
    return r.json()


def main():
    apply_mode = "--apply" in sys.argv
    tok = login()

    target_dash_ids = [19, 20, 21, 23]
    card_ids = set()
    for did in target_dash_ids:
        d = get(tok, f"/dashboard/{did}")
        for dc in d.get("dashcards") or []:
            if dc.get("card_id"):
                card_ids.add(dc["card_id"])

    total = updated = ok = skipped = 0
    for cid in sorted(card_ids):
        total += 1
        card = get(tok, f"/card/{cid}")
        name = card.get("name")
        rules = rules_for_card(card)
        if not rules:
            print(f"SKIP card#{cid} {name}: 無法由 card name 推得規則")
            skipped += 1
            continue
        dq = card.get("dataset_query") or {}
        stages = dq.get("stages") or []
        if not stages or not stages[0].get("source-table"):
            print(f"SKIP card#{cid} {name}: empty query")
            skipped += 1
            continue
        existing = stages[0].get("filters") or []
        missing = [r for r in rules if sig(r) not in sigs(existing)]
        if not missing:
            print(f"OK   card#{cid} {name}: 已存在")
            ok += 1
            continue
        print(f"UPD  card#{cid} {name}: +{len(missing)} 條件 {[sig(m) for m in missing]}")
        if apply_mode:
            new_dq = copy.deepcopy(dq)
            new_dq["stages"][0]["filters"] = list(existing) + missing
            put(tok, f"/card/{cid}", {"dataset_query": new_dq})
            print(f"     [applied]")
        updated += 1

    print(f"\nTotal={total} updated={updated} ok={ok} skipped={skipped}")
    if not apply_mode:
        print("[dry-run] 加 --apply 寫入")


if __name__ == "__main__":
    main()
