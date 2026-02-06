# Build Stage
FROM python:3.11-slim as builder

# Install build dependencies (removed git and curl - not needed for builds)
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js (for Warden CLI UI)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only necessary files for build (avoid copying entire repo)
COPY pyproject.toml setup.py setup.cfg README.md ./
COPY src/ ./src/
COPY cli/ ./cli/

# Install Python dependencies and Warden
RUN pip install --no-cache-dir build \
    && pip install --no-cache-dir .

# Install Node.js CLI dependencies and build
WORKDIR /app/cli
RUN npm ci --only=production && npm run build

# Runtime Stage
FROM python:3.11-slim

# Install only Node.js runtime (no curl needed in final image)
RUN apt-get update \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && apt-get remove -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

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
