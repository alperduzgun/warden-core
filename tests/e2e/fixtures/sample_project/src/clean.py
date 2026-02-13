"""Clean Python file — should produce zero critical findings."""
from typing import List


def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


def filter_positive(numbers: List[int]) -> List[int]:
    """Return only positive numbers."""
    return [n for n in numbers if n > 0]
