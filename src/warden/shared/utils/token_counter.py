"""Real token counting with tiktoken (ID 22)."""
import tiktoken
class TokenCounter:
    def __init__(self):
        self.enc = tiktoken.get_encoding("cl100k_base")
    def count(self, text: str) -> int:
        return len(self.enc.encode(text))
    def estimate_max(self, text: str, max_tokens: int) -> str:
        tokens = self.count(text)
        if tokens > max_tokens:
            chars_per_token = len(text) / tokens
            return text[:int(max_tokens * chars_per_token)]
        return text
