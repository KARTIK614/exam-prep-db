//! Environment-driven configuration.
//!
//! Loaded exactly once at startup by `Config::from_env()`. All secrets are
//! wrapped in `secrecy::SecretString` so a stray `Debug`/`Display` never
//! leaks the raw value.

use std::env;
use std::net::{IpAddr, Ipv4Addr, SocketAddr};

use secrecy::SecretString;

/// Top-level configuration, populated from environment variables.
#[derive(Debug, Clone)]
pub struct Config {
    /// Where the HTTP server should listen. Render sets `PORT`; we default
    /// to 3000 for local dev.
    pub bind_addr: SocketAddr,

    /// Log level for `tracing_subscriber`'s env filter. Reads `LOG_LEVEL`
    /// with a fallback of `info,exam_prep_backend=debug`.
    pub log_level: String,

    /// Comma-separated allowed CORS origins. Empty = permissive
    /// (`Any`) — only intended for local dev; set explicitly in prod.
    pub cors_origin: Option<String>,

    pub turso: TursoConfig,
    pub jwt: JwtConfig,
    pub llm: LlmConfig,
}

#[derive(Debug, Clone)]
pub struct TursoConfig {
    pub url: String,
    pub auth_token: SecretString,
}

#[derive(Debug, Clone)]
pub struct JwtConfig {
    pub access_secret: SecretString,
    pub refresh_secret: SecretString,
}

#[derive(Debug, Clone)]
pub struct LlmConfig {
    pub gemini_api_key: Option<SecretString>,
    pub deepseek_primary_key: Option<SecretString>,
    pub deepseek_secondary_key: Option<SecretString>,
    pub glm_api_key: Option<SecretString>,
}

#[derive(Debug, thiserror::Error)]
pub enum ConfigError {
    #[error("required env var `{0}` is missing")]
    Missing(&'static str),

    #[error("env var `{name}` has invalid value: {reason}")]
    Invalid { name: &'static str, reason: String },
}

impl Config {
    /// Read every relevant env var. Errors out on the first required-but-missing
    /// value so `main.rs` can print a human-friendly message and exit.
    pub fn from_env() -> Result<Self, ConfigError> {
        // Best-effort .env load. If it's missing (prod), that's fine —
        // Render supplies vars via the environment.
        let _ = dotenvy::dotenv();

        let port: u16 = match env::var("PORT") {
            Ok(v) => v.parse().map_err(|e: std::num::ParseIntError| ConfigError::Invalid {
                name: "PORT",
                reason: e.to_string(),
            })?,
            Err(_) => 3000,
        };
        let bind_addr = SocketAddr::new(IpAddr::V4(Ipv4Addr::UNSPECIFIED), port);

        let log_level = env::var("LOG_LEVEL")
            .unwrap_or_else(|_| "info,exam_prep_backend=debug,tower_http=info".to_string());

        let cors_origin = env::var("CORS_ORIGIN").ok().filter(|s| !s.is_empty());

        let turso = TursoConfig {
            url: require("TURSO_DB_URL")?,
            auth_token: require_secret("TURSO_AUTH_TOKEN")?,
        };

        let jwt = JwtConfig {
            access_secret: require_secret("JWT_SECRET")?,
            refresh_secret: require_secret("JWT_REFRESH_SECRET")?,
        };

        let llm = LlmConfig {
            gemini_api_key: optional_secret("GEMINI_API_KEY"),
            deepseek_primary_key: optional_secret("DEEPSEEK_PRIMARY_KEY"),
            deepseek_secondary_key: optional_secret("DEEPSEEK_SECONDARY_KEY"),
            glm_api_key: optional_secret("GLM_API_KEY"),
        };

        Ok(Self {
            bind_addr,
            log_level,
            cors_origin,
            turso,
            jwt,
            llm,
        })
    }
}

fn require(name: &'static str) -> Result<String, ConfigError> {
    env::var(name)
        .ok()
        .filter(|s| !s.is_empty())
        .ok_or(ConfigError::Missing(name))
}

fn require_secret(name: &'static str) -> Result<SecretString, ConfigError> {
    require(name).map(SecretString::from)
}

fn optional_secret(name: &'static str) -> Option<SecretString> {
    env::var(name)
        .ok()
        .filter(|s| !s.is_empty())
        .map(SecretString::from)
}
