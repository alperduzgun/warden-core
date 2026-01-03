"""
Property Frame Test - Property-based testing detection.

This file contains functions that would benefit from property-based testing
but currently lack proper validation and edge case handling.
"""

from typing import List, Optional


# 🔴 NO INPUT VALIDATION - Property test would catch edge cases
def divide(a: int, b: int) -> float:
    """Division without zero check."""
    return a / b  # Will crash on b=0


# 🔴 NO BOUNDS CHECKING - Property test would find index errors  
def get_element(items: List[str], index: int) -> str:
    """Gets element without bounds check."""
    return items[index]  # Will crash on invalid index


# 🔴 STRING MANIPULATION WITHOUT VALIDATION
def parse_user_input(data: str) -> dict:
    """Parses user input unsafely."""
    parts = data.split(":")
    return {
        "name": parts[0],
        "value": parts[1]  # 🔴 Assumes at least 2 parts
    }


# 🔴 NO NULL/EMPTY HANDLING
def process_items(items: Optional[List[str]]) -> int:
    """Processes items without null check."""
    return len(items)  # Will crash on None


# 🔴 NUMERIC OVERFLOW POTENTIAL
def calculate_factorial(n: int) -> int:
    """Calculates factorial without overflow protection."""
    if n <= 1:
        return 1
    return n * calculate_factorial(n - 1)  # Stack overflow on large n


# ✅ GOOD PATTERN - Proper validation
def safe_divide(a: int, b: int) -> Optional[float]:
    """Safe division with zero check."""
    if b == 0:
        return None
    return a / b


# ✅ GOOD PATTERN - Bounds checking
def safe_get_element(items: List[str], index: int) -> Optional[str]:
    """Safe element access with bounds check."""
    if not items or index < 0 or index >= len(items):
        return None
    return items[index]


if __name__ == "__main__":
    # These demonstrate the issues
    print(divide(10, 2))
    print(get_element(["a", "b"], 0))
