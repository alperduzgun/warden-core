"""Test file for CLI validation"""

import os
import sys
from typing import List, Optional

# Unused import - should be detected by OrphanFrame
import json


def calculate_sum(numbers: List[int]) -> int:
    """Calculate the sum of numbers"""
    total = 0
    for num in numbers:
        total += num
    return total


def unused_function():
    """This function is never called - should be detected by OrphanFrame"""
    return "I am lonely"


class Calculator:
    """Simple calculator class"""

    def __init__(self):
        self.result = 0

    def add(self, a: int, b: int) -> int:
        """Add two numbers"""
        # Potential issue: no input validation
        return a + b

    def divide(self, a: int, b: int) -> float:
        """Divide two numbers"""
        # Security issue: no zero check
        return a / b


def main():
    """Main function"""
    numbers = [1, 2, 3, 4, 5]
    result = calculate_sum(numbers)
    print(f"Sum: {result}")

    calc = Calculator()
    print(calc.add(10, 20))
    # Dangerous: potential division by zero
    print(calc.divide(10, 0))


if __name__ == "__main__":
    main()