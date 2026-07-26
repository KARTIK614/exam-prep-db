# exam-prep-backend

Rust backend for the exam-prep platform (v3 Phase 1 skeleton).

This crate currently exposes a single route (`GET /health`) that pings
Turso and returns `{status, turso}`. All other routes will be layered on
in later phases (see `docs/plans/v3-R4-api-auth.md`).

## Quick start

```sh
cd backend
cp .env.example .env      # then edit with real values
cargo run
# → listening on 0.0.0.0:3000

curl -s http://localhost:3000/health
# → {"status":"ok","turso":"ok"}
```

## Verifying the build

```sh
cargo check           # fast type-check
cargo build --release # full optimized build
```

## Environment variables

Required:

| Name                | Purpose                                            |
|---------------------|----------------------------------------------------|
| `TURSO_DB_URL`      | libSQL URL, e.g. `libsql://<db>.turso.io`          |
| `TURSO_AUTH_TOKEN`  | Turso auth JWT                                     |
| `JWT_SECRET`        | HMAC secret for access tokens                      |
| `JWT_REFRESH_SECRET`| HMAC secret for refresh tokens                     |

Optional:

| Name                       | Default                                       | Purpose                             |
|----------------------------|-----------------------------------------------|-------------------------------------|
| `PORT`                     | `3000`                                        | HTTP listen port (Render sets this) |
| `LOG_LEVEL`                | `info,exam_prep_backend=debug,tower_http=info`| `tracing` env-filter directives     |
| `CORS_ORIGIN`              | `*` (Any)                                     | Allowed CORS origin                 |
| `GEMINI_API_KEY`           | —                                             | LLM provider                        |
| `DEEPSEEK_PRIMARY_KEY`     | —                                             | LLM provider                        |
| `DEEPSEEK_SECONDARY_KEY`   | —                                             | LLM provider fallback               |
| `GLM_API_KEY`              | —                                             | LLM provider                        |

## Layout

```
backend/
├── Cargo.toml
├── README.md
└── src/
    ├── main.rs        # composition root
    ├── config.rs      # env-driven Config struct
    ├── error.rs       # AppError + IntoResponse
    ├── api/
    │   ├── mod.rs     # router + middleware wiring
    │   └── health.rs  # GET /health
    └── db/
        └── mod.rs     # Turso client + ping()
```

See `docs/plans/v3-R1-rust-backend.md` for the full architectural plan
this skeleton is built against.
