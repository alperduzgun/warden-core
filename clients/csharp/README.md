# Warden C# Client

C# client for communicating with Warden Python backend via gRPC.

## Quick Start

### 1. Start Python gRPC Server

```bash
cd /path/to/warden-core

# Generate gRPC code first (one-time)
python scripts/generate_grpc.py

# Start server
python start_grpc_server.py --port 50051
```

### 2. Add to Your C# Project

```xml
<ItemGroup>
  <PackageReference Include="Grpc.Net.Client" Version="2.60.0" />
  <PackageReference Include="Google.Protobuf" Version="3.25.2" />
  <PackageReference Include="Grpc.Tools" Version="2.60.0" PrivateAssets="All" />
</ItemGroup>

<ItemGroup>
  <Protobuf Include="path/to/warden.proto" GrpcServices="Client" />
</ItemGroup>
```

### 3. Use the Client

```csharp
using Warden.Panel.Services;

// Create client
using var client = new WardenClient("localhost", 50051);

// Check connection
if (await client.IsConnectedAsync())
{
    // Execute pipeline
    var result = await client.ExecutePipelineAsync("./src");

    Console.WriteLine($"Found {result.TotalFindings} issues");
    Console.WriteLine($"Critical: {result.CriticalCount}");
}
```

## API Reference

### Pipeline Operations

```csharp
// Full pipeline
var result = await client.ExecutePipelineAsync("./src");

// Specific frames only
var result = await client.ExecutePipelineAsync("./src",
    new[] { "security", "fuzz" });

// Streaming with progress
await foreach (var evt in client.ExecutePipelineStreamAsync("./src"))
{
    Console.WriteLine($"{evt.Progress * 100}% - {evt.Message}");
}
```

### LLM Operations

```csharp
// Analyze code
var result = await client.AnalyzeWithLlmAsync(
    code: "def foo(): pass",
    prompt: "Review this code"
);

// Classify code
var classification = await client.ClassifyCodeAsync(code);
Console.WriteLine($"Has SQL: {classification.HasDatabaseOperations}");
```

### Configuration

```csharp
// Get available frames
var frames = await client.GetAvailableFramesAsync();

// Get available providers
var providers = await client.GetAvailableProvidersAsync();

// Get configuration
var config = await client.GetConfigurationAsync();
```

### Health Check

```csharp
// Simple connection check
bool connected = await client.IsConnectedAsync();

// Detailed health
var health = await client.HealthCheckAsync();
Console.WriteLine($"Healthy: {health.Healthy}");
Console.WriteLine($"Uptime: {health.UptimeSeconds}s");
```

## Extension Methods

```csharp
// Security-only scan
var result = await client.SecurityScanAsync("./src");

// Full validation
var result = await client.FullValidationAsync("./src");

// Quick LLM review
var review = await client.QuickReviewAsync(code);
```

## WPF/MAUI Integration

```csharp
public class ScanViewModel : INotifyPropertyChanged
{
    private readonly WardenClient _client = new();

    public async Task ScanAsync(string path)
    {
        await foreach (var evt in _client.ExecutePipelineStreamAsync(path))
        {
            Progress = evt.Progress * 100;

            if (evt.Finding != null)
                Findings.Add(evt.Finding);
        }
    }
}
```

## Architecture

```
C# Panel  ─────────────────────────────────  Python Backend
    │                                              │
    │  ┌─────────────────────────────────────┐    │
    │  │         gRPC (Port 50051)           │    │
    │  │      Protocol Buffers binary        │    │
    │  └─────────────────────────────────────┘    │
    │                                              │
    ▼                                              ▼
WardenClient                              WardenServicer
    │                                              │
    └──────────────────────────────────────────────┘
```

## Proto File

The proto file is located at:
```
warden-core/src/warden/grpc/protos/warden.proto
```

Generate C# code automatically by adding to your .csproj:
```xml
<Protobuf Include="warden.proto" GrpcServices="Client" />
```
