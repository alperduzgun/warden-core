"""Tests for ErrorClassifier."""

from __future__ import annotations

from warden.self_healing.classifier import ErrorClassifier
from warden.self_healing.models import ErrorCategory, HealingRecord


class TestClassify:
    def setup_method(self):
        self.classifier = ErrorClassifier()

    def test_module_not_found_error(self):
        err = ModuleNotFoundError("No module named 'tiktoken'")
        assert self.classifier.classify(err) == ErrorCategory.MODULE_NOT_FOUND

    def test_import_error(self):
        err = ImportError("cannot import name 'foo' from 'bar'")
        assert self.classifier.classify(err) == ErrorCategory.IMPORT_ERROR

    def test_permission_error(self):
        err = PermissionError("Permission denied: '/etc/shadow'")
        assert self.classifier.classify(err) == ErrorCategory.PERMISSION_ERROR

    def test_timeout_error(self):
        err = TimeoutError("connection timed out")
        assert self.classifier.classify(err) == ErrorCategory.TIMEOUT

    def test_timeout_in_message(self):
        err = Exception("Operation timed out after 30s")
        assert self.classifier.classify(err) == ErrorCategory.TIMEOUT

    def test_external_service_error(self):
        err = ConnectionRefusedError("Connection refused")
        assert self.classifier.classify(err) == ErrorCategory.EXTERNAL_SERVICE

    def test_external_service_in_message(self):
        err = Exception("503 Service Unavailable")
        assert self.classifier.classify(err) == ErrorCategory.EXTERNAL_SERVICE

    def test_rate_limit_error(self):
        err = Exception("rate limit exceeded")
        assert self.classifier.classify(err) == ErrorCategory.EXTERNAL_SERVICE

    def test_config_error(self):
        err = Exception("invalid config value for 'provider'")
        assert self.classifier.classify(err) == ErrorCategory.CONFIG_ERROR

    def test_key_error_as_config(self):
        err = KeyError("missing key 'api_key'")
        assert self.classifier.classify(err) == ErrorCategory.CONFIG_ERROR

    def test_model_not_found_by_class_name(self):
        """ModelNotFoundError detected by class name (import-free)."""

        class ModelNotFoundError(Exception):
            pass

        err = ModelNotFoundError("model 'qwen:0.5b' not found")
        assert self.classifier.classify(err) == ErrorCategory.MODEL_NOT_FOUND

    def test_provider_unavailable(self):
        err = Exception("provider ollama unavailable")
        assert self.classifier.classify(err) == ErrorCategory.PROVIDER_UNAVAILABLE

    def test_unknown_error(self):
        err = RuntimeError("something unexpected happened")
        assert self.classifier.classify(err) == ErrorCategory.UNKNOWN


class TestExtractModuleName:
    def setup_method(self):
        self.classifier = ErrorClassifier()

    def test_no_module_named(self):
        err = ModuleNotFoundError("No module named 'tiktoken'")
        assert ErrorClassifier.extract_module_name(err) == "tiktoken"

    def test_no_module_named_dotted(self):
        err = ModuleNotFoundError("No module named 'sentence_transformers.util'")
        assert ErrorClassifier.extract_module_name(err) == "sentence_transformers"

    def test_cannot_import_name(self):
        err = ImportError("cannot import name 'Tokenizer' from 'tiktoken'")
        assert ErrorClassifier.extract_module_name(err) == "Tokenizer"

    def test_unrecognized_message(self):
        err = ImportError("something weird happened")
        assert ErrorClassifier.extract_module_name(err) is None


class TestErrorKeyUniqueness:
    def test_empty_error_message_unique_keys(self):
        """Different exception types with empty messages must produce different keys."""
        key1 = HealingRecord.make_error_key(ValueError(""))
        key2 = HealingRecord.make_error_key(RuntimeError(""))
        assert key1 != key2

    def test_same_type_same_message_same_key(self):
        key1 = HealingRecord.make_error_key(ValueError("x"))
        key2 = HealingRecord.make_error_key(ValueError("x"))
        assert key1 == key2
