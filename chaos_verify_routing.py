
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import sys
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("warden.chaos")

class ChaosResult:
    def __init__(self, scenario, passed, details=""):
        self.scenario = scenario
        self.passed = passed
        self.details = details

async def run_scenario(name, func):
    logger.info(f"🧪 Scenario: {name}")
    try:
        await func()
        print(f"   Result: ✅ PASS")
        return ChaosResult(name, True)
    except Exception as e:
        print(f"   Result: ❌ FAIL ({str(e)})")
        return ChaosResult(name, False, str(e))

# Mocking dependent classes
class MockRateLimiter:
    async def acquire_async(self, tokens):
        pass

class MockLLMService:
    def __init__(self, provider="MOCK"):
        self.provider = provider
        self.endpoint = "http://localhost:11434"
    
    async def complete_async(self, prompt, system_prompt=None, model=None, use_fast_tier=False):
        return MagicMock(success=True)

# We need to import the class to test logic, but we can't easily instantiate it without dependencies.
# So we will subclass it with mocks in mind or just test the logic if isolated.
# Actually, the logic is in `_call_llm_with_retry_async`.

# Import the actual class
from warden.analysis.application.llm_phase_base import LLMPhaseBase, LLMPhaseConfig

class TestLLMPhase(LLMPhaseBase):
    def phase_name(self): return "CHAOS_TEST"
    def get_system_prompt(self): return ""
    def format_user_prompt(self, context): return ""
    def parse_llm_response(self, response): return response

async def test_borderline_upgrade():
    """Test: Tokens just above threshold (2000) should trigger upgrade."""
    phase = TestLLMPhase(
        llm_service=MockLLMService("OLLAMA"),
        rate_limiter=MockRateLimiter()
    )
    phase.tokenizer = MagicMock()
    # Mock encode to return 2001 tokens
    phase.tokenizer.encode.return_value = [1] * (2001 - phase.config.max_tokens - 100) # Math: 2001 = tokens + max(800) + buffer(100) -> 1101 input

    # Mock the LLM call to capture arguments
    phase.llm.complete_async = AsyncMock(return_value=MagicMock(success=True))

    await phase._call_llm_with_retry_async(
        system_prompt="sys", 
        user_prompt="user", 
        use_fast_tier=True # Requesting Fast Tier
    )
    
    # Verify: valid call was made
    call_args = phase.llm.complete_async.call_args
    # call_args.kwargs['use_fast_tier'] SHOULD BE False (Upgraded)
    used_fast_tier = call_args.kwargs.get('use_fast_tier')
    
    if used_fast_tier is not False:
        raise Exception(f"Expected use_fast_tier=False (Upgraded), but got {used_fast_tier}")

async def test_no_upgrade_below_limit():
    """Test: Tokens below threshold (2000) should NOT trigger upgrade."""
    phase = TestLLMPhase(
        llm_service=MockLLMService("OLLAMA"),
        rate_limiter=MockRateLimiter()
    )
    phase.tokenizer = MagicMock()
    # Mock encode to return 1500 tokens
    phase.tokenizer.encode.return_value = [1] * 500

    phase.llm.complete_async = AsyncMock(return_value=MagicMock(success=True))

    await phase._call_llm_with_retry_async(
        system_prompt="sys", 
        user_prompt="user", 
        use_fast_tier=True
    )
    
    # Verify
    call_args = phase.llm.complete_async.call_args
    used_fast_tier = call_args.kwargs.get('use_fast_tier')
    
    if used_fast_tier is not True:
        raise Exception(f"Expected use_fast_tier=True (Preserved), but got {used_fast_tier}")

async def test_no_tokenizer_fallback():
    """Test: Missing Tokenizer falls back to char count (~4 chars/token)."""
    phase = TestLLMPhase(
        llm_service=MockLLMService("OLLAMA"),
        rate_limiter=MockRateLimiter()
    )
    phase.tokenizer = None # Simulate missing tiktoken

    # Limit is 2000 tokens. 
    # Fallback math: (len(text) // 4) + max_tokens(800) + 50
    # Threshold 2000.  2000 - 850 = 1150 capacity.
    # 1150 * 4 = 4600 chars in input to trigger.
    
    huge_input = "a" * 8000 # ~2000 + 850 = 2850 tokens -> Should upgrade

    phase.llm.complete_async = AsyncMock(return_value=MagicMock(success=True))

    await phase._call_llm_with_retry_async(
        system_prompt="", 
        user_prompt=huge_input, 
        use_fast_tier=True
    )
    
    call_args = phase.llm.complete_async.call_args
    used_fast_tier = call_args.kwargs.get('use_fast_tier')
    
    if used_fast_tier is not False:
        raise Exception(f"Expected upgrade fallback char count, but got {used_fast_tier}")

async def main():
    print("🌪️ Starting Chaos Verification for Smart Routing...")
    results = []
    results.append(await run_scenario("Borderline Upgrade Check", test_borderline_upgrade))
    results.append(await run_scenario("Safe Zone Preserved", test_no_upgrade_below_limit))
    results.append(await run_scenario("No-Tokenizer Fallback", test_no_tokenizer_fallback))
    
    failures = [r for r in results if not r.passed]
    if failures:
        print(f"\n--- Summary: {len(failures)} Failures ---")
        sys.exit(1)
    else:
        print("\n--- Summary: 0 Failures (All Passed) ---")
        sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())
