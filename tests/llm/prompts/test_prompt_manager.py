"""Tests for PromptManager."""
import pytest
from pathlib import Path
from warden.llm.prompts.prompt_manager import PromptManager, PromptTemplateError


@pytest.fixture
def tmp_templates(tmp_path):
    """Create temporary template directory with test templates."""
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    shared_dir = templates_dir / "shared"
    shared_dir.mkdir()

    # Base templates
    (templates_dir / "simple.txt").write_text("Hello {{NAME}}!")
    (templates_dir / "with_include.txt").write_text("Header\n@include(shared/_footer.txt)\nEnd")
    (shared_dir / "_footer.txt").write_text("-- Footer content --")

    # Circular includes
    (templates_dir / "circular_a.txt").write_text("A\n@include(circular_b.txt)")
    (templates_dir / "circular_b.txt").write_text("B\n@include(circular_a.txt)")

    # Nested includes
    (templates_dir / "nested.txt").write_text("Top\n@include(shared/_level1.txt)")
    (shared_dir / "_level1.txt").write_text("L1\n@include(shared/_level2.txt)")
    (shared_dir / "_level2.txt").write_text("L2 content")

    return templates_dir


class TestPromptManager:
    def test_simple_load(self, tmp_templates):
        pm = PromptManager(tmp_templates)
        result = pm.load("simple.txt", {"NAME": "Warden"})
        assert result == "Hello Warden!"

    def test_unknown_variable_preserved(self, tmp_templates):
        pm = PromptManager(tmp_templates)
        result = pm.load("simple.txt")
        assert "{{NAME}}" in result

    def test_include_resolution(self, tmp_templates):
        pm = PromptManager(tmp_templates)
        result = pm.load("with_include.txt")
        assert "Footer content" in result
        assert "@include" not in result

    def test_nested_includes(self, tmp_templates):
        pm = PromptManager(tmp_templates)
        result = pm.load("nested.txt")
        assert "Top" in result
        assert "L1" in result
        assert "L2 content" in result

    def test_circular_include_detection(self, tmp_templates):
        pm = PromptManager(tmp_templates)
        with pytest.raises(PromptTemplateError, match="Circular include"):
            pm.load("circular_a.txt")

    def test_missing_template(self, tmp_templates):
        pm = PromptManager(tmp_templates)
        with pytest.raises(PromptTemplateError, match="not found"):
            pm.load("nonexistent.txt")

    def test_path_traversal_blocked(self, tmp_templates):
        pm = PromptManager(tmp_templates)
        with pytest.raises(PromptTemplateError, match="Path traversal"):
            pm.load("../../etc/passwd")

    def test_size_limit(self, tmp_templates):
        # Create oversized template
        (tmp_templates / "huge.txt").write_text("x" * 200_000)
        pm = PromptManager(tmp_templates)
        with pytest.raises(PromptTemplateError, match="size limit"):
            pm.load("huge.txt")

    def test_global_variables(self, tmp_templates):
        pm = PromptManager(tmp_templates)
        pm.register_variables(NAME="Global")
        result = pm.load("simple.txt")
        assert result == "Hello Global!"

    def test_local_overrides_global(self, tmp_templates):
        pm = PromptManager(tmp_templates)
        pm.register_variables(NAME="Global")
        result = pm.load("simple.txt", {"NAME": "Local"})
        assert result == "Hello Local!"

    def test_cache_invalidation(self, tmp_templates):
        pm = PromptManager(tmp_templates)
        result1 = pm.load("simple.txt", {"NAME": "First"})
        # Modify the file
        (tmp_templates / "simple.txt").write_text("Changed {{NAME}}!")
        # Still cached
        result2 = pm.load("simple.txt", {"NAME": "Second"})
        assert "Hello" in result2  # Still cached raw
        # Invalidate
        pm.invalidate_cache()
        result3 = pm.load("simple.txt", {"NAME": "Third"})
        assert result3 == "Changed Third!"

    def test_real_templates_load(self):
        """Verify the actual shipped templates load without error."""
        pm = PromptManager()
        for template in ["analysis.txt", "classification.txt", "resilience.txt", "fortification.txt"]:
            result = pm.load(template)
            assert len(result) > 0
            assert "@include" not in result  # All includes resolved
