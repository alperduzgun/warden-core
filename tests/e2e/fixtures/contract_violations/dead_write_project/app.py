"""Project that writes a context field but never reads it."""


def process(context):
    context.unused_report = {"data": [1, 2, 3]}  # Written, never read
    context.result = context.findings  # result yazilip okunacak
    return context.result
