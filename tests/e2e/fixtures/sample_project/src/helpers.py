"""Utility helpers."""
import re
from datetime import datetime

def sanitize_filename(name: str) -> str:
    return re.sub(r'[^\w\-.]', '_', name)

def format_timestamp(dt: datetime) -> str:
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')

def chunk_list(lst: list, size: int) -> list:
    return [lst[i:i + size] for i in range(0, len(lst), size)]
