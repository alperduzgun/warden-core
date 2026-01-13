# Warden gRPC Test Guide

## Postman gRPC Kurulumu (Server Reflection)

Server reflection aktif olduğunda Postman proto dosyası olmadan tüm servisleri otomatik keşfeder.

### 1. Yeni gRPC Request Oluştur
1. Postman'da **New** > **gRPC Request**
2. Server URL: `localhost:50051`

### 2. Server Reflection Kullan (Önerilen)
1. **Service definition** bölümünde **"Using server reflection"** seç
2. Postman otomatik olarak tüm metodları listeler
3. Proto dosyası import etmeye gerek yok!

> **Not:** Server değiştiğinde Postman otomatik güncellenir.

### Alternatif: Manuel Proto Import
1. **Service definition** bölümünde **Import .proto file**
2. Dosya seç: `src/warden/grpc/protos/warden.proto`
3. Import path ekle: `src/warden/grpc/protos`

### 3. Method Seç
Dropdown'dan method seç:
- `warden.WardenService/HealthCheck`
- `warden.WardenService/GetStatus`
- `warden.WardenService/ExecutePipeline`
- vs.

### 4. Message Yaz
Her method için örnek mesajlar aşağıda.

---

## gRPC Test Mesajları

### HealthCheck
```json
{}
```

### GetStatus
```json
{}
```

### GetAvailableFrames
```json
{}
```

### GetAvailableProviders
```json
{}
```

### GetConfiguration
```json
{}
```

### ExecutePipeline
```json
{
  "path": "./src",
  "frames": ["security", "chaos"],
  "parallel": true,
  "timeout_seconds": 300
}
```

### ExecutePipeline (Security Only)
```json
{
  "path": "./src",
  "frames": ["security"]
}
```

### ExecutePipeline (All Frames)
```json
{
  "path": "./src",
  "parallel": true
}
```

### ExecutePipelineStream (Server Streaming)
```json
{
  "path": "./src",
  "frames": ["security"]
}
```
**Not:** Bu streaming response döner, Postman'da stream olarak görürsün.

### AnalyzeWithLlm
```json
{
  "code": "def process(user_id):\n    query = f\"SELECT * FROM users WHERE id = {user_id}\"\n    return db.execute(query)",
  "prompt": "Identify security vulnerabilities and suggest fixes.",
  "provider": "anthropic",
  "temperature": 0.7,
  "max_tokens": 1000
}
```

### AnalyzeWithLlm (Quick Review)
```json
{
  "code": "async def fetch_data(url):\n    async with httpx.AsyncClient() as client:\n        response = await client.get(url)\n        return response.json()",
  "prompt": "Review this code for bugs and security issues."
}
```

### ClassifyCode
```json
{
  "code": "import asyncio\nfrom fastapi import FastAPI\nfrom sqlalchemy import create_engine\n\napp = FastAPI()\n\n@app.get('/users')\nasync def get_users():\n    return []",
  "file_path": "main.py"
}
```

---

## Expected Responses

### HealthCheck Response
```json
{
  "healthy": true,
  "version": "1.0.0",
  "uptime_seconds": 3600,
  "components": {
    "bridge": true,
    "orchestrator": true,
    "llm": true
  }
}
```

### GetStatus Response
```json
{
  "running": true,
  "active_pipelines": 0,
  "total_scans": 10,
  "total_findings": 50,
  "memory_mb": 256,
  "cpu_percent": 5.5
}
```

### ExecutePipeline Response
```json
{
  "success": true,
  "run_id": "abc-123",
  "total_findings": 5,
  "critical_count": 1,
  "high_count": 2,
  "medium_count": 2,
  "low_count": 0,
  "findings": [
    {
      "id": "f-001",
      "title": "SQL Injection",
      "severity": "CRITICAL",
      "file_path": "src/db.py",
      "line_number": 42
    }
  ],
  "duration_ms": 1500
}
```

### ExecutePipelineStream Events
```json
{"event_type": "pipeline_start", "message": "Starting pipeline..."}
{"event_type": "stage_start", "stage": "security", "progress": 0.0}
{"event_type": "progress", "stage": "security", "progress": 0.5, "message": "Analyzing files..."}
{"event_type": "finding", "finding": {"id": "f-001", "title": "SQL Injection", "severity": "CRITICAL"}}
{"event_type": "stage_complete", "stage": "security", "progress": 1.0}
{"event_type": "pipeline_complete", "progress": 1.0, "message": "Pipeline completed"}
```

### ClassifyCode Response
```json
{
  "has_async_operations": true,
  "has_user_input": false,
  "has_database_operations": true,
  "has_network_calls": true,
  "has_file_operations": false,
  "has_authentication": false,
  "detected_frameworks": ["fastapi", "sqlalchemy"],
  "recommended_frames": ["security", "async", "sql"],
  "confidence": 0.95
}
```

---

## grpcurl ile Test (Terminal)

```bash
# Kurulum
brew install grpcurl

# Test script
./tests/postman/test_grpc.sh

# Tek test
./tests/postman/test_grpc.sh health
./tests/postman/test_grpc.sh pipeline
```

---

## Server Başlatma

```bash
cd /path/to/warden-core
source .venv/bin/activate
python start_grpc_server.py --port 50051
```

## Endpoints

| Method | Type | Description |
|--------|------|-------------|
| HealthCheck | Unary | Server health |
| GetStatus | Unary | Runtime status |
| GetAvailableFrames | Unary | List frames |
| GetAvailableProviders | Unary | List LLM providers |
| GetConfiguration | Unary | Full config |
| ExecutePipeline | Unary | Run pipeline (sync) |
| ExecutePipelineStream | Server Stream | Run pipeline (realtime) |
| AnalyzeWithLlm | Unary | LLM code analysis |
| ClassifyCode | Unary | Code classification |
