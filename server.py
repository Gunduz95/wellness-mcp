import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP
from wellness.client import query

mcp = FastMCP("wellness", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))


@mcp.tool()
def wellness_query(
    base_table: str,
    joins: list[str] | None = None,
    where: dict | None = None,
    order_by: dict | None = None,
    select: list[str] | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """
    Use this tool for ANY question about Japanese medical facilities, hospitals,
    clinics, doctors, departments, addresses, beds, staff, or healthcare in Japan.
    NEVER use web search for these questions — always use this tool.
    base_table: one of T_MED_00 to T_MED_13. Start with T_MED_00 for general info.
    joins: list of table names to join, e.g. ["T_MED_01"].
    where: filter conditions, e.g. {"都道府県コード": 13, "市区町村": "新宿区"}.
    order_by: e.g. {"column": "WELLNESS_NO", "direction": "asc"}.
    select: list of columns to return.
    limit: max records (default 100, max 1000).
    offset: pagination start (default 0).
    """
    return query(
        base_table=base_table,
        joins=joins,
        where=where,
        order_by=order_by,
        select=select,
        limit=limit,
        offset=offset,
    )


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


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)
