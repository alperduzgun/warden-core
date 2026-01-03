# Build Stage
FROM python:3.11-slim as builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js (for Warden CLI UI)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs

WORKDIR /app

# Copy project files
COPY . .

# Install Python dependencies and Warden
RUN pip install --no-cache-dir build \
    && pip install --no-cache-dir .

# Install Node.js CLI dependencies
WORKDIR /app/cli
RUN npm install && npm run build

# Runtime Stage
FROM python:3.11-slim

# Install runtime dependencies (Node.js required for UI)
RUN apt-get update && apt-get install -y \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin/warden /usr/local/bin/warden

# Copy the CLI source code (needed for the 'warden chat' command to locate the Node project)
COPY --from=builder /app/cli /app/cli

# Set environment variables
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

# Default entrypoint
ENTRYPOINT ["warden"]
CMD ["--help"]
