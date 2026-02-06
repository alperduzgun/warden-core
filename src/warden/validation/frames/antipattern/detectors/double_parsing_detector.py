"""Remove double parsing (ID 38)."""
class DoubleParsingDetector:
    def __init__(self, ast_cache): self.cache = ast_cache
