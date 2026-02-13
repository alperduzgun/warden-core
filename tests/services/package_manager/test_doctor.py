import pytest
from pathlib import Path
from warden.services.package_manager.doctor import WardenDoctor, CheckStatus

@pytest.fixture
def doctor_env(tmp_path):
    warden_dir = tmp_path / ".warden"
    warden_dir.mkdir()

    config_path = tmp_path / "warden.yaml"
    import yaml
    with open(config_path, "w") as f:
        yaml.dump({"dependencies": {"pkg-1": "latest"}}, f)

    return tmp_path, warden_dir, config_path

def test_doctor_missing_warden_dir(tmp_path):
    doc = WardenDoctor(tmp_path)
    status, msg = doc.check_warden_dir()
    assert status == CheckStatus.ERROR
    assert "not found" in msg

def test_doctor_check_frames_missing(doctor_env):
    root, warden_dir, _ = doctor_env
    doc = WardenDoctor(root)
    status, msg = doc.check_frames()
    assert status == CheckStatus.ERROR
    assert "Missing frames: pkg-1" in msg

def test_doctor_python_version():
    doc = WardenDoctor(Path("."))
    status, msg = doc.check_python_version()
    assert status == CheckStatus.SUCCESS
    assert "Python" in msg

def test_doctor_check_config_valid(tmp_path):
    """Test that a valid warden.yaml passes config check"""
    import yaml
    config_path = tmp_path / "warden.yaml"
    valid_config = {
        "project": {"name": "test", "language": "python"},
        "frames": ["security", "resilience"],
        "advanced": {"min_severity": "high"}
    }
    with open(config_path, "w") as f:
        yaml.dump(valid_config, f)

    doc = WardenDoctor(tmp_path)
    status, msg = doc.check_config()
    assert status == CheckStatus.SUCCESS
    assert "valid YAML" in msg

def test_doctor_check_config_missing(tmp_path):
    """Test that missing warden.yaml is detected"""
    doc = WardenDoctor(tmp_path)
    status, msg = doc.check_config()
    assert status == CheckStatus.ERROR
    assert "not found" in msg

def test_doctor_check_config_invalid_yaml(tmp_path):
    """Test that invalid YAML syntax is detected"""
    config_path = tmp_path / "warden.yaml"
    with open(config_path, "w") as f:
        f.write("invalid: yaml: syntax:\n  - bad\n    indentation")

    doc = WardenDoctor(tmp_path)
    status, msg = doc.check_config()
    assert status == CheckStatus.ERROR
    assert "Invalid YAML" in msg or "YAML" in msg

def test_doctor_check_config_empty(tmp_path):
    """Test that empty warden.yaml is detected"""
    config_path = tmp_path / "warden.yaml"
    config_path.touch()

    doc = WardenDoctor(tmp_path)
    status, msg = doc.check_config()
    assert status == CheckStatus.ERROR
    assert "empty" in msg

def test_doctor_check_config_missing_recommended_keys(tmp_path):
    """Test that missing recommended keys triggers warning"""
    import yaml
    config_path = tmp_path / "warden.yaml"
    minimal_config = {"some_other_key": "value"}
    with open(config_path, "w") as f:
        yaml.dump(minimal_config, f)

    doc = WardenDoctor(tmp_path)
    status, msg = doc.check_config()
    assert status == CheckStatus.WARNING
    assert "missing recommended keys" in msg

def test_doctor_check_config_unknown_keys(tmp_path):
    """Test that unknown top-level keys trigger warning"""
    import yaml
    config_path = tmp_path / "warden.yaml"
    config_with_unknown = {
        "project": {"name": "test"},
        "frames": ["security"],
        "banana": "yellow",
        "rocket": "fast",
    }
    with open(config_path, "w") as f:
        yaml.dump(config_with_unknown, f)

    doc = WardenDoctor(tmp_path)
    status, msg = doc.check_config()
    assert status == CheckStatus.WARNING
    assert "unknown top-level keys" in msg
    assert "banana" in msg
    assert "rocket" in msg

def test_doctor_check_config_type_mismatch_project(tmp_path):
    """Test that wrong type for 'project' triggers warning"""
    import yaml
    config_path = tmp_path / "warden.yaml"
    bad_types_config = {
        "project": "should-be-dict",
        "frames": ["security"],
    }
    with open(config_path, "w") as f:
        yaml.dump(bad_types_config, f)

    doc = WardenDoctor(tmp_path)
    status, msg = doc.check_config()
    assert status == CheckStatus.WARNING
    assert "type mismatches" in msg
    assert "'project' should be dict" in msg

def test_doctor_check_config_type_mismatch_frames(tmp_path):
    """Test that wrong type for 'frames' triggers warning"""
    import yaml
    config_path = tmp_path / "warden.yaml"
    bad_types_config = {
        "project": {"name": "test"},
        "frames": "should-be-list",
    }
    with open(config_path, "w") as f:
        yaml.dump(bad_types_config, f)

    doc = WardenDoctor(tmp_path)
    status, msg = doc.check_config()
    assert status == CheckStatus.WARNING
    assert "type mismatches" in msg
    assert "'frames' should be list" in msg

def test_doctor_check_config_type_mismatch_dependencies(tmp_path):
    """Test that wrong type for 'dependencies' triggers warning"""
    import yaml
    config_path = tmp_path / "warden.yaml"
    bad_types_config = {
        "project": {"name": "test"},
        "frames": ["security"],
        "dependencies": ["should", "be", "dict"],
    }
    with open(config_path, "w") as f:
        yaml.dump(bad_types_config, f)

    doc = WardenDoctor(tmp_path)
    status, msg = doc.check_config()
    assert status == CheckStatus.WARNING
    assert "type mismatches" in msg
    assert "'dependencies' should be dict" in msg

def test_doctor_check_config_all_known_keys_valid(tmp_path):
    """Test that all known top-level keys pass without warnings"""
    import yaml
    config_path = tmp_path / "warden.yaml"
    full_config = {
        "project": {"name": "test"},
        "frames": ["security"],
        "dependencies": {},
        "llm": {"provider": "openai"},
        "frames_config": {},
        "custom_rules": [],
        "ci": {},
        "advanced": {},
        "spec": {},
        "analysis": {},
        "suppression": {},
        "fortification": {},
        "cleaning": {},
        "pipeline": {},
    }
    with open(config_path, "w") as f:
        yaml.dump(full_config, f)

    doc = WardenDoctor(tmp_path)
    status, msg = doc.check_config()
    assert status == CheckStatus.SUCCESS
    assert "valid YAML" in msg

def test_doctor_check_config_missing_keys_takes_priority(tmp_path):
    """Test that missing recommended keys warning comes before unknown keys warning"""
    import yaml
    config_path = tmp_path / "warden.yaml"
    config = {
        "unknown_key": "value",
    }
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    doc = WardenDoctor(tmp_path)
    status, msg = doc.check_config()
    assert status == CheckStatus.WARNING
    # Missing keys warning should come first since both project and frames are missing
    assert "missing recommended keys" in msg
