//! HTTP router assembly.
//!
//! Composes tracing / CORS / request-id middleware around a router that
//! exposes:
//!
//!   - `/health`                       — public liveness probe
//!   - `/api/v1/auth/*`                — public auth endpoints (register,
//!                                       login, refresh, logout, forgot-
//!                                       password, reset-password/{token})
//!   - `GET|PATCH /api/v1/me`          — auth-gated profile endpoints
//!   - `/api/v1/admin/*`               — admin-gated (empty for now — added
//!                                       in future phases; the router
//!                                       reserves the tree)
//!
//! Per-route rate limits (R4 §6.1) are applied via `tower_governor`.

use std::sync::Arc;
use std::time::Duration;

use axum::extract::Request;
use axum::http::{header, HeaderValue, Method};
use axum::routing::{delete, get, patch, post};
use axum::Router;
use tower::ServiceBuilder;
use tower_governor::governor::GovernorConfigBuilder;
use tower_governor::GovernorLayer;
use tower_governor::key_extractor::SmartIpKeyExtractor;
use tower_http::catch_panic::CatchPanicLayer;
use tower_http::cors::{Any, CorsLayer};
use tower_http::request_id::{MakeRequestUuid, PropagateRequestIdLayer, SetRequestIdLayer};
use tower_http::trace::{DefaultOnResponse, TraceLayer};
use tower_http::LatencyUnit;
// Note: `LatencyUnit` is a top-level re-export in tower-http 0.6 and is
// exposed regardless of the `trace` sub-feature.
use tracing::Level;

use crate::config::Config;
use crate::db::Db;

pub mod admin;
pub mod analytics;
pub mod auth;
pub mod bookmarks;
pub mod deep_dive;
pub mod errors;
pub mod exam_presets;
pub mod flags;
pub mod health;
pub mod me;
pub mod pagination;
pub mod questions;
pub mod review;
pub mod search;
pub mod settings;
pub mod tests;
pub mod topics;

/// Application state passed to every handler via `axum::extract::State`.
///
/// All fields are `Clone`-cheap (`Arc` or handle types) so the whole struct
/// can be cloned per-request without heap churn.
#[derive(Clone)]
pub struct AppState {
    pub db: Db,
    pub config: Arc<Config>,
}

/// Convenience macro-like helper: build a fresh `GovernorLayer` with the
/// default (PeerIP) key extractor at the given per-IP token-bucket
/// interval + burst. Used inline at each `.route_layer(...)` site.
///
/// `per_second(N)` in `tower_governor`'s builder means "one request per N
/// seconds" (i.e. the token replenishment interval), not "N requests per
/// second".
macro_rules! ip_rl {
    ($per_second:expr, $burst:expr) => {{
        // SmartIpKeyExtractor honours X-Forwarded-For / X-Real-IP before
        // falling back to the direct socket address. Required on Render
        // (proxied) and on localhost (no peer IP header). The plain
        // PeerIpKeyExtractor returns "Unable To Extract Key!" as a 500 in
        // both cases — see F06 in docs/plans/V3_CRITIC_REPORT.md.
        let cfg = GovernorConfigBuilder::default()
            .per_second($per_second)
            .burst_size($burst)
            .key_extractor(SmartIpKeyExtractor)
            .finish()
            .expect("valid governor config");
        GovernorLayer { config: Arc::new(cfg) }
    }};
}

/// Build the top-level router with all middleware wired in.
pub fn router(state: AppState) -> Router {
    let cors = build_cors(state.config.cors_origin.as_deref());

    // `X-Request-Id` header name — set once, referenced twice below.
    let request_id_header = header::HeaderName::from_static("x-request-id");

    // Rate-limit tuning per R4 §6.1. In tower_governor's builder,
    // `per_second(N)` means "one request every N seconds" (i.e. the
    // token replenishment interval), NOT "N requests per second".
    // `burst_size` is the token-bucket capacity — how many requests can
    // arrive back-to-back before throttling engages.
    //
    //   5/min  → per_second=12, burst=5     (1 replenished every 12s)
    //   3/min  → per_second=20, burst=3
    //   60/min → per_second=1,  burst=60
    let register_limit = ip_rl!(12, 5);
    let login_limit = ip_rl!(12, 5);
    let forgot_limit = ip_rl!(20, 3);
    let reset_limit = ip_rl!(12, 5);
    // Refresh: legit clients refresh once every ~14 minutes (access-token
    // TTL is 15). A short interval with a small burst is plenty.
    let refresh_limit = ip_rl!(2, 10);

    // ----- public /api/v1/auth/* -----
    let auth_public = Router::new()
        .route(
            "/register",
            post(auth::register).route_layer(register_limit),
        )
        .route("/login", post(auth::login).route_layer(login_limit))
        .route("/refresh", post(auth::refresh).route_layer(refresh_limit))
        .route("/logout", post(auth::logout))
        .route(
            "/forgot-password",
            post(auth::forgot_password).route_layer(forgot_limit),
        )
        .route(
            "/reset-password/{token}",
            post(auth::reset_password).route_layer(reset_limit),
        );

    // ----- authenticated /api/v1/me + content endpoints -----
    // Direct routes on the v1 router so paths resolve to `/api/v1/<x>`
    // exactly (nesting an inner router at `/` would map to `/<x>/`).
    //
    // Auth is enforced per-handler via the `RequireAuth` extractor
    // (see `crate::middleware::auth`) rather than a route-layer.
    let v1 = Router::new()
        .nest("/auth", auth_public)
        .route("/me", get(me::get_me).patch(me::patch_me))
        .route("/topics", get(topics::list_topics))
        .route("/topics/{id}", get(topics::get_topic))
        .route("/questions", get(questions::list_questions))
        .route("/questions/{id}", get(questions::get_question))
        .route("/search", get(search::search))
        // --- exam presets (Sujit feedback) ------------------------
        .route("/exam-presets", get(exam_presets::list_presets))
        // --- analytics (Phase 6) -----------------------------------
        .route("/analytics/mastery", get(analytics::mastery))
        .route("/analytics/heatmap", get(analytics::heatmap))
        .route("/analytics/consistency", get(analytics::consistency))
        .route(
            "/analytics/next-weak-topic",
            get(analytics::next_weak_topic),
        )
        .route("/analytics/pacing", get(analytics::pacing))
        .route("/analytics/error-dist", get(analytics::error_dist))
        .route("/analytics/paper-performance", get(analytics::paper_performance))
        // --- errors (recent wrong answers) -------------------------
        .route("/errors", get(errors::list_errors))
        // --- user settings -----------------------------------------
        .route(
            "/me/settings",
            get(settings::get_settings).patch(settings::patch_settings),
        )
        // --- tests / test-taking (Phase 5) -------------------------
        .route("/tests", post(tests::create_test).get(tests::list_tests))
        .route("/tests/{id}", get(tests::get_test))
        .route("/tests/{id}/answers", post(tests::submit_answer))
        .route("/tests/{id}/mark-for-review", post(tests::mark_for_review))
        .route("/tests/{id}/finish", post(tests::finish))
        .route("/tests/{id}/results", get(tests::get_results))
        .route(
            "/tests/{id}/responses/{question_id}",
            patch(tests::update_note),
        )
        .route("/papers", get(tests::list_papers))
        // --- review / SRS (Phase 6) --------------------------------
        .route("/review/queue", get(review::get_queue))
        .route(
            "/review/answers/{card_id}",
            post(review::answer),
        )
        // --- bookmarks / flags / deep-dive (Phase 7) ---------------
        .route("/bookmarks", get(bookmarks::list_bookmarks))
        .route(
            "/bookmarks/{question_id}",
            post(bookmarks::toggle_bookmark),
        )
        .route(
            "/questions/{question_id}/flag",
            post(flags::flag_question),
        )
        // Deep Dive: 20 requests / hour / IP. In tower_governor, the
        // "per_second(N)" spec is "one replenished every N seconds"; 180
        // seconds ≈ 20/hour with a burst of 20 for concurrent tabs.
        .route(
            "/questions/{question_id}/deep-dive",
            post(deep_dive::deep_dive).route_layer(ip_rl!(180, 20)),
        )
        // --- admin (Phase 7) --------------------------------------
        // Individual routes each pull `RequireAdmin` via their extractor.
        .route("/admin/stats", get(admin::stats::get_stats))
        .route(
            "/admin/questions",
            post(admin::questions::create_question),
        )
        .route(
            "/admin/questions/{id}",
            patch(admin::questions::patch_question)
                .delete(admin::questions::delete_question),
        )
        .route(
            "/admin/questions/bulk-toggle-disabled",
            post(admin::questions::bulk_toggle_disabled),
        )
        .route("/admin/users", get(admin::users::list_users))
        .route(
            "/admin/users/{id}",
            patch(admin::users::patch_user),
        )
        .route("/admin/flags", get(admin::flags::list_flags))
        .route(
            "/admin/flags/{id}/{action}",
            post(admin::flags::flag_action),
        )
        .route(
            "/admin/duplicates",
            get(admin::duplicates::list_duplicates),
        )
        .route(
            "/admin/duplicates/resolve",
            post(admin::duplicates::resolve_duplicate),
        )
        .route("/admin/review", get(admin::review::list_review))
        .route(
            "/admin/review/{question_id}",
            post(admin::review::act_on_review),
        )
        .route(
            "/admin/uploads",
            get(admin::uploads::list_uploads).post(admin::uploads::create_upload),
        )
        .route(
            "/admin/uploads/{id}/extract",
            post(admin::uploads::extract_upload),
        )
        .route(
            "/admin/uploads/{id}/import",
            post(admin::uploads::import_upload),
        )
        // FE mistakenly hits `pdf-uploads` instead of `uploads` on the
        // AdminUploads page — alias both paths so the FE keeps working
        // without a client change. Same handlers on both.
        .route(
            "/admin/pdf-uploads",
            get(admin::uploads::list_uploads).post(admin::uploads::create_upload),
        )
        .route(
            "/admin/pdf-uploads/{id}/extract",
            post(admin::uploads::extract_upload),
        )
        .route(
            "/admin/pdf-uploads/{id}/import",
            post(admin::uploads::import_upload),
        )
        // F02 (V3 critic): rate-limit LLM synthesis. Each start_batch call
        // fans out to DeepSeek/Claude for N generations. An admin token
        // (leaked or rogue) could burn thousands of dollars in minutes.
        // 5/hour per IP = burst 5, replenish every 720s.
        .route(
            "/admin/synthesize",
            post(admin::synthesize::start_batch).route_layer(ip_rl!(720, 5)),
        )
        .route(
            "/admin/synthesize/{batch_id}",
            get(admin::synthesize::get_batch),
        )
        .route(
            "/admin/synthesize/{batch_id}/commit",
            post(admin::synthesize::commit_batch),
        );

    // General limit (60/min per IP fallback) applied at the /api/v1 tree
    // — auth-specific limits above are stricter and applied on top.
    let general_limit = ip_rl!(1, 60);

    let middleware = ServiceBuilder::new()
        // Assign an X-Request-Id if the caller didn't send one.
        .layer(SetRequestIdLayer::new(
            request_id_header.clone(),
            MakeRequestUuid,
        ))
        // Stash the (now-populated) X-Request-Id into a tokio task-local
        // so `AppError::into_response` can echo it into the JSON error
        // envelope. Must run AFTER `SetRequestIdLayer` so the header is
        // present; anything reading REQUEST_ID outside this scope sees
        // `None` and falls back to `null` (harmless).
        .layer(axum::middleware::from_fn(
            |req: axum::extract::Request, next: axum::middleware::Next| async move {
                let rid = req
                    .headers()
                    .get("x-request-id")
                    .and_then(|v| v.to_str().ok())
                    .unwrap_or("-")
                    .to_string();
                crate::error::REQUEST_ID
                    .scope(rid, next.run(req))
                    .await
            },
        ))
        // One tracing span per request, including method + uri + latency.
        .layer(
            TraceLayer::new_for_http()
                .make_span_with(|req: &Request<_>| {
                    let request_id = req
                        .headers()
                        .get("x-request-id")
                        .and_then(|v| v.to_str().ok())
                        .unwrap_or("-");
                    tracing::info_span!(
                        "http_request",
                        method = %req.method(),
                        uri = %req.uri(),
                        request_id = %request_id,
                    )
                })
                .on_response(
                    DefaultOnResponse::new()
                        .level(Level::INFO)
                        .latency_unit(LatencyUnit::Millis),
                ),
        )
        // Bubble the X-Request-Id back out to the client.
        .layer(PropagateRequestIdLayer::new(request_id_header))
        // Convert panics inside handlers into 500s instead of dropping the
        // connection.
        .layer(CatchPanicLayer::new())
        .layer(cors)
        .into_inner();

    Router::new()
        .route("/health", get(health::health))
        .nest("/api/v1", v1.layer(general_limit))
        .layer(middleware)
        .with_state(state)
}

fn build_cors(origin: Option<&str>) -> CorsLayer {
    let base = CorsLayer::new()
        .allow_methods([
            Method::GET,
            Method::POST,
            Method::PUT,
            Method::PATCH,
            Method::DELETE,
            Method::OPTIONS,
        ])
        .allow_headers(Any)
        .max_age(Duration::from_secs(600));

    // F03 (V3 critic): the previous fallback silently allowed `Any` origin
    // when CORS_ORIGIN was unset or malformed. In production that means
    // any website with a stolen JWT could call our API from the browser.
    // Now:
    //   * missing/blank → keep `Any` but only after explicitly unblocking
    //     via `ALLOW_ANY_CORS_ORIGIN=1` (dev/staging escape hatch);
    //     otherwise panic during startup.
    //   * malformed value → panic (fail-fast surface).
    let allow_any = std::env::var("ALLOW_ANY_CORS_ORIGIN")
        .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
        .unwrap_or(false);

    match origin {
        Some(o) if !o.trim().is_empty() => match HeaderValue::from_str(o) {
            Ok(hv) => base.allow_origin(hv),
            Err(err) => panic!(
                "CORS_ORIGIN is set to {o:?} but is not a valid HTTP header value: {err}. \
                 Fix the env var; do not fall back to Any silently."
            ),
        },
        _ if allow_any => {
            tracing::warn!("CORS_ORIGIN unset; falling back to Any because ALLOW_ANY_CORS_ORIGIN=1");
            base.allow_origin(Any)
        }
        _ => panic!(
            "CORS_ORIGIN env var is required in production. Set it to your \
             frontend origin (e.g. https://exam.example.com) or export \
             ALLOW_ANY_CORS_ORIGIN=1 for local development."
        ),
    }
}
