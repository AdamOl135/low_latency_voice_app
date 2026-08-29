# Multi-stage Dockerfile for Low-Latency Voice App Backend
# Stage 1: Build static Go binary with Alpine builder
FROM golang:1.23-alpine AS builder

# Install build dependencies and root certificates
RUN apk add --no-cache ca-certificates git tzdata

WORKDIR /build

# Cache Go module dependencies
COPY go.mod go.sum ./
RUN go mod download

# Copy source tree
COPY . .

# Compile optimized static binary with stripped debug symbols
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build \
    -trimpath \
    -ldflags="-s -w -extldflags '-static'" \
    -o /app/server \
    ./cmd/server

# Stage 2: Ultra-lightweight Alpine runtime image (<20MB)
FROM alpine:3.20

# Install runtime SSL certificates and timezone data
RUN apk --no-cache add ca-certificates tzdata

WORKDIR /app

# Copy compiled static binary from builder
COPY --from=builder /app/server /app/server

# Create data directory for SQLite WAL persistence
RUN mkdir -p /app/data && chmod 755 /app/data

# Default environment configuration
ENV PORT=8080 \
    UDP_PORT=7878 \
    DB_PATH=/app/data/voiceapp.db

# Expose HTTP/WebSocket control plane (8080/tcp) and UDP voice audio plane (7878/udp)
EXPOSE 8080/tcp
EXPOSE 7878/udp

# Mount point for persistent database and media
VOLUME ["/app/data"]

# Health check against HTTP health endpoint
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8080/health || exit 1

# Start backend server
ENTRYPOINT ["/app/server"]
