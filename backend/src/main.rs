//! Composition root for the exam-prep Rust backend (v3 Phase 1 skeleton).
//!
//! Responsibilities kept intentionally narrow:
//!   1. Load config from the environment.
//!   2. Initialise tracing.
//!   3. Open the Turso connection and smoke-ping it.
//!   4. Build the axum router.
//!   5. Serve on `$PORT` (Render convention) with graceful shutdown.
//!
//! No business logic lives here.

mod api;
mod config;
mod db;
mod error;
#[allow(dead_code)]
mod middleware;
#[allow(dead_code)]
mod models;
#[allow(dead_code)]
mod schemas;
#[allow(dead_code)]
mod services;

use std::sync::Arc;

use anyhow::Context;
use tokio::net::TcpListener;
use tokio::signal;
use tracing_subscriber::prelude::*;
use tracing_subscriber::EnvFilter;

use crate::api::AppState;
use crate::config::Config;
use crate::db::Db;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Env vars first — must succeed before tracing so we honour LOG_LEVEL.
    let cfg = Config::from_env().context("failed to load configuration")?;
    init_tracing(&cfg.log_level);

    tracing::info!(bind = %cfg.bind_addr, "starting exam-prep backend");

    let db = Db::connect(&cfg.turso)
        .await
        .context("failed to build Turso client")?;

    // Startup smoke-check: fail fast if Turso is unreachable. The health
    // endpoint uses the same code path per-request.
    match db.ping().await {
        Ok(()) => tracing::info!("Turso ping ok"),
        Err(err) => tracing::warn!(error = %err, "Turso ping failed at startup — /health will report degraded"),
    }

    let state = AppState {
        db,
        config: Arc::new(cfg.clone()),
    };
    let app = api::router(state);

    let listener = TcpListener::bind(cfg.bind_addr)
        .await
        .with_context(|| format!("failed to bind {}", cfg.bind_addr))?;
    tracing::info!(addr = %cfg.bind_addr, "listening");

    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await
        .context("axum::serve failed")?;

    Ok(())
}

fn init_tracing(log_level: &str) {
    let filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new(log_level));

    let fmt_layer = tracing_subscriber::fmt::layer()
        .with_target(true)
        .with_line_number(false);

    tracing_subscriber::registry()
        .with(filter)
        .with(fmt_layer)
        .init();
}

/// Await SIGTERM or Ctrl-C. Render sends SIGTERM before killing the
/// container; catching it lets in-flight requests drain.
async fn shutdown_signal() {
    let ctrl_c = async {
        let _ = signal::ctrl_c().await;
    };

    #[cfg(unix)]
    let terminate = async {
        match signal::unix::signal(signal::unix::SignalKind::terminate()) {
            Ok(mut s) => {
                s.recv().await;
            }
            Err(err) => {
                tracing::error!(error = %err, "failed to install SIGTERM handler");
                std::future::pending::<()>().await;
            }
        }
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        _ = ctrl_c => tracing::info!("received Ctrl-C, shutting down"),
        _ = terminate => tracing::info!("received SIGTERM, shutting down"),
    }
}
