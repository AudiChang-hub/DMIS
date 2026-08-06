#!/usr/bin/env python3
"""列出 Metabase 所有 Dashboard 的詳細設定：cards / display / viz_settings / parameters / mappings / query。"""
import json
import requests
from metabase_credentials import load_metabase_credentials

BASE, EMAIL, PASSWORD = load_metabase_credentials()


def login():
    r = requests.post(f"{BASE}/session", json={"username": EMAIL, "password": PASSWORD})
    r.raise_for_status()
    return r.json()["id"]


def get(tok, path):
    return requests.get(f"{BASE}{path}", headers={"X-Metabase-Session": tok}).json()


def summarize_query(dq):
    if not dq:
        return "(none)"
    stages = dq.get("stages") or []
    if not stages:
        q = dq.get("query") or {}
        stages = [q] if q else []
    out = []
    for s in stages:
        breakouts = s.get("breakout") or []
        aggs = s.get("aggregation") or []
        filters = s.get("filters") or s.get("filter") or []
        order = s.get("order-by") or s.get("order_by") or []
        limit = s.get("limit")
        bk = [str(b[-1]) for b in breakouts if isinstance(b, list)]
        ag = [a[0] if isinstance(a, list) else str(a) for a in aggs]
        fl = json.dumps(filters, ensure_ascii=False) if filters else "(none)"
        out.append({
            "breakouts(field_id)": bk,
            "aggregations": ag,
            "filters": fl[:200],
            "order_by": json.dumps(order, ensure_ascii=False)[:150] if order else "(none)",
            "limit": limit,
        })
    return out


def main():
    tok = login()
    dashes = sorted(get(tok, "/dashboard"), key=lambda x: (x["name"].split()[0], x["id"]))
    out_lines = []

    for d in dashes:
        if d["name"] == "E-commerce Insights":
            continue
        det = get(tok, f"/dashboard/{d['id']}")
        out_lines.append(f"## Dashboard #{d['id']}: {d['name']}")
        # parameters
        params = det.get("parameters") or []
        if params:
            out_lines.append(f"  Parameters:")
            for p in params:
                out_lines.append(f"    - name={p.get('name')} slug={p.get('slug')} type={p.get('type')} id={p.get('id')}")
        else:
            out_lines.append(f"  Parameters: (none)")
        # public uuid
        puid = det.get("public_uuid")
        out_lines.append(f"  public_uuid: {puid}")
        # cards
        dcs = det.get("dashcards") or []
        out_lines.append(f"  Dashcards ({len(dcs)}):")
        for dc in dcs:
            c = dc.get("card") or {}
            cid = dc.get("card_id")
            name = c.get("name", "?")
            display = c.get("display", "?")
            vs = c.get("visualization_settings") or {}
            vs_keys = sorted(vs.keys())
            pms = dc.get("parameter_mappings") or []
            out_lines.append(f"    - card_id={cid} display={display} name={name}")
            out_lines.append(f"      viz_settings_keys: {vs_keys}")
            if vs.get("graph.dimensions") or vs.get("graph.metrics") or vs.get("graph.series_order") or vs.get("stackable.stack_type"):
                keep = {k: vs[k] for k in ["graph.dimensions","graph.metrics","graph.series_order","stackable.stack_type","graph.show_values","pie.show_data_labels","pie.percent_visibility"] if k in vs}
                out_lines.append(f"      viz_relevant: {json.dumps(keep, ensure_ascii=False)}")
            dq = c.get("dataset_query") or {}
            stages = summarize_query(dq)
            out_lines.append(f"      query: {json.dumps(stages, ensure_ascii=False)[:500]}")
            out_lines.append(f"      parameter_mappings: {len(pms)} (params: {[pm.get('parameter_id') for pm in pms]})")
        out_lines.append("")

    print("\n".join(out_lines))


if __name__ == "__main__":
    main()
