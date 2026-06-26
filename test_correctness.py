"""
Wellness MCP — correctness suite.

Proves the MCP layer returns the SAME data as the raw 汎用API (the source of truth),
across tables, operators, joins, and the known edge cases. Run this before every deploy
and whenever someone reports a wrong answer.

    python test_correctness.py            # offline-ish: MCP layer (server.py) vs raw API
    python test_correctness.py --live      # also smoke-test the deployed production endpoint

Exit code is non-zero if any check fails (handy for "don't deploy if red").
Cross-platform: no hardcoded paths; uses whatever `python` runs it.
"""
import sys, os, io, json

# make stdout show Japanese on any OS / console
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass

# import the project regardless of where it's run from
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server                       # the MCP layer under test
from wellness.client import query   # the raw API (source of truth)

PASS, FAIL = [], []

def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not ok else ""))

def norm(v):
    """Compare loosely: API sometimes returns '1' (str) where we expect 1 (int)."""
    return None if v is None else str(v)

TABLES = [f"T_MED_{i:02d}" for i in range(14)]

# --------------------------------------------------------------------------------------
print("\n=== 1. DATA FIDELITY: MCP wellness_query == raw API, field-by-field (every table) ===")
# For each table, take a real record from the API and confirm the MCP returns identical
# values for every column. This is the class of bug that caused the all-null T_MED_02 issue.
for t in TABLES:
    raw = query(base_table=t, limit=1)
    rows = raw.get("data") if isinstance(raw, dict) else None
    if not rows:
        check(f"{t}: has a sample row", False, "no rows returned by API")
        continue
    rec = rows[0]
    no = rec.get("WELLNESS_NO")
    fields = [k for k in rec if k != "WELLNESS_NO"]
    mcp = server.wellness_query(base_table=t, where={"WELLNESS_NO": no}, fields=fields)
    mrow = mcp["data"][0] if mcp.get("data") else {}
    diffs = [f for f in fields if norm(mrow.get(f)) != norm(rec.get(f))]
    check(f"{t}: MCP values == API values (WELLNESS_NO={no}, {len(fields)} fields)",
          not diffs, f"mismatched fields: {diffs[:5]}")

# --------------------------------------------------------------------------------------
print("\n=== 2. THE REGRESSION GUARD: non-T_MED_00 query with NO fields must return real data ===")
# The exact bug Watanabe hit: wellness_query on another table without `fields` returned all null.
raw = query(base_table="T_MED_02", where={"WELLNESS_NO": 124}, limit=1)
api_rec = raw["data"][0]
mcp = server.wellness_query(base_table="T_MED_02", where={"WELLNESS_NO": 124})  # no fields!
mrow = mcp["data"][0] if mcp.get("data") else {}
nonnull = [k for k, v in mrow.items() if v is not None and k != "WELLNESS_NO"]
check("T_MED_02 / WELLNESS_NO 124 no-fields returns >1 real value (not all null)", len(nonnull) > 1,
      f"non-null fields: {len(nonnull)}")
# and the values that ARE present match the API
present_ok = all(norm(mrow.get(k)) == norm(v) for k, v in api_rec.items() if k != "WELLNESS_NO")
check("T_MED_02 / 124 present values match the raw API", present_ok)

# --------------------------------------------------------------------------------------
print("\n=== 3. describe_table COMPLETENESS: MCP columns cover the live schema (every table) ===")
for t in TABLES:
    # union live-sampled columns
    sample = query(base_table=t, limit=50)
    live_cols = []
    for row in (sample.get("data") or []):
        for k, v in row.items():
            if k not in live_cols and not isinstance(v, (list, dict)):
                live_cols.append(k)
    mcp_cols = server.describe_table(t).get("columns", [])
    missing = [c for c in live_cols if c not in mcp_cols]
    check(f"{t}: describe_table covers all live columns ({len(mcp_cols)} cols)", not missing,
          f"missing: {missing}")

# --------------------------------------------------------------------------------------
print("\n=== 4. COUNT CONSISTENCY: MCP wellness_count == raw API total ===")
COUNT_CASES = [
    ("all facilities (no filter)", "T_MED_00", None),
    ("Tokyo (都13)", "T_MED_00", {"都道府県コード": 13}),
    ("Tokyo hospitals (都13, 分類0)", "T_MED_00", {"都道府県コード": 13, "分類コード": 0}),
    ("Kanagawa hospitals (都14, 分類0)", "T_MED_00", {"都道府県コード": 14, "分類コード": 0}),
    ("OR 13 or 27 ($or)", "T_MED_00", {"$or": [{"都道府県コード": 13}, {"都道府県コード": 27}]}),
    ("Tokyo, beds>=100 (join T_MED_01)", "T_MED_00",
        {"都道府県コード": 13, "分類コード": 0, "T_MED_01.病床数": {"$gte": 100}}),
    ("yokohama EXACT (ordinance city -> 0 expected)", "T_MED_00",
        {"市区町村": "横浜市", "分類コード": 0}),
    ("yokohama PREFIX (%) (ordinance city -> many)", "T_MED_00",
        {"市区町村": {"$like": "横浜市%"}, "分類コード": 0}),
]
for name, base, where in COUNT_CASES:
    mcp_n = server.wellness_count(base_table=base, where=where)["count"]
    eff = where or {"WELLNESS_NO": {"$gte": 0}}
    joins = server._auto_joins(where, None)
    api = query(base_table=base, joins=joins, where=eff, limit=1)
    api_total = api.get("total")
    check(f"count: {name}  (MCP={mcp_n}, API={api_total})", mcp_n == api_total)

# --------------------------------------------------------------------------------------
print("\n=== 5. GOLDEN VALUES (documented expected numbers — catch silent data/logic drift) ===")
# from MCP.md / ASYNC.md, verified 2026-06-26. If the DB changes these may legitimately move;
# update them deliberately when that happens.
GOLDEN = [
    ("all facilities == 105593", {"WELLNESS_NO": {"$gte": 0}}, None, 105593),
    ("Tokyo hospitals == 517", {"都道府県コード": 13, "分類コード": 0}, None, 517),
    ("Kanagawa hospitals == 297", {"都道府県コード": 14, "分類コード": 0}, None, 297),
    ("OR 13|27 == 15326", {"$or": [{"都道府県コード": 13}, {"都道府県コード": 27}]}, None, 15326),
]
for name, where, joins, expected in GOLDEN:
    n = server.wellness_count(base_table="T_MED_00", where=where, joins=joins)["count"]
    check(f"golden: {name}  (got {n})", n == expected)

# --------------------------------------------------------------------------------------
print("\n=== 6. ERROR PARITY: MCP surfaces the API's errors (not silent / not different) ===")
# invalid table
try:
    server.wellness_query(base_table="T_MED_99", where={"WELLNESS_NO": 1})
    check("invalid table raises", False, "no error raised")
except Exception as e:
    check("invalid table raises an error", True)
# bad operator -> API 400, message should propagate
try:
    server.wellness_count(where={"都道府県コード": {"$fake": 13}})
    check("bad operator raises", False, "no error raised")
except Exception as e:
    check("bad operator raises with API message", "$fake" in str(e) or "演算子" in str(e), str(e)[:80])

# --------------------------------------------------------------------------------------
print("\n=== 7. JOIN + FLATTEN: requesting a joined field auto-joins and returns the value ===")
raw = query(base_table="T_MED_00", joins=["T_MED_01"], where={"WELLNESS_NO": 124}, limit=1)
api_rec = server._flatten(raw["data"][0])
mcp = server.wellness_query(base_table="T_MED_00", where={"WELLNESS_NO": 124},
                            fields=["正式名称", "病床数"])  # 病床数 lives in T_MED_01 -> auto-join
mrow = mcp["data"][0]
check("auto-join: 病床数 present & == API", norm(mrow.get("病床数")) == norm(api_rec.get("病床数")),
      f"MCP={mrow.get('病床数')} API={api_rec.get('病床数')}")

# --------------------------------------------------------------------------------------
print("\n=== 7b. AGGREGATE: wellness_aggregate distinct/group-by == independent code count ===")
KN = {"都道府県コード": 14, "分類コード": 0}   # Kanagawa hospitals
# independent truth: fetch rows ourselves and dedupe
_raw = query(base_table="T_MED_00", joins=["T_MED_04"], where=KN, limit=1000)
_rows = [server._flatten(r) for r in _raw.get("data", [])]
def _distinct(field):
    return len({r.get(field) for r in _rows if r.get(field) not in (None, "")})
agg_name = server.wellness_aggregate(where=KN, count_distinct="法人名称")
check(f"aggregate: distinct 法人名称 == code count ({_distinct('法人名称')})",
      agg_name.get("distinct_count") == _distinct("法人名称"))
agg_keiei = server.wellness_aggregate(where=KN, count_distinct="経営体")
check(f"aggregate: distinct 経営体 == code count ({_distinct('経営体')})",
      agg_keiei.get("distinct_count") == _distinct("経営体"))
agg_grp = server.wellness_aggregate(where=KN, group_by="開設元")
indep_groups = len({r.get("開設元") for r in _rows if r.get("開設元") not in (None, "")})
check(f"aggregate: group_by 開設元 group_count == code ({indep_groups})",
      agg_grp.get("group_count") == indep_groups)
check("aggregate: group_by totals sum to rows_scanned-with-value",
      sum(agg_grp.get("groups", {}).values()) == sum(1 for r in _rows if r.get("開設元") not in (None, "")))
# group_by on a JOINED-table field must resolve (any field, not just curated) -> non-empty
TKH = {"都道府県コード": 13, "分類コード": 0}   # Tokyo hospitals
_jr = [server._flatten(r) for r in
       query(base_table="T_MED_00", joins=["T_MED_01"], where=TKH, limit=1000).get("data", [])]
_indep = {}
for r in _jr:
    v = r.get("電子カルテ導入有無")
    if v not in (None, ""):
        _indep[v] = _indep.get(v, 0) + 1
agg_join = server.wellness_aggregate(where=TKH, group_by="電子カルテ導入有無")  # field in T_MED_01
check("aggregate: group_by joined-table field (電子カルテ導入有無) resolves & matches",
      agg_join.get("groups") == {str(k) if not isinstance(k, str) else k: v
                                 for k, v in sorted(_indep.items(), key=lambda kv: kv[1], reverse=True)}
      or agg_join.get("groups") == dict(sorted(_indep.items(), key=lambda kv: kv[1], reverse=True)),
      f"got {agg_join.get('groups')} vs {_indep}")

# safety guard must refuse a too-big set, not flood the API
guard = server.wellness_aggregate(where=None, count_distinct="正式名称")
check("aggregate: guard refuses >AGG_MAX_ROWS sets", "error" in guard and guard.get("matched", 0) > server.AGG_MAX_ROWS)


def check_live():
    print("\n=== 8. LIVE PRODUCTION endpoint (deployed server, end-to-end over MCP protocol) ===")
    import asyncio
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    URL = os.getenv("MCP_URL", "https://wellness-mcp-production.up.railway.app/mcp")
    TOKEN = os.getenv("MCP_AUTH_TOKEN", "")
    if not TOKEN:
        check("live: MCP_AUTH_TOKEN set", False, "set MCP_AUTH_TOKEN env to run --live")
        return
    async def run():
        headers = {"Authorization": f"Bearer {TOKEN}"}
        async with streamablehttp_client(URL, headers=headers) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                d = json.loads((await s.call_tool("describe_table", {"table": "T_MED_02"})).content[0].text)
                check("live: describe_table(T_MED_02) >= 20 cols (fix deployed)",
                      len(d.get("columns", [])) >= 20, f"{len(d.get('columns', []))} cols")
                q = json.loads((await s.call_tool("wellness_query",
                      {"base_table": "T_MED_02", "where": {"WELLNESS_NO": 124}})).content[0].text)
                row = q["data"][0] if q.get("data") else {}
                nn = [k for k, v in row.items() if v is not None and k != "WELLNESS_NO"]
                check("live: T_MED_02/124 returns real data (not all null)", len(nn) > 1, f"{len(nn)} non-null")
                c = json.loads((await s.call_tool("wellness_count",
                      {"where": {"都道府県コード": 13, "分類コード": 0}})).content[0].text)
                check("live: Tokyo hospitals == 517", c.get("count") == 517, f"got {c.get('count')}")
    asyncio.run(run())

if "--live" in sys.argv:
    check_live()

# --------------------------------------------------------------------------------------
print("\n" + "=" * 70)
print(f"RESULT: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:")
    for f in FAIL:
        print("   -", f)
print("=" * 70)
sys.exit(1 if FAIL else 0)
