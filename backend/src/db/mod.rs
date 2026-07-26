//! Turso libSQL client wrapper.
//!
//! Per R2 §1.4 we keep a single `Arc<libsql::Connection>` in `AppState`.
//! `libsql`'s HTTP transport is stateless and reqwest's own pool handles
//! keep-alive underneath — no external pool crate needed.

use std::sync::Arc;

use secrecy::ExposeSecret;

use crate::config::TursoConfig;

/// Thin wrapper around `libsql::Connection` so the rest of the app doesn't
/// need to depend on the crate directly.
#[derive(Clone)]
pub struct Db {
    conn: Arc<libsql::Connection>,
}

impl Db {
    /// Build a remote libSQL client and open a connection.
    ///
    /// This does *not* pre-warm the connection; the first `ping()` will make
    /// the first HTTP round-trip.
    pub async fn connect(cfg: &TursoConfig) -> anyhow::Result<Self> {
        let database = libsql::Builder::new_remote(
            cfg.url.clone(),
            cfg.auth_token.expose_secret().to_string(),
        )
        .build()
        .await?;

        let conn = database.connect()?;
        Ok(Self { conn: Arc::new(conn) })
    }

    /// Cheap read-only round-trip to verify Turso is reachable.
    /// Used by the `/health` endpoint and by startup smoke-checks.
    pub async fn ping(&self) -> anyhow::Result<()> {
        // `SELECT 1` returns exactly one row, one column; we just need the
        // network round-trip to succeed.
        let mut rows = self.conn.query("SELECT 1", ()).await?;
        let _ = rows.next().await?;
        Ok(())
    }

    /// Expose the raw connection for future repository modules. Kept
    /// `pub(crate)` so the surface stays inside the backend crate.
    #[allow(dead_code)]
    pub(crate) fn conn(&self) -> &libsql::Connection {
        &self.conn
    }
}
