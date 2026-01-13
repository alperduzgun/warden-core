"""
Token Bucket Rate Limiter for LLM.

Prevents exhausting TPM (Tokens Per Minute) and RPM (Requests Per Minute) quotas
by proactively suspending execution before requests are sent.
"""

import asyncio
import time
from typing import Optional, Tuple
from dataclasses import dataclass
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class RateLimitConfig:
    """Rate limit configuration."""
    tpm: int = 1000  # Tokens Per Minute
    rpm: int = 6     # Requests Per Minute
    burst: int = 1   # Max concurrent requests (bucket size)


class RateLimiter:
    """
    Token Bucket Rate Limiter.
    
    Manages two buckets:
    1. Tokens (TPM)
    2. Requests (RPM)
    """

    def __init__(self, config: RateLimitConfig):
        self.config = config
        
        # Token Bucket
        self._tokens = float(config.tpm)
        self._last_token_refill = time.time()
        
        # Request Bucket - Capacity is burst, Rate is rpm
        self._requests = float(config.burst)
        self._last_request_refill = time.time()
        
        # Lock will be lazily initialized to avoid event loop binding issues
        self._lock: Optional[asyncio.Lock] = None
        
        logger.info(
            "rate_limiter_initialized",
            tpm=config.tpm,
            rpm=config.rpm,
            burst=config.burst
        )

    def _get_lock(self) -> asyncio.Lock:
        """Get or create the asyncio lock (lazy initialization)."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def _refill_async(self):
        """Refill buckets based on time elapsed."""
        now = time.time()
        
        # Refill Tokens
        elapsed_tokens = now - self._last_token_refill
        token_rate = self.config.tpm / 60.0  # Tokens per second
        new_tokens = elapsed_tokens * token_rate
        
        if new_tokens > 0:
            self._tokens = min(self.config.tpm, self._tokens + new_tokens)
            self._last_token_refill = now
            
        # Refill Requests
        elapsed_requests = now - self._last_request_refill
        request_rate = self.config.rpm / 60.0
        new_requests = elapsed_requests * request_rate
        
        if new_requests > 0:
            # Cap at burst size, not RPM
            self._requests = min(self.config.burst, self._requests + new_requests)
            self._last_request_refill = now

    async def acquire_async(self, estimated_tokens: int) -> float:
        """
        Acquire permission to send a request.
        
        Args:
            estimated_tokens: Estimated token cost of the request
            
        Returns:
            Wait time in seconds (0.0 if immediate)
        """
        async with self._get_lock():
            await self._refill_async()
            
            wait_time = 0.0
            
            # Check Request Quota
            if self._requests < 1:
                # Calculate wait for 1 request
                needed = 1.0 - self._requests
                rate = self.config.rpm / 60.0
                req_wait = needed / rate
                wait_time = max(wait_time, req_wait)
                
            # Check Token Quota
            if self._tokens < estimated_tokens:
                # Calculate wait for needed tokens
                needed = estimated_tokens - self._tokens
                rate = self.config.tpm / 60.0
                if rate > 0:
                    token_wait = needed / rate
                    wait_time = max(wait_time, token_wait)
                else:
                    # Should not happen if TPM > 0
                    wait_time = 3600.0 

            # ADAPTIVE PACING (Flow Control)
            # Slow down execution as we approach capacity limits to avoid API "burst" bans.
            # This is smoother than hitting a hard wall and waiting 60s.
            if self.config.tpm > 0:
                token_utilization = 1.0 - (self._tokens / self.config.tpm)
                
                if token_utilization > 0.95:
                    # >95% capacity used: Emergency braking
                    # API is likely to throttle us massively if we send now.
                    pacing_delay = 5.0
                    if pacing_delay > wait_time:
                        logger.warning("adaptive_pacing_emergency", usage=f"{token_utilization*100:.1f}%", delay=pacing_delay)
                        wait_time = pacing_delay
                        
                elif token_utilization > 0.85:
                    # >85% capacity used: Heavy braking
                    pacing_delay = 1.5
                    if pacing_delay > wait_time:
                        logger.info("adaptive_pacing_heavy", usage=f"{token_utilization*100:.1f}%", delay=pacing_delay)
                        wait_time = pacing_delay
                        
                elif token_utilization > 0.70:
                    # >70% capacity used: Light feathering
                    pacing_delay = 0.2
                    if pacing_delay > wait_time:
                         wait_time = pacing_delay

            if wait_time > 0:
                logger.warning(
                    "rate_limit_throttle",
                    wait_seconds=f"{wait_time:.2f}",
                    reason="quota_exceeded",
                    needed_tokens=estimated_tokens,
                    available_tokens=int(self._tokens),
                )
                
                # We do NOT consume here because we verify *after* returning
                # But to maintain the contract, we should consume if we return success.
                # In this simpler implementation, we'll sleep immediately.
                
                # NOTE: For true strictness, we should sleep INSIDE the lock?
                # No, sleeping inside lock blocks all other tasks.
                # We should return wait time, sleep OUTSIDE, then acquire again?
                # Or use a condition variable.
                
                # Simple approach: Sleep then consume (recursive verify)
                pass 

        if wait_time > 0:
            await asyncio.sleep(wait_time + 0.1)  # Add small buffer
            return await self.acquire_async(estimated_tokens)

        # Consume execution cost
        async with self._get_lock():
            # Re-check in case another task stole it (rare in single loop, but robust)
            await self._refill_async()
            if self._requests >= 1 and self._tokens >= estimated_tokens:
                self._requests -= 1
                self._tokens -= estimated_tokens
                return 0.0
            else:
                # Lost the race, try again
                return await self.acquire_async(estimated_tokens)
