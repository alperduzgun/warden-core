"""Rate limiter for LLM API calls (ID 17)."""
import asyncio, time
class TokenBucketLimiter:
    def __init__(self, tpm=60, burst=10):
        self.tpm, self.burst, self.tokens = tpm, burst, burst
        self.last = time.time()
    async def acquire(self, n=1):
        elapsed = time.time() - self.last
        self.tokens = min(self.burst, self.tokens + elapsed * self.tpm / 60)
        self.last = time.time()
        if self.tokens < n:
            await asyncio.sleep((n - self.tokens) * 60 / self.tpm)
