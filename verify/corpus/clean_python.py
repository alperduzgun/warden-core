"""
Clean code: no vulnerabilities expected.

corpus_labels:
  sql-injection: 0
  xss: 0
  hardcoded-password: 0
  weak-crypto: 0
  taint-analysis: 0
  command-injection: 0
"""

import logging
import math
from typing import Union

logger = logging.getLogger(__name__)

Number = Union[int, float]


class Calculator:
    """A simple calculator with proper error handling."""

    def add(self, a: Number, b: Number) -> Number:
        result = a + b
        logger.debug("add(%s, %s) = %s", a, b, result)
        return result

    def multiply(self, a: Number, b: Number) -> Number:
        result = a * b
        logger.debug("multiply(%s, %s) = %s", a, b, result)
        return result

    def divide(self, a: Number, b: Number) -> float:
        if b == 0:
            raise ValueError("Cannot divide by zero")
        result = a / b
        logger.debug("divide(%s, %s) = %s", a, b, result)
        return result

    def sqrt(self, n: Number) -> float:
        if n < 0:
            raise ValueError("Cannot take square root of negative number")
        result = math.sqrt(n)
        logger.debug("sqrt(%s) = %s", n, result)
        return result
