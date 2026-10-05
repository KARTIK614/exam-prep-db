//! Turso libSQL client wrapper.
//!
//! Per R2 §1.4 we keep one shared `libsql::Connection` in `AppState`.
//! `libsql`'s HTTP transport is stateless and reqwest's own pool handles
//! keep-alive underneath — no external pool crate needed.
//!
//! One catch: a remote connection carries a Hrana *stream*, and the server
//! expires streams after a few seconds of inactivity. A connection whose
//! stream expired answers every later query with `STREAM_EXPIRED`, so a
//! student thinking on one question for four minutes would find the next
//! autosave (and everything after it) failing. `conn()` therefore swaps in
//! a fresh connection — a local, network-free operation — when the shared
//! one has been idle longer than `IDLE_RECONNECT_MS`, or when a query has
//! reported a broken stream (see `mark_stream_broken`).

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, RwLock};
use std::time::{SystemTime, UNIX_EPOCH};

use secrecy::ExposeSecret;

use crate::config::TursoConfig;

/// Reconnect when the shared connection has been idle this long. Well
/// under the server's stream-expiry window.
const IDLE_RECONNECT_MS: u64 = 4_000;

/// Set when any query fails with a Hrana stream error; the next `conn()`
/// call replaces the connection.
static STREAM_BROKEN: AtomicBool = AtomicBool::new(false);

/// Called from the `libsql::Error` → `AppError` conversion.
pub(crate) fn mark_stream_broken_if(err_text: &str) {
    if err_text.contains("STREAM_EXPIRED") || (err_text.contains("stream") && err_text.contains("expired")) {
        STREAM_BROKEN.store(true, Ordering::Relaxed);
    }
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

/// Thin wrapper around `libsql::Connection` so the rest of the app doesn't
/// need to depend on the crate directly.
#[derive(Clone)]
pub struct Db {
    database: Arc<libsql::Database>,
    conn: Arc<RwLock<Arc<libsql::Connection>>>,
    last_used_ms: Arc<AtomicU64>,
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
        Ok(Self {
            database: Arc::new(database),
            conn: Arc::new(RwLock::new(Arc::new(conn))),
            last_used_ms: Arc::new(AtomicU64::new(now_ms())),
        })
    }

    /// Cheap read-only round-trip to verify Turso is reachable.
    /// Used by the `/health` endpoint and by startup smoke-checks.
    pub async fn ping(&self) -> anyhow::Result<()> {
        // `SELECT 1` returns exactly one row, one column; we just need the
        // network round-trip to succeed.
        let mut rows = self.conn().query("SELECT 1", ()).await?;
        let _ = rows.next().await?;
        Ok(())
    }

    /// The shared connection, replaced first if it went idle or its stream
    /// broke. Requests already in flight keep their own `Arc` and finish on
    /// the old connection.
    pub(crate) fn conn(&self) -> Arc<libsql::Connection> {
        let now = now_ms();
        let last = self.last_used_ms.swap(now, Ordering::Relaxed);
        let broken = STREAM_BROKEN.swap(false, Ordering::Relaxed);
        if broken || now.saturating_sub(last) > IDLE_RECONNECT_MS {
            match self.database.connect() {
                Ok(fresh) => {
                    if let Ok(mut slot) = self.conn.write() {
                        *slot = Arc::new(fresh);
                    }
                }
                Err(e) => tracing::warn!(error = %e, "libsql reconnect failed; reusing connection"),
            }
        }
        match self.conn.read() {
            Ok(c) => Arc::clone(&c),
            Err(poisoned) => Arc::clone(&poisoned.into_inner()),
        }
    }
}
