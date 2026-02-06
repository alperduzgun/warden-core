# Build Stage
FROM python:3.11-slim as builder

# Install build dependencies + curl for Node.js setup
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js (for Warden CLI UI)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency files first (better layer caching)
COPY pyproject.toml setup.py setup.cfg README.md ./

# Install Python dependencies only (separate layer for caching)
RUN pip install --no-cache-dir build \
    && pip install --no-cache-dir -e .

# Copy source code (changes less frequently than deps)
COPY src/ ./src/

# Build CLI separately (better caching)
COPY cli/package.json cli/package-lock.json ./cli/
WORKDIR /app/cli
RUN npm ci --only=production --silent

COPY cli/ ./
RUN npm run build && npm prune --production

# Runtime Stage (optimized for size)
FROM python:3.11-slim

# Install only runtime dependencies (minimal footprint)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get purge -y --auto-remove curl \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Create non-root user for security
RUN useradd -m -u 1000 warden

WORKDIR /app

# Copy only necessary runtime artifacts from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin/warden /usr/local/bin/warden
COPY --from=builder /app/cli/dist /app/cli/dist
COPY --from=builder /app/cli/package.json /app/cli/package.json

# Set ownership of /app to warden user
RUN chown -R warden:warden /app

# Set environment variables
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

# Switch to non-root user for security
USER warden

# Default entrypoint
ENTRYPOINT ["warden"]
CMD ["--help"]
