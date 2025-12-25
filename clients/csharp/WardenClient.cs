// ============================================================================
// Warden gRPC Client for C#
//
// Usage in C# Panel:
//   var client = new WardenClient("localhost", 50051);
//   var result = await client.ExecutePipelineAsync("./src");
// ============================================================================

using Grpc.Net.Client;
using Warden.Grpc;

namespace Warden.Panel.Services;

/// <summary>
/// Client for communicating with Warden Python backend via gRPC.
/// </summary>
public class WardenClient : IDisposable
{
    private readonly GrpcChannel _channel;
    private readonly WardenService.WardenServiceClient _client;
    private bool _disposed;

    /// <summary>
    /// Create a new Warden client.
    /// </summary>
    /// <param name="host">Server host (default: localhost)</param>
    /// <param name="port">Server port (default: 50051)</param>
    public WardenClient(string host = "localhost", int port = 50051)
    {
        var address = $"http://{host}:{port}";
        _channel = GrpcChannel.ForAddress(address);
        _client = new WardenService.WardenServiceClient(_channel);
    }

    // =========================================================================
    // Pipeline Operations
    // =========================================================================

    /// <summary>
    /// Execute validation pipeline on a path.
    /// </summary>
    public async Task<PipelineResult> ExecutePipelineAsync(
        string path,
        IEnumerable<string>? frames = null,
        CancellationToken cancellationToken = default)
    {
        var request = new PipelineRequest
        {
            Path = path,
            Parallel = true,
            TimeoutSeconds = 300
        };

        if (frames != null)
        {
            request.Frames.AddRange(frames);
        }

        return await _client.ExecutePipelineAsync(request, cancellationToken: cancellationToken);
    }

    /// <summary>
    /// Execute pipeline with streaming progress updates.
    /// </summary>
    public async IAsyncEnumerable<PipelineEvent> ExecutePipelineStreamAsync(
        string path,
        IEnumerable<string>? frames = null,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        var request = new PipelineRequest
        {
            Path = path,
            Parallel = true
        };

        if (frames != null)
        {
            request.Frames.AddRange(frames);
        }

        using var call = _client.ExecutePipelineStream(request, cancellationToken: cancellationToken);

        await foreach (var evt in call.ResponseStream.ReadAllAsync(cancellationToken))
        {
            yield return evt;
        }
    }

    // =========================================================================
    // LLM Operations
    // =========================================================================

    /// <summary>
    /// Analyze code with LLM.
    /// </summary>
    public async Task<LlmAnalyzeResult> AnalyzeWithLlmAsync(
        string code,
        string prompt,
        string? provider = null,
        CancellationToken cancellationToken = default)
    {
        var request = new LlmAnalyzeRequest
        {
            Code = code,
            Prompt = prompt
        };

        if (!string.IsNullOrEmpty(provider))
        {
            request.Provider = provider;
        }

        return await _client.AnalyzeWithLlmAsync(request, cancellationToken: cancellationToken);
    }

    /// <summary>
    /// Classify code to determine recommended frames.
    /// </summary>
    public async Task<ClassifyResult> ClassifyCodeAsync(
        string code,
        string? filePath = null,
        CancellationToken cancellationToken = default)
    {
        var request = new ClassifyRequest
        {
            Code = code
        };

        if (!string.IsNullOrEmpty(filePath))
        {
            request.FilePath = filePath;
        }

        return await _client.ClassifyCodeAsync(request, cancellationToken: cancellationToken);
    }

    // =========================================================================
    // Configuration
    // =========================================================================

    /// <summary>
    /// Get available validation frames.
    /// </summary>
    public async Task<FrameList> GetAvailableFramesAsync(
        CancellationToken cancellationToken = default)
    {
        return await _client.GetAvailableFramesAsync(new Empty(), cancellationToken: cancellationToken);
    }

    /// <summary>
    /// Get available LLM providers.
    /// </summary>
    public async Task<ProviderList> GetAvailableProvidersAsync(
        CancellationToken cancellationToken = default)
    {
        return await _client.GetAvailableProvidersAsync(new Empty(), cancellationToken: cancellationToken);
    }

    /// <summary>
    /// Get current configuration.
    /// </summary>
    public async Task<ConfigurationResponse> GetConfigurationAsync(
        CancellationToken cancellationToken = default)
    {
        return await _client.GetConfigurationAsync(new Empty(), cancellationToken: cancellationToken);
    }

    // =========================================================================
    // Health & Status
    // =========================================================================

    /// <summary>
    /// Check if server is healthy.
    /// </summary>
    public async Task<HealthResponse> HealthCheckAsync(
        CancellationToken cancellationToken = default)
    {
        return await _client.HealthCheckAsync(new Empty(), cancellationToken: cancellationToken);
    }

    /// <summary>
    /// Get server status.
    /// </summary>
    public async Task<StatusResponse> GetStatusAsync(
        CancellationToken cancellationToken = default)
    {
        return await _client.GetStatusAsync(new Empty(), cancellationToken: cancellationToken);
    }

    /// <summary>
    /// Check if connected to server.
    /// </summary>
    public async Task<bool> IsConnectedAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            var health = await HealthCheckAsync(cancellationToken);
            return health.Healthy;
        }
        catch
        {
            return false;
        }
    }

    // =========================================================================
    // Dispose
    // =========================================================================

    public void Dispose()
    {
        if (_disposed) return;
        _channel.Dispose();
        _disposed = true;
    }
}

// ============================================================================
// Extension Methods for convenient usage
// ============================================================================

public static class WardenClientExtensions
{
    /// <summary>
    /// Execute security scan only.
    /// </summary>
    public static Task<PipelineResult> SecurityScanAsync(
        this WardenClient client,
        string path,
        CancellationToken cancellationToken = default)
    {
        return client.ExecutePipelineAsync(path, new[] { "security" }, cancellationToken);
    }

    /// <summary>
    /// Execute full validation (all frames).
    /// </summary>
    public static Task<PipelineResult> FullValidationAsync(
        this WardenClient client,
        string path,
        CancellationToken cancellationToken = default)
    {
        return client.ExecutePipelineAsync(path, null, cancellationToken);
    }

    /// <summary>
    /// Quick code review with LLM.
    /// </summary>
    public static Task<LlmAnalyzeResult> QuickReviewAsync(
        this WardenClient client,
        string code,
        CancellationToken cancellationToken = default)
    {
        return client.AnalyzeWithLlmAsync(
            code,
            "Review this code for bugs, security issues, and improvements. Be concise.",
            cancellationToken: cancellationToken);
    }
}
