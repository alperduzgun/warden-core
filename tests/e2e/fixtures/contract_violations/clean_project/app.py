"""Project with balanced writes and reads."""


def process(context):
    context.output = context.input_data  # Both sides used
    return context.output
