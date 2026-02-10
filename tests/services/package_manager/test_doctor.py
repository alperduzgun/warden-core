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
        "settings": {"min_severity": "high"}
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
