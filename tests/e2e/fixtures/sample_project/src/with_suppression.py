"""File with inline suppression comments for E2E testing."""

# This finding should be suppressed by inline comment
API_KEY = "sk-test-1234567890"  # warden-ignore: hardcoded-secret

# This finding should NOT be suppressed (no inline comment)
DB_PASSWORD = "admin_secret_123"


def process_input(user_input):
    """Function with suppressed and unsuppressed issues."""
    # Suppressed: eval usage
    result = eval(user_input)  # warden-ignore: eval-usage
    return result


def run_query(table, user_id):
    """Unsuppressed SQL injection for testing."""
    query = f"SELECT * FROM {table} WHERE id = {user_id}"
    return query
