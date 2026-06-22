import requests
import os 
from dotenv import load_dotenv

from pathlib import Path
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

API_URL = os.getenv("WELLNESS_API_URL")
API_KEY = os.getenv("WELLNESS_API_KEY")

VALID_TABLES = [f"T_MED_{i:02d}" for i in range(14)]

def query(base_table, joins=None, where=None, order_by=None, select=None, limit=100, offset=0):

    if base_table not in VALID_TABLES:

        return {"success": False, "error": f"Invalid table: {base_table}. Must be T_MED_00 to T_MED_13"}

    if limit < 1 or limit > 1000:
        return {"success": False, "error": "limit must be between 1 and 1000"}

    
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

    try:
        response = requests.post(
            API_URL,
            headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
            json=body,
            timeout=30
        )
        response.encoding = "utf-8"
        response.raise_for_status()
        return response.json()
    except requests.Timeout:
        return {"success": False, "error": "API timeout — no response in 30 seconds"}
    except requests.HTTPError:
        try:
            error = response.json()
            error_message = error.get("error") or "Unknown API error"

        except ValueError:
            error_message = response.text or "Unknown API error"

        return {
            "success": False,
            "error": f"API request failed (http {response.status_code}): {error_message}"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}




