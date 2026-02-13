"""API endpoint handlers."""
import json

def parse_request(body: str) -> dict:
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"error": "Invalid JSON"}

def format_response(data: dict, status: int = 200) -> dict:
    return {"status": status, "data": data}

def validate_input(data: dict, required_fields: list) -> list:
    missing = [f for f in required_fields if f not in data]
    return missing
