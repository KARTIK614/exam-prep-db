"""Exam Prep Platform — app factory. Register blueprints, wire config + auth, expose `app`."""
import os
import secrets
import logging
from flask import Flask
from flask_session import Session

from config import Config
from db import init_db, close_db
from seed import seed_data
from auth import seed_admin_if_empty, check_auth


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)
    _fill_secret_fallbacks(app)

    Session(app)
    app.teardown_appcontext(close_db)

    try:
        init_db(app)
    except Exception as exc:
        app.logger.error(f"init_db failed (continuing): {exc}", exc_info=True)
    try:
        seed_data(app.config["DB_PATH"])
    except Exception as exc:
        app.logger.warning(f"seed_data skipped: {exc}")
    try:
        seed_admin_if_empty(app)
    except Exception as exc:
        app.logger.error(f"seed_admin_if_empty failed (continuing): {exc}", exc_info=True)

    app.before_request(check_auth)

    from bp_auth import bp as auth_bp
    from bp_main import bp as main_bp
    from bp_tests import bp as tests_bp
    from bp_analytics import bp as analytics_bp
    from bp_errorlog import bp as errorlog_bp
    from bp_api import bp as api_bp
    from bp_doubt import bp as doubt_bp
    from bp_diag import bp as diag_bp
    from bp_admin import bp as admin_bp
    from bp_review import bp as review_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(tests_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(errorlog_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(doubt_bp, url_prefix="/api/doubt")
    # bp_diag disabled — see docs/plans/CRITIC_REPORT_backend.md F06/F31/F43.
    # Endpoints (/diag/<token>, /setup/seed/<token>) had URL-token auth that
    # leaked via logs and enabled admin takeover. Re-enable only if reintroduced
    # behind hardened server-side auth (not URL params).
    if os.environ.get("ENABLE_DIAG_ENDPOINTS") == "1":
        app.register_blueprint(diag_bp)
        app.logger.warning("DIAG ENDPOINTS ENABLED — auth is URL-token-based; kill after use")
    app.register_blueprint(admin_bp)
    app.register_blueprint(review_bp)

    return app


def _fill_secret_fallbacks(app):
    """In production require secrets to be set; locally, generate ephemeral ones with a warning."""
    for var, key in (("FLASK_SECRET_KEY", "SECRET_KEY"), ("JWT_SECRET", "JWT_SECRET")):
        if app.config.get(key):
            continue
        if app.config["IS_PROD"]:
            raise RuntimeError(f"{var} env var is required in production")
        app.config[key] = "dev-" + secrets.token_hex(16)
        logging.getLogger(__name__).warning(
            f"Using ephemeral dev {var} — set env var to persist across restarts"
        )
    if not app.config.get("SEED_ADMIN_PASS") and app.config["IS_PROD"]:
        logging.getLogger(__name__).warning(
            "EXAM_ADMIN_PASS not set — no admin will be seeded. "
            "Set EXAM_ADMIN_USER + EXAM_ADMIN_PASS to bootstrap the first login."
        )


# Module-level app for gunicorn `wsgi:app` compatibility.
app = create_app()


if __name__ == "__main__":
    print("\n" + "=" * 56)
    print("  Exam Platform")
    print("  Running at: http://localhost:5050")
    print("=" * 56 + "\n")
    app.run(debug=False, port=5050, host="127.0.0.1")
