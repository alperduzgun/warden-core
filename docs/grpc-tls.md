# gRPC TLS Configuration

The Warden gRPC server supports TLS encryption for secure communication between the server and clients.

## Overview

TLS (Transport Layer Security) support enables encrypted communication and optional client authentication for the gRPC server. The server can operate in two modes:

1. **Insecure Mode** (default): No encryption, suitable for local development
2. **TLS Mode**: Encrypted communication with optional client certificate authentication

## Basic TLS Setup

### Server Configuration

To enable TLS, provide certificate and key file paths when initializing the server:

```python
from pathlib import Path
from warden.grpc import GrpcServer

server = GrpcServer(
    port=50051,
    tls_cert_path=Path("/path/to/server-cert.pem"),
    tls_key_path=Path("/path/to/server-key.pem")
)

await server.start_async()
```

### Command-Line Usage

Start the server with TLS from the command line:

```bash
python3 -m warden.grpc.server \
    --port 50051 \
    --tls-cert /path/to/server-cert.pem \
    --tls-key /path/to/server-key.pem
```

## Mutual TLS (Client Authentication)

For enhanced security, you can require client certificate authentication:

```python
server = GrpcServer(
    port=50051,
    tls_cert_path=Path("/path/to/server-cert.pem"),
    tls_key_path=Path("/path/to/server-key.pem"),
    tls_ca_path=Path("/path/to/ca-cert.pem")  # CA certificate for validating clients
)
```

Command-line:

```bash
python3 -m warden.grpc.server \
    --port 50051 \
    --tls-cert /path/to/server-cert.pem \
    --tls-key /path/to/server-key.pem \
    --tls-ca /path/to/ca-cert.pem
```

## Certificate Generation

### Self-Signed Certificates (Development)

For development and testing, generate self-signed certificates:

```bash
# Generate CA private key and certificate
openssl req -x509 -newkey rsa:4096 -days 365 -nodes \
    -keyout ca-key.pem -out ca-cert.pem \
    -subj "/CN=Warden CA"

# Generate server private key and certificate signing request
openssl req -newkey rsa:4096 -nodes \
    -keyout server-key.pem -out server-req.pem \
    -subj "/CN=localhost"

# Sign server certificate with CA
openssl x509 -req -in server-req.pem -days 365 \
    -CA ca-cert.pem -CAkey ca-key.pem -CAcreateserial \
    -out server-cert.pem

# Generate client certificate (for mutual TLS)
openssl req -newkey rsa:4096 -nodes \
    -keyout client-key.pem -out client-req.pem \
    -subj "/CN=warden-client"

openssl x509 -req -in client-req.pem -days 365 \
    -CA ca-cert.pem -CAkey ca-key.pem -CAcreateserial \
    -out client-cert.pem
```

### Production Certificates

For production, use certificates from a trusted Certificate Authority:

1. Purchase or obtain free certificates from Let's Encrypt
2. Ensure certificates include appropriate SANs (Subject Alternative Names)
3. Keep private keys secure and never commit them to version control

## Client Connection

### Python Client (Insecure Mode)

```python
import grpc
from warden.grpc.generated import warden_pb2_grpc

channel = grpc.insecure_channel('localhost:50051')
stub = warden_pb2_grpc.WardenServiceStub(channel)
```

### Python Client (TLS Mode)

```python
import grpc
from pathlib import Path

# Read server certificate
with open('/path/to/server-cert.pem', 'rb') as f:
    trusted_certs = f.read()

credentials = grpc.ssl_channel_credentials(root_certificates=trusted_certs)
channel = grpc.secure_channel('localhost:50051', credentials)
stub = warden_pb2_grpc.WardenServiceStub(channel)
```

### Python Client (Mutual TLS)

```python
import grpc

# Read certificates
with open('/path/to/ca-cert.pem', 'rb') as f:
    ca_cert = f.read()
with open('/path/to/client-cert.pem', 'rb') as f:
    client_cert = f.read()
with open('/path/to/client-key.pem', 'rb') as f:
    client_key = f.read()

credentials = grpc.ssl_channel_credentials(
    root_certificates=ca_cert,
    private_key=client_key,
    certificate_chain=client_cert
)
channel = grpc.secure_channel('localhost:50051', credentials)
stub = warden_pb2_grpc.WardenServiceStub(channel)
```

## Configuration Validation

The server performs the following validations:

1. **Both cert and key required**: If you provide `tls_cert_path`, you must also provide `tls_key_path` (and vice versa)
2. **File existence**: All certificate files must exist at the specified paths
3. **File readability**: Certificate files must be readable by the server process
4. **Valid format**: Certificates must be in PEM format

### Error Handling

The server will raise specific exceptions for configuration errors:

- `FileNotFoundError`: Certificate or key file not found
- `RuntimeError`: Invalid TLS configuration (e.g., only cert provided without key)
- Generic exceptions are caught and wrapped with descriptive error messages

## Logging

The server logs TLS-related events using structured logging:

- `grpc_server_init`: Logs TLS status on initialization (`tls_enabled: true/false`)
- `grpc_tls_configured`: Logs successful TLS configuration with cert paths
- `grpc_insecure_mode`: Logs when server starts in insecure mode
- `grpc_tls_cert_not_found`: Logs certificate file not found errors
- `grpc_tls_config_failed`: Logs TLS configuration failures

Example log output:

```
2026-02-11 22:00:00 [info] grpc_server_init port=50051 endpoints=51 tls_enabled=true
2026-02-11 22:00:00 [info] grpc_tls_configured cert_path=/path/to/cert.pem key_path=/path/to/key.pem ca_path=None client_auth_required=false
2026-02-11 22:00:00 [info] grpc_server_started address=[::]:50051 endpoints=51 tls_enabled=true
```

## Security Best Practices

1. **Use TLS in production**: Never expose gRPC servers without TLS in production environments
2. **Protect private keys**: Store private keys with restricted permissions (chmod 600)
3. **Rotate certificates**: Regularly rotate certificates before expiration
4. **Use mutual TLS for sensitive operations**: Require client certificates for administrative operations
5. **Validate hostnames**: Ensure certificate SANs match server hostnames
6. **Monitor certificate expiration**: Set up alerts for certificate expiration
7. **Use strong keys**: Minimum RSA 2048-bit or ECC 256-bit keys
8. **Keep certificates out of version control**: Never commit `.pem`, `.key`, or `.crt` files

## Testing

The implementation includes comprehensive unit tests:

```bash
# Run TLS-specific tests
python3 -m pytest tests/grpc/test_grpc_tls.py -v

# All tests should pass
# - Initialization with/without TLS
# - Transport configuration (secure/insecure)
# - Error handling (missing files, invalid config)
# - Client authentication setup
# - Logging verification
```

## Troubleshooting

### "TLS certificate not found"

- Verify the certificate path is correct and absolute
- Check file permissions (readable by server process)
- Ensure the file exists and hasn't been deleted

### "Both tls_cert_path and tls_key_path must be provided together"

- You must provide both certificate and key files
- You cannot use one without the other

### Connection refused (with TLS)

- Verify server is running with TLS enabled
- Check client is using `grpc.secure_channel()` instead of `insecure_channel()`
- Ensure client has correct server certificate

### Certificate verification failed

- Client's trusted certificates don't match server certificate
- Certificate may be expired or have incorrect hostname
- For self-signed certificates, ensure client trusts the CA certificate

## Examples

### Development Setup (Self-Signed)

```python
# Generate certificates (see Certificate Generation section)
# Then start server:

from pathlib import Path
from warden.grpc import GrpcServer

server = GrpcServer(
    port=50051,
    tls_cert_path=Path("./certs/server-cert.pem"),
    tls_key_path=Path("./certs/server-key.pem")
)

await server.start_async()
```

### Production Setup (Let's Encrypt)

```python
from pathlib import Path
from warden.grpc import GrpcServer

server = GrpcServer(
    port=50051,
    tls_cert_path=Path("/etc/letsencrypt/live/warden.example.com/fullchain.pem"),
    tls_key_path=Path("/etc/letsencrypt/live/warden.example.com/privkey.pem")
)

await server.start_async()
```

### High-Security Setup (Mutual TLS)

```python
from pathlib import Path
from warden.grpc import GrpcServer

server = GrpcServer(
    port=50051,
    tls_cert_path=Path("/etc/warden/tls/server-cert.pem"),
    tls_key_path=Path("/etc/warden/tls/server-key.pem"),
    tls_ca_path=Path("/etc/warden/tls/ca-cert.pem")  # Requires client certs
)

await server.start_async()
```

## API Reference

### GrpcServer Constructor Parameters

- **tls_cert_path** (`Path | None`): Path to TLS certificate file in PEM format. When provided with `tls_key_path`, enables TLS mode.

- **tls_key_path** (`Path | None`): Path to TLS private key file in PEM format. Required when `tls_cert_path` is provided.

- **tls_ca_path** (`Path | None`): Path to CA certificate for client authentication. When provided, requires clients to present valid certificates signed by this CA.

### Command-Line Arguments

- **--tls-cert**: Path to TLS certificate file (enables TLS)
- **--tls-key**: Path to TLS private key file (required with --tls-cert)
- **--tls-ca**: Path to TLS CA certificate for client authentication (optional)

## Migration from Insecure to TLS

If you have an existing server running in insecure mode:

1. Generate or obtain TLS certificates
2. Update server initialization to include TLS parameters
3. Update all clients to use secure channels
4. Test in staging environment before production deployment
5. Consider running both insecure and secure servers during transition period (on different ports)
6. Monitor logs for connection errors
7. Disable insecure server once all clients migrated

## See Also

- [gRPC Python Documentation](https://grpc.io/docs/languages/python/)
- [gRPC Authentication Guide](https://grpc.io/docs/guides/auth/)
- [OpenSSL Documentation](https://www.openssl.org/docs/)
