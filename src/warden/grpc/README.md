# Warden gRPC Server

Async gRPC server wrapping WardenBridge for C# Panel communication.

## Features

- **51 gRPC endpoints** for comprehensive Warden operations
- **Async/await** support for high-performance concurrent operations
- **TLS/SSL support** with optional client certificate authentication
- **gRPC Reflection** for automatic service discovery (Postman, grpcurl)
- **Structured logging** via structlog
- **Backward compatible** - works in both secure and insecure modes

## Quick Start

### Insecure Mode (Development)

```python
from warden.grpc import GrpcServer

server = GrpcServer(port=50051)
await server.start_async()
await server.wait_for_termination_async()
```

Or from command line:

```bash
python3 -m warden.grpc.server --port 50051
```

### TLS Mode (Production)

```python
from pathlib import Path
from warden.grpc import GrpcServer

server = GrpcServer(
    port=50051,
    tls_cert_path=Path("/path/to/server-cert.pem"),
    tls_key_path=Path("/path/to/server-key.pem")
)
await server.start_async()
await server.wait_for_termination_async()
```

Or from command line:

```bash
python3 -m warden.grpc.server \
    --port 50051 \
    --tls-cert /path/to/server-cert.pem \
    --tls-key /path/to/server-key.pem
```

### Mutual TLS (Client Authentication)

```python
server = GrpcServer(
    port=50051,
    tls_cert_path=Path("/path/to/server-cert.pem"),
    tls_key_path=Path("/path/to/server-key.pem"),
    tls_ca_path=Path("/path/to/ca-cert.pem")  # Requires client certificates
)
```

## TLS Configuration

The server supports flexible TLS configuration:

- **No TLS parameters**: Runs in insecure mode (default)
- **cert + key**: Enables TLS with server authentication
- **cert + key + ca**: Enables mutual TLS with client authentication

See [docs/grpc-tls.md](../../../docs/grpc-tls.md) for detailed TLS setup, certificate generation, and security best practices.

## Command-Line Options

```bash
python3 -m warden.grpc.server --help
```

Options:
- `--port`: Port to listen on (default: 50051)
- `--project`: Project root path (default: current directory)
- `--tls-cert`: Path to TLS certificate file (enables TLS)
- `--tls-key`: Path to TLS private key file (required with --tls-cert)
- `--tls-ca`: Path to CA certificate for client authentication (optional)

## Architecture

```
GrpcServer
├── WardenServicer (51 gRPC endpoints)
│   └── WardenBridge (CLI integration)
│       ├── Pipeline orchestrator
│       ├── Frame management
│       ├── Configuration
│       └── LLM integration
└── gRPC Reflection (auto-discovery)
```

## Available Endpoints

The server exposes 51 gRPC endpoints across multiple categories:

- **Health & Status**: HealthCheck, GetStatus, GetConfiguration
- **Pipeline**: ExecutePipeline, ExecutePipelineStream
- **Frames**: GetAvailableFrames, ExecuteFrame
- **LLM**: GetAvailableProviders, ClassifyCode
- **Configuration**: GetConfig, UpdateConfig
- **And more...**

See [protos/warden.proto](protos/warden.proto) for complete endpoint definitions.

## Client Connection

### Python Client (Insecure)

```python
import grpc
from warden.grpc.generated import warden_pb2, warden_pb2_grpc

channel = grpc.insecure_channel('localhost:50051')
stub = warden_pb2_grpc.WardenServiceStub(channel)

# Call endpoint
response = await stub.HealthCheck(warden_pb2.Empty())
print(f"Version: {response.version}")
```

### Python Client (TLS)

```python
import grpc

# Read server certificate
with open('/path/to/server-cert.pem', 'rb') as f:
    trusted_certs = f.read()

credentials = grpc.ssl_channel_credentials(root_certificates=trusted_certs)
channel = grpc.secure_channel('localhost:50051', credentials)
stub = warden_pb2_grpc.WardenServiceStub(channel)

# Call endpoint
response = await stub.HealthCheck(warden_pb2.Empty())
```

## Development

### Generate gRPC Code

```bash
python3 scripts/generate_grpc.py
```

### Run Tests

```bash
# TLS-specific tests
python3 -m pytest tests/grpc/test_grpc_tls.py -v

# Integration tests
python3 -m pytest tests/integration/grpc_integration/ -v
```

### Test with grpcurl

```bash
# List services (requires reflection)
grpcurl -plaintext localhost:50051 list

# Call health check
grpcurl -plaintext localhost:50051 warden.WardenService/HealthCheck

# With TLS
grpcurl -cacert server-cert.pem localhost:50051 list
```

## Logging

The server uses structured logging for all events:

```python
# Example log output
2026-02-11 22:00:00 [info] grpc_server_init port=50051 endpoints=51 tls_enabled=true
2026-02-11 22:00:00 [info] grpc_tls_configured cert_path=/path/to/cert.pem
2026-02-11 22:00:00 [info] grpc_server_started address=[::]:50051
```

## Security

- **Use TLS in production**: Never expose the server without TLS encryption
- **Protect private keys**: Store with restricted permissions (chmod 600)
- **Rotate certificates**: Set up automatic certificate rotation
- **Use mutual TLS**: Require client certificates for sensitive operations
- **Monitor logs**: Set up alerts for authentication failures

See [docs/grpc-tls.md](../../../docs/grpc-tls.md) for complete security guidelines.

## Troubleshooting

### Server won't start

- Check if port is already in use: `lsof -i :50051`
- Verify gRPC code is generated: `ls src/warden/grpc/generated/`
- Check logs for error messages

### TLS connection fails

- Verify certificate paths are correct and files exist
- Check certificate isn't expired: `openssl x509 -in cert.pem -noout -dates`
- Ensure client trusts server certificate
- Check firewall rules

### Performance issues

- Use streaming endpoints for large data transfers
- Enable connection pooling on client side
- Monitor server resources (CPU, memory)
- Consider horizontal scaling

## Files

- `server.py` - Main server implementation with TLS support
- `servicer.py` - gRPC endpoint implementations
- `converters.py` - Protocol buffer converters
- `protos/warden.proto` - Service definitions
- `generated/` - Auto-generated gRPC code (run generate_grpc.py)

## References

- [gRPC Python Documentation](https://grpc.io/docs/languages/python/)
- [gRPC Authentication Guide](https://grpc.io/docs/guides/auth/)
- [Protocol Buffers](https://protobuf.dev/)
- [Warden TLS Documentation](../../../docs/grpc-tls.md)
