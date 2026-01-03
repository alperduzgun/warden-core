"""
Orphan Frame Test - Unused code detection.

This file contains intentionally unused imports, functions, and classes
to test the OrphanFrame detection capabilities.
"""

import os
import json
import sys  # 🟡 UNUSED IMPORT
from typing import List, Optional, Dict  # 🟡 Optional, Dict UNUSED


# 🟡 UNUSED FUNCTION - should be detected
def unused_helper_function():
    """This function is never called anywhere."""
    return "I am orphan code"


# 🟡 UNUSED FUNCTION - should be detected
def another_orphan(x: int, y: int) -> int:
    """Another unused function."""
    return x + y


# 🟡 UNUSED CLASS - should be detected
class OrphanService:
    """This class is never instantiated."""
    
    def __init__(self):
        self.name = "orphan"
    
    def do_nothing(self):
        return None


# ✅ USED FUNCTION
def used_function(items: List[str]) -> str:
    """This function is called in main."""
    return ", ".join(items)


# ✅ USED CLASS
class ActiveService:
    """This class is instantiated and used."""
    
    def process(self, data: str) -> str:
        return data.upper()


# 🟡 DEAD CODE after return
def function_with_dead_code() -> str:
    return "result"
    print("This will never execute")  # 🟡 DEAD CODE
    x = 1 + 1  # 🟡 DEAD CODE


def main():
    # Only these are actually used
    result = used_function(["a", "b", "c"])
    print(result)
    
    service = ActiveService()
    print(service.process("hello"))
    
    print(function_with_dead_code())


if __name__ == "__main__":
    main()
