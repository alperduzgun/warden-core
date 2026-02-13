
import pytest
import subprocess
from unittest.mock import MagicMock, patch
from warden.infrastructure.installer import AutoInstaller, InstallConfig, InstallResult
from warden.shared.domain.exceptions import InstallError

@pytest.fixture
def config(tmp_path):
    return InstallConfig(
        version="1.0.0",
        install_path=tmp_path / "lib",
        verify_install=False
    )

def test_install_fail_fast_subprocess(config):
    """Ensure installer raises InstallError when pip fails."""
    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, ["pip"], stderr="Connection failed")):
        with pytest.raises(InstallError) as exc:
            AutoInstaller.install(config)
        
        assert "Pip install failed" in str(exc.value)

def test_install_idempotency(config):
    """Ensure installer returns success immediately if version matches."""
    with patch.object(AutoInstaller, "_get_installed_version", return_value="1.0.0"):
        # Should NOT call subprocess.run for pip
        with patch("subprocess.run") as mock_run:
            result = AutoInstaller.install(config)
            
            assert result.success is True
            assert result.message == "Already installed"
            mock_run.assert_not_called()

def test_install_verification_failure(config):
    """Ensure verification failure raises exception."""
    config.verify_install = True
    
    # Pip succeeds
    with patch("subprocess.run", return_value=MagicMock(returncode=0)):
        # Verification fails
        with patch.object(AutoInstaller, "_verify_install") as mock_verify:
            mock_verify.return_value = InstallResult(success=False, message="Binary missing")
            
            with pytest.raises(InstallError) as exc:
                AutoInstaller.install(config)
            
            assert "Verification failed" in str(exc.value)
