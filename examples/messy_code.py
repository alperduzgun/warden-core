import os
import sys

# This is a messy file with lots of issues.

def very_long_function_name_that_is_hard_to_read_and_understand(a, b, c, d, e, f, g, h):
    # This function is way too long and has too many arguments.
    if a > b:
        if c > d:
            if e > f:
                if g > h:
                    return "a > b and c > d and e > f and g > h"
    return "something else"

def another_function():
    # This function has a mix of tabs and spaces.
	# It also has some commented out code.
    # x = 1
    # y = 2
    return 1+2

class MyClass:
    def __init__(self):
        self.my_variable = 1
        self.another_variable = "hello"

    def my_method(self):
        # This method is also too long.
        # It has a lot of nested if statements.
        if self.my_variable > 0:
            if self.another_variable == "hello":
                if self.my_variable < 10:
                    if self.another_variable != "world":
                        return True
        return False

def function_with_magic_numbers():
    return 3.14159 * 5 * 5

# Inconsistent spacing
x=1
y  =  2
z =3

# Benchmark cache invalidation comment

# Code Simplifier Examples:

def old_style_formatting(name, age):
    """Old % formatting - should use f-strings."""
    message = "Hello %s, you are %d years old" % (name, age)
    return message

def format_method_example(user, count):
    """Using .format() - should use f-strings."""
    return "User {} has {} items".format(user, count)

def manual_list_building(items):
    """Manual list building - should use comprehension."""
    result = []
    for item in items:
        result.append(item.value)
    return result

def redundant_else_example(x):
    """Redundant else after return."""
    if x > 0:
        return x
    else:
        return 0