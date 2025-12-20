"""Sample Python file for testing Warden analyzer"""

def calculate_sum(a, b):
    # TODO: Add type hints
    print(f"Calculating sum of {a} and {b}")
    return a + b

def divide(x, y):
    try:
        result = x / y
    except:  # Bare except - bad practice!
        return None
    return result

class Calculator:
    def __init__(self):
        self.history = []

    def add(self, a, b):
        result = a + b
        self.history.append(result)
        return result
