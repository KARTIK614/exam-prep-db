# syntax=docker/dockerfile:1.7
#
# Multi-stage build for exam-prep-backend (Rust axum).
# Stage 1 compiles the release binary with a cache-mounted target dir.
# Stage 2 ships a distroless cc-debian12 runtime with only the binary.

# ─── Stage 1: builder ────────────────────────────────────────────────
FROM rust:1.83-slim AS builder

# libsql needs a C toolchain + OpenSSL headers for the remote HTTPS client.
RUN apt-get update && apt-get install -y --no-install-recommends \
      pkg-config \
      libssl-dev \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Pre-cache deps: copy only the manifest first so `cargo fetch` layer is
# cached across source-only changes.
COPY Cargo.toml Cargo.lock ./
RUN mkdir -p src && echo 'fn main() {}' > src/main.rs && \
    cargo fetch && \
    rm -rf src

# Now copy real source and build.
COPY src ./src
RUN --mount=type=cache,target=/build/target,sharing=locked \
    --mount=type=cache,target=/usr/local/cargo/registry,sharing=locked \
    cargo build --release --locked && \
    cp /build/target/release/exam-prep-backend /usr/local/bin/exam-prep-backend

# ─── Stage 2: runtime ────────────────────────────────────────────────
FROM gcr.io/distroless/cc-debian12:nonroot AS runtime

# Distroless nonroot uid=65532, gid=65532 — no shell, no package manager.
WORKDIR /app

# CA certs shipped by distroless-cc — libsql HTTPS works out of the box.
COPY --from=builder /usr/local/bin/exam-prep-backend /app/exam-prep-backend

# Render injects $PORT (default 10000); axum binds 0.0.0.0:$PORT.
# Health endpoint at /health returns 200 when Turso ping succeeds.
EXPOSE 3000

USER nonroot:nonroot

ENTRYPOINT ["/app/exam-prep-backend"]
