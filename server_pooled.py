import sys
import os
import re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP
from wellness.client_async import query   # async (httpx) twin of wellness.client


# ─────────────────────────────────────────────────────────────────────────────
# PERFORMANCE CANDIDATE — for a SEPARATE Railway staging service only.
# Same tools / behaviour / output / errors as server.py, BUT built for concurrency:
#   • async tools + httpx (non-blocking I/O)
#   • stateless_http=True  → each request independent (safe across worker processes)
#   • module-level `app`   → run with MULTIPLE uvicorn workers:
#         uvicorn server_pooled:app --host 0.0.0.0 --port $PORT --workers 3
# Production (server.py / wellness/client.py) is NOT touched and NOT affected.
# ─────────────────────────────────────────────────────────────────────────────


AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN")

DEFAULT_FIELDS = ["正式名称", "都道府県", "市区町村", "町番地", "TEL"]


class BearerAuthMiddleware:
    def __init__(self, app, token):
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        provided = headers.get(b"authorization", b"").decode()
        if provided == f"Bearer {self.token}":
            return await self.app(scope, receive, send)
        await send({"type": "http.response.start", "status": 401,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})


INSTRUCTIONS = """\
WELLNESS — Japanese healthcare facility database (hospitals, clinics, doctors,
departments, addresses, beds, staff). Always use these tools, never web search.

HOW TO ANSWER (follow exactly):
- LANGUAGE: answer in Japanese (the customers are Japanese). Translate the answer
  formats below into natural Japanese, e.g. "東京都の病院：517件",
  "Xに病院は見つかりませんでした". Only reply in another language if the user clearly
  writes in it.
- "how many / count / number of ..." → call wellness_count → reply with ONE short line
  that RESTATES what was counted (include the filter), then the number,
  e.g. "Hospitals in Tokyo with 100+ beds: 342". No table, no list, no steps.
- For an OR / multi-part count ("A or B"), show the breakdown, not just the total,
  e.g. "Tokyo 517 + Osaka 429 = 946".
- "list / names of / which ..." → call wellness_query with fields=["正式名称"] →
  reply with ONLY a plain list of names. The tool returns at most 20; if a `note`
  field is present, relay it professionally — state the total, show the 20, and offer
  to narrow / show more.
- LARGE REQUESTS: if the user asks for many records (e.g. "give me 500 hospitals",
  "全部ちょうだい", a big list), do NOT dump them in chat. First ask HOW they want it:
  「①このチャットに表示 ②Excelファイル ③CSVファイル のどれがよろしいですか？」then deliver
  in that format.
- "details / show / info about ..." → call wellness_query with the few relevant
  fields → reply with ONE clean markdown table.
- If the result is empty / count is 0, say so plainly, e.g. "No hospitals found in X."
  Never reply with a bare "0" or an empty list.
- If the question is ambiguous (unclear place or filter), ask ONE short clarifying
  question instead of guessing.
- Never print WELLNESS_NO unless explicitly asked.
- Never describe your query steps, tool calls, or reasoning. No "Here are...",
  no preamble. Output only the final answer.

FACILITY TYPE — map the user's word to 分類コード (a T_MED_00 column). This is
REQUIRED for correct counts:
- "病院" / "hospital"                 → {"分類コード": 0}
- "診療所" / "クリニック" / "clinic"   → {"分類コード": 1}
- "歯科" / "dental"                   → {"分類コード": 2}
- "施設" / "医療機関" / "facility", or no type word → do NOT filter by 分類コード
  (counts every type).
Example: "how many hospitals in Kanagawa" → {"都道府県コード": 14, "分類コード": 0}
→ 297. Without 分類コード it would wrongly return all 5901 facilities.

FILTERING ACROSS TABLES — do it in ONE call. Beds are in T_MED_01, prefecture is
in T_MED_00. Join the table and prefix the column:
    base_table="T_MED_00", joins=["T_MED_01"],
    where={"都道府県コード": 13, "分類コード": 0, "T_MED_01.病床数": {"$gte": 100}}
NEVER fetch all rows and filter/count manually — the API does it and returns an
exact total."""

mcp = FastMCP(
    "wellness",
    instructions=INSTRUCTIONS,
    host="0.0.0.0",
    port=int(os.getenv("PORT", 8000)),
    stateless_http=True,   # ← independent requests; safe with multiple workers
)

PREF = "13=東京都 14=神奈川県 27=大阪府 1=北海道 40=福岡県 23=愛知県 28=兵庫県"

FIELD_TABLE = {
    "診療科目": "T_MED_01", "病床数": "T_MED_01", "一般病床数": "T_MED_01",
    "診療時間午前": "T_MED_01", "診療時間午後": "T_MED_01", "休診日": "T_MED_01",
    "院内処方の有無": "T_MED_01", "院外処方の有無": "T_MED_01",
    "科目": "T_MED_13",
    "平均患者数_一般": "T_MED_03", "平均患者数_外来": "T_MED_03", "平均在院日数_一般": "T_MED_03",
    "法人名称": "T_MED_04", "法人番号": "T_MED_04",
}


def _auto_joins(where, joins, fields=None):
    found = set(joins or [])
    if where:
        for key in where:
            m = re.match(r"^(T_MED_\d{2})\.", str(key))
            if m:
                found.add(m.group(1))
    if fields:
        for f in fields:
            name = f.split(".", 1)[1] if "." in f else f
            if name in FIELD_TABLE:
                found.add(FIELD_TABLE[name])
    return sorted(found) or None


def _flatten(record):
    flat = {}
    for k, v in record.items():
        if isinstance(v, list):
            if v and isinstance(v[0], dict):
                for row in v:
                    for kk, vv in row.items():
                        if kk != "WELLNESS_NO":
                            if kk in flat:
                                flat[kk] = str(flat[kk]) + ", " + str(vv)
                            else:
                                flat[kk] = vv
        elif isinstance(v, dict):
            for kk, vv in v.items():
                if kk != "WELLNESS_NO":
                    flat.setdefault(kk, vv)
        else:
            flat[k] = v
    return flat


def _project(record, fields):
    if not fields:
        return record
    out = {}
    for f in fields:
        name = f.split(".", 1)[1] if "." in f else f
        out[name] = record.get(name)
    return out


@mcp.tool()
async def wellness_count(
    base_table: str = "T_MED_00",
    where: dict | None = None,
    joins: list[str] | None = None,
) -> dict:
    """
    Return ONLY the number of facilities matching the filter. Use this for every
    "how many", "count", or "number of" question — never fetch rows to count.

    Facility type: "hospital"→{"分類コード":0}, "clinic"→{"分類コード":1},
    "dental"→{"分類コード":2}. Omit 分類コード for "facility"/no type word.
    e.g. "how many hospitals in Kanagawa" → where={"都道府県コード":14,"分類コード":0}.

    Cross-table filters work in one call: prefix the joined column, e.g.
        where={"都道府県コード": 13, "T_MED_01.病床数": {"$gte": 100}}
    The needed join is added automatically. Returns {"count": N}.
    Present as ONE short line: what was counted + the number, e.g. "Hospitals in Tokyo: 517".
    """
    joins = _auto_joins(where, joins)
    eff_where = where or {"WELLNESS_NO": {"$gte": 0}}
    result = await query(base_table=base_table, joins=joins, where=eff_where, limit=1)
    if isinstance(result, dict) and "total" in result and result["total"] is not None:
        return {"count": result["total"]}
    raise RuntimeError(result.get("error", "Unknown error"))


@mcp.tool()
async def wellness_query(
    base_table: str = "T_MED_00",
    where: dict | None = None,
    fields: list[str] | None = None,
    joins: list[str] | None = None,
    order_by: dict | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """
    Fetch facility records. Use for "list", "names of", "which", or "details"
    questions. For a count, use wellness_count instead.

    ALWAYS pass `fields` with just the columns the answer needs — this keeps the
    output small. For a name list use fields=["正式名称"]; for a details table use
    e.g. fields=["正式名称","市区町村","TEL","病床数"]. Joined columns may be
    requested with a table prefix; the join is added automatically.

    Cross-table filtering in one call (do NOT loop / cross-reference manually):
        base_table="T_MED_00", where={"都道府県コード": 13,
                                       "T_MED_01.病床数": {"$gte": 100}},
        fields=["正式名称","病床数"], order_by={"column":"WELLNESS_NO","direction":"asc"}

    Facility type: "hospital"→{"分類コード":0}, "clinic"→{"分類コード":1},
    "dental"→{"分類コード":2}. Omit 分類コード for "facility"/no type word.

    base_table: T_MED_00 (default; name/address/prefecture) .. T_MED_13.
    where: conditions in ONE dict are combined with AND. For OR, use $or with a
           list: {"$or": [{"都道府県コード": 13}, {"都道府県コード": 27}]} (13 OR 27).
           Operators: $gte $lte $gt $lt $between [a,b] $like "%x%" $in [..] $or.
    limit: default 20, max 1000. offset: pagination. Response has exact `total`,
    and a `note` field when more rows exist (relay it: offer narrow / more / file export).
    Returns {"total": N, "returned": k, "data": [...]} with flat records.
    Show results as a plain list (names) or one markdown table (details). Never
    show WELLNESS_NO unless asked. Never explain the query.
    Prefecture: filter by name, e.g. {"都道府県": "神奈川県"} (or by code {"都道府県コード": 14}).
    """
    if fields is None:
        fields = DEFAULT_FIELDS
    joins = _auto_joins(where, joins, fields)
    result = await query(
        base_table=base_table,
        joins=joins,
        where=where,
        order_by=order_by,
        limit=limit,
        offset=offset,
    )
    if not isinstance(result, dict) or "data" not in result:
        message = result.get("error", "Unknown error") if isinstance(result, dict) else "Unknown error"
        raise RuntimeError(message)

    rows = [_project(_flatten(r), fields) for r in result.get("data", [])]
    out = {
        "total": result.get("total"),
        "returned": len(rows),
        "data": rows,
    }
    total = result.get("total") or 0
    if total > len(rows):
        out["note"] = (
            f"全{total}件中{len(rows)}件のみ表示しています。"
            f"続きが必要な場合は、(1)市区町村や条件で絞り込み、(2)件数を指定して追加表示、"
            f"または件数が多い場合は (3)Excel / CSV ファイルでの出力 をご案内してください。"
        )
    return out


@mcp.tool()
def list_tables() -> dict:
    """List all available tables in the Wellness database with their purpose."""
    return {
        "T_MED_00": "Base facility info - name, address, TEL, location, codes",
        "T_MED_01": "Medical info - departments, hours, bed count, prescriptions",
        "T_MED_02": "Services - payment methods, barrier-free, smoking, meals",
        "T_MED_03": "Patient stats - avg daily inpatient, outpatient, avg stay",
        "T_MED_04": "Corporation - legal entity name and address",
        "T_MED_05": "Staff - job type, role, value",
        "T_MED_06": "Procedures - area code and content code",
        "T_MED_07": "Home care - area code and content code",
        "T_MED_08": "Vaccinations - vaccination code",
        "T_MED_09": "厚生局 monthly data - WELLNESS_NO and ID",
        "T_MED_10": "Equipment - category code and content code",
        "T_MED_11": "Instructions - content code",
        "T_MED_12": "DPC info - MDC code, disease code, procedure code, value",
        "T_MED_13": "Departments - department name (科目)",
    }


@mcp.tool()
def describe_table(table: str) -> dict:
    """Return the column names for a given table. table: one of T_MED_00 to T_MED_13."""
    columns = {
        "T_MED_00": ["WELLNESS_NO","分類コード","正式名称","略式名称","略式名称カナ","略式名称英語","郵便番号","都道府県コード","市区町村コード","都道府県","市区町村","町番地","TEL","FAX","URL","KAI_CODE","経営体","開設元","開設元カナ","理事長名","交通機関","最寄駅","所要時間","駐車場有無","駐車場台数","無料台数","緯度","経度","緯度日本","経度日本","二次医療圏コード","二次医療圏","医療機関番号","指定年月日","登録年月日"],
        "T_MED_01": ["WELLNESS_NO","診療科目","診療時間午前","診療時間午後","休診日","病床数","一般病床数","院内処方の有無","院外処方の有無","セカンドオピニオン診療情報提供有無","セカンドオピニオン診察有無","電子カルテ導入有無","併設している介護施設","保有している施設設備","紹介重点医療機関","マイナンバーカード利用可否","電子処方箋","リフィル処方箋"],
        "T_MED_02": ["WELLNESS_NO","クレジットカード対応有無","対応クレジットカード","電子決済対応有無","バリアフリー化の実施の有無","多機能トイレの設置の有無","全面禁煙の有無","適時及び適温による食事の提供","オーダリングシステム_検査有無","オーダリングシステム_処方有無","電子資格確認"],
        "T_MED_03": ["WELLNESS_NO","平均患者数_一般","平均患者数_外来","平均在院日数_一般"],
        "T_MED_04": ["WELLNESS_NO","法人番号","法人名称","法人都道府県","法人市区町村","法人町番地"],
        "T_MED_05": ["WELLNESS_NO","職種区分","職種","値"],
        "T_MED_06": ["WELLNESS_NO","領域コード","内容コード"],
        "T_MED_07": ["WELLNESS_NO","対応領域コード","内容コード"],
        "T_MED_08": ["WELLNESS_NO","予防接種コード"],
        "T_MED_09": ["WELLNESS_NO","ID"],
        "T_MED_10": ["WELLNESS_NO","分類コード","内容コード"],
        "T_MED_11": ["WELLNESS_NO","内容コード"],
        "T_MED_12": ["WELLNESS_NO","MDCコード","疾患コード","術式コード","値"],
        "T_MED_13": ["WELLNESS_NO","科目"],
    }
    if table not in columns:
        return {"error": f"Unknown table: {table}"}
    return {"table": table, "columns": columns[table]}


# Module-level ASGI app — this is what `uvicorn server_pooled:app --workers N` runs.
_base_app = mcp.streamable_http_app()
app = BearerAuthMiddleware(_base_app, AUTH_TOKEN) if AUTH_TOKEN else _base_app


if __name__ == "__main__":
    # Local convenience: run with workers via an import string (required for workers).
    import uvicorn
    uvicorn.run(
        "server_pooled:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        workers=int(os.getenv("WEB_CONCURRENCY", "3")),
    )
