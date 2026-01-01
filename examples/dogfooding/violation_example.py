"""
Intentionally vulnerable code to demonstrate Warden's 
Context-Aware Service Abstraction Detection.

Since Warden detects 'SecretManager' in this project, 
it should flag the direct usage of 'os.getenv' below.
"""

import os
import json

def get_api_key():
    # ❌ VIOLATION: Project has SecretManager, but we are using os.getenv directly.
    # Warden should report: "Use SecretManager instead of direct 'os.getenv'"
    return os.getenv("OPENAI_API_KEY")

def load_config():
    # ❌ VIOLATION: Project has ConfigManager (likely), checking for yaml/json load bypass
    with open("config.json") as f:
        return json.load(f)
