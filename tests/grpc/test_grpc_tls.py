"""
Unit tests for gRPC TLS support.

These tests verify TLS configuration without requiring actual certificates.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, mock_open

# Skip entire module if grpcio not installed
grpc = pytest.importorskip("grpc", reason="grpcio required for gRPC tests")

from warden.grpc.server import GrpcServer


class TestGrpcTlsConfiguration:
    """Test TLS configuration logic."""

    def test_init_without_tls(self):
        """Test server initialization without TLS parameters."""
        server = GrpcServer(port=50051)

        assert server.tls_cert_path is None
        assert server.tls_key_path is None
        assert server.tls_ca_path is None

    def test_init_with_tls_paths(self):
        """Test server initialization with TLS paths."""
        cert_path = Path("/path/to/cert.pem")
        key_path = Path("/path/to/key.pem")
        ca_path = Path("/path/to/ca.pem")

        server = GrpcServer(
            port=50051,
            tls_cert_path=cert_path,
            tls_key_path=key_path,
            tls_ca_path=ca_path
        )

        assert server.tls_cert_path == cert_path
        assert server.tls_key_path == key_path
        assert server.tls_ca_path == ca_path

    def test_configure_transport_without_server(self):
        """Test _configure_transport raises when server not initialized."""
        server = GrpcServer(port=50051)

        with pytest.raises(RuntimeError, match="Server not initialized"):
            server._configure_transport("[::]:50051")

    @patch('grpc.aio.server')
    def test_configure_transport_insecure_mode(self, mock_server_class):
        """Test _configure_transport configures insecure mode when no TLS."""
        mock_server = Mock()
        mock_server_class.return_value = mock_server

        server = GrpcServer(port=50051)
        server.server = mock_server

        result = server._configure_transport("[::]:50051")

        assert result is False
        mock_server.add_insecure_port.assert_called_once_with("[::]:50051")
        mock_server.add_secure_port.assert_not_called()

    @patch('grpc.aio.server')
    def test_configure_transport_only_cert_provided(self, mock_server_class):
        """Test _configure_transport raises when only cert provided."""
        mock_server = Mock()
        mock_server_class.return_value = mock_server

        server = GrpcServer(
            port=50051,
            tls_cert_path=Path("/cert.pem")
        )
        server.server = mock_server

        with pytest.raises(RuntimeError, match="Both tls_cert_path and tls_key_path"):
            server._configure_transport("[::]:50051")

    @patch('grpc.aio.server')
    def test_configure_transport_only_key_provided(self, mock_server_class):
        """Test _configure_transport raises when only key provided."""
        mock_server = Mock()
        mock_server_class.return_value = mock_server

        server = GrpcServer(
            port=50051,
            tls_key_path=Path("/key.pem")
        )
        server.server = mock_server

        with pytest.raises(RuntimeError, match="Both tls_cert_path and tls_key_path"):
            server._configure_transport("[::]:50051")

    @patch('grpc.ssl_server_credentials')
    @patch('builtins.open', new_callable=mock_open, read_data=b"cert_data")
    @patch('grpc.aio.server')
    def test_configure_transport_tls_mode(
        self,
        mock_server_class,
        mock_file,
        mock_ssl_creds
    ):
        """Test _configure_transport configures TLS mode correctly."""
        mock_server = Mock()
        mock_server_class.return_value = mock_server
        mock_credentials = Mock()
        mock_ssl_creds.return_value = mock_credentials

        cert_path = Path("/tmp/cert.pem")
        key_path = Path("/tmp/key.pem")

        with patch.object(Path, 'exists', return_value=True):
            server = GrpcServer(
                port=50051,
                tls_cert_path=cert_path,
                tls_key_path=key_path
            )
            server.server = mock_server

            result = server._configure_transport("[::]:50051")

        assert result is True
        mock_server.add_secure_port.assert_called_once_with(
            "[::]:50051",
            mock_credentials
        )
        mock_server.add_insecure_port.assert_not_called()

        # Verify SSL credentials were created correctly
        mock_ssl_creds.assert_called_once()
        call_args = mock_ssl_creds.call_args
        assert call_args[1]['root_certificates'] is None
        assert call_args[1]['require_client_auth'] is False

    @patch('grpc.ssl_server_credentials')
    @patch('builtins.open', new_callable=mock_open, read_data=b"cert_data")
    @patch('grpc.aio.server')
    def test_configure_transport_with_client_auth(
        self,
        mock_server_class,
        mock_file,
        mock_ssl_creds
    ):
        """Test _configure_transport with client authentication."""
        mock_server = Mock()
        mock_server_class.return_value = mock_server
        mock_credentials = Mock()
        mock_ssl_creds.return_value = mock_credentials

        cert_path = Path("/tmp/cert.pem")
        key_path = Path("/tmp/key.pem")
        ca_path = Path("/tmp/ca.pem")

        with patch.object(Path, 'exists', return_value=True):
            server = GrpcServer(
                port=50051,
                tls_cert_path=cert_path,
                tls_key_path=key_path,
                tls_ca_path=ca_path
            )
            server.server = mock_server

            result = server._configure_transport("[::]:50051")

        assert result is True

        # Verify SSL credentials were created with client auth
        mock_ssl_creds.assert_called_once()
        call_args = mock_ssl_creds.call_args
        assert call_args[1]['root_certificates'] == b"cert_data"
        assert call_args[1]['require_client_auth'] is True

    @patch('grpc.aio.server')
    def test_configure_transport_cert_not_found(self, mock_server_class):
        """Test _configure_transport raises when cert file not found."""
        mock_server = Mock()
        mock_server_class.return_value = mock_server

        server = GrpcServer(
            port=50051,
            tls_cert_path=Path("/nonexistent/cert.pem"),
            tls_key_path=Path("/nonexistent/key.pem")
        )
        server.server = mock_server

        with pytest.raises(FileNotFoundError, match="TLS certificate not found"):
            server._configure_transport("[::]:50051")

    @patch('builtins.open', new_callable=mock_open, read_data=b"cert_data")
    @patch('grpc.aio.server')
    def test_configure_transport_key_not_found(self, mock_server_class, mock_file):
        """Test _configure_transport raises when key file not found."""
        mock_server = Mock()
        mock_server_class.return_value = mock_server

        cert_path = Path("/tmp/cert.pem")
        key_path = Path("/tmp/key.pem")

        # Create a mock that returns different values based on the path
        original_exists = Path.exists

        def exists_wrapper(path_obj):
            # Cert exists, key doesn't
            return str(path_obj).endswith('cert.pem')

        with patch.object(Path, 'exists', new=exists_wrapper):
            server = GrpcServer(
                port=50051,
                tls_cert_path=cert_path,
                tls_key_path=key_path
            )
            server.server = mock_server

            with pytest.raises(FileNotFoundError, match="TLS private key not found"):
                server._configure_transport("[::]:50051")

    @patch('grpc.ssl_server_credentials')
    @patch('builtins.open', new_callable=mock_open, read_data=b"cert_data")
    @patch('grpc.aio.server')
    def test_configure_transport_ca_not_found(
        self,
        mock_server_class,
        mock_file,
        mock_ssl_creds
    ):
        """Test _configure_transport raises when CA file not found."""
        mock_server = Mock()
        mock_server_class.return_value = mock_server

        cert_path = Path("/tmp/cert.pem")
        key_path = Path("/tmp/key.pem")
        ca_path = Path("/tmp/ca.pem")

        def exists_wrapper(path_obj):
            # Cert and key exist, CA doesn't
            path_str = str(path_obj)
            return path_str.endswith('cert.pem') or path_str.endswith('key.pem')

        with patch.object(Path, 'exists', new=exists_wrapper):
            server = GrpcServer(
                port=50051,
                tls_cert_path=cert_path,
                tls_key_path=key_path,
                tls_ca_path=ca_path
            )
            server.server = mock_server

            with pytest.raises(FileNotFoundError, match="TLS CA certificate not found"):
                server._configure_transport("[::]:50051")


class TestGrpcServerWithTls:
    """Integration-style tests for server with TLS."""

    @pytest.mark.asyncio
    async def test_server_stop_without_start_with_tls_config(self):
        """Test stopping server with TLS config that wasn't started."""
        server = GrpcServer(
            port=50051,
            tls_cert_path=Path("/tmp/cert.pem"),
            tls_key_path=Path("/tmp/key.pem")
        )

        # Should not raise even with TLS config
        await server.stop_async()

    def test_server_initialization_logs_tls_status(self):
        """Test that server initialization logs TLS status."""
        with patch('warden.grpc.server.logger') as mock_logger:
            # Without TLS
            server = GrpcServer(port=50051)
            mock_logger.info.assert_called_with(
                "grpc_server_init",
                port=50051,
                endpoints=51,
                tls_enabled=False
            )

            # With TLS
            server = GrpcServer(
                port=50052,
                tls_cert_path=Path("/cert.pem"),
                tls_key_path=Path("/key.pem")
            )
            mock_logger.info.assert_called_with(
                "grpc_server_init",
                port=50052,
                endpoints=51,
                tls_enabled=True
            )
