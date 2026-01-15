
import unittest
import tempfile
import yaml
import shutil
from pathlib import Path
from warden.rules.defaults.loader import DefaultRulesLoader

class TestDynamicRulesLoader(unittest.TestCase):
    def setUp(self):
        self.loader = DefaultRulesLoader()
        self.test_dir = Path(tempfile.mkdtemp())
        self.loader.rules_dir = self.test_dir
        
        # Create python/fastapi.yaml
        self.python_dir = self.test_dir / "python"
        self.python_dir.mkdir()
        
        self.rule_data = {
            "rules": [
                {
                    "id": "fastapi-rule-1",
                    "name": "FastAPI Check",
                    "activation": {
                        "framework": "fastapi"
                    },
                    "tags": ["security"],
                    "pattern": "foo",
                    "severity": "high"
                },
                {
                    "id": "generic-rule-1",
                    "name": "Generic Check",
                    "tags": ["security"],
                    "pattern": "bar",
                    "severity": "medium"
                }
            ]
        }
        
        with open(self.python_dir / "test.yaml", "w") as f:
            yaml.dump(self.rule_data, f)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_context_filtering_match(self):
        # Should load BOTH rules (generic + fastapi matched)
        rules = self.loader.get_rules_for_language("python", context_tags={"framework": "fastapi"})
        ids = [r.id for r in rules]
        self.assertIn("fastapi-rule-1", ids)
        self.assertIn("generic-rule-1", ids)

    def test_context_filtering_mismatch(self):
        # Should load ONLY generic rule (fastapi mismatched)
        rules = self.loader.get_rules_for_language("python", context_tags={"framework": "django"})
        ids = [r.id for r in rules]
        self.assertNotIn("fastapi-rule-1", ids)
        self.assertIn("generic-rule-1", ids)

    def test_no_context(self):
        # Strict Logic: If no context provided, rules with activation requirements must be SKIPPED.
        # This prevents accidental loading of framework-specific rules in generic contexts.
        rules = self.loader.get_rules_for_language("python", context_tags=None)
        ids = [r.id for r in rules]
        self.assertNotIn("fastapi-rule-1", ids)
        self.assertIn("generic-rule-1", ids)

if __name__ == '__main__':
    unittest.main_async()
