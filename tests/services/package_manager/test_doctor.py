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
