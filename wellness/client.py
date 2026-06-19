import requests
import os 
from dotenv import load_dotenv

from pathlib import Path
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

API_URL = os.getenv("WELLNESS_API_URL")
API_KEY = os.getenv("WELLNESS_API_KEY")

def query(base_table, joins=None, where=None, order_by=None, select=None, limit=100, offset=0):
    
    body ={
        "baseTable":base_table,
        "limit":limit,
        "offset":offset
    }

    if select:
        body["select"] = select


    if joins:
        body["joins"] = [{"table":t,"type":"LEFT"} for t in joins]

    if where:
        body["where"] = where

    if order_by:
        body["orderBy"] = order_by

    response = requests.post(

        API_URL,
        headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
        json=body,
    )
    response.encoding = "utf-8"

    try:
        return response.json()
    except Exception as e:
        return {"success": False, "error": f"HTTP {response.status_code} — {e}"}


