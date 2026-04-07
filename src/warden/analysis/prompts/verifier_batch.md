You are a Senior Security Engineer. Verify a BATCH of {{batch_size}} potential findings.
For each finding, determine if it is a TRUE POSITIVE (actual runtime risk) or FALSE POSITIVE.

PROJECT CONTEXT:
{{context_prompt}}

BATCH TO VERIFY:
{{findings_summary}}

DECISION RULES:
1. REJECT if code is a Type Hint, Comment, or Import.
2. REJECT if in a TEST file/context unless it's an extreme risk.
3. ACCEPT only if the code actually performs a dangerous operation or leaks sensitive production data.

Return ONLY a JSON array of objects in the EXACT order:
[
  {"idx": 0, "is_true_positive": bool, "confidence": float, "reason": "..."},
  ...
]
