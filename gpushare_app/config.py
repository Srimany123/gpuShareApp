"""
Application configuration
=========================

This module defines configuration classes used by the Flask application.
Sensitive settings such as the secret key, database URI and mail
credentials are pulled from environment variables.  Default values are
provided for convenience when running locally, but **never use the
defaults in production**.  Instead set the appropriate environment
variables before starting the application.

Supported environment variables:

``SECRET_KEY``
    Secret key used by Flask to sign sessions and cookies.  Defaults to
    ``"please_change_me"``.

``DATABASE_URL``
    SQLAlchemy database URI.  Defaults to a SQLite database in the
    project directory.  Example: ``postgresql+psycopg2://user:pass@host/db``.

``MAIL_SERVER``
    Hostname of the SMTP server.  Defaults to ``localhost``.

``MAIL_PORT``
    Port of the SMTP server.  Defaults to ``25``.

``MAIL_USE_TLS`` / ``MAIL_USE_SSL``
    Boolean flags controlling TLS/SSL usage.  Defaults to ``False``.

``MAIL_USERNAME`` / ``MAIL_PASSWORD``
    Authentication credentials for the SMTP server.  If not provided the
    mail extension will operate in anonymous mode.

``MAIL_DEFAULT_SENDER``
    Default sender address used when sending emails.  Defaults to
    ``None``, which means Flask-Mail will not override the message
    sender.

``BASE_URL``
    Base URL of the site, used in emails and for generating absolute
    URLs.  Defaults to ``"http://localhost:5000"``.

Feel free to extend this class or derive from it to support different
deployment environments (e.g. ``DevelopmentConfig``, ``TestingConfig``,
``ProductionConfig``).
"""

from __future__ import annotations

import os

# Attempt to load environment variables from a .env file located at
# the project root.  This allows users to configure the application
# simply by copying `.env.example` to `.env` and editing values.
try:
    # python-dotenv may not be installed; ignore failure
    from dotenv import load_dotenv  # type: ignore
    _env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
except Exception:
    pass


class Config:
    """Base configuration for the GPUShare application."""

    # Secret key for session management and CSRF protection
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "please_change_me")

    # Database configuration.  Use SQLite by default for local setups.
    SQLALCHEMY_DATABASE_URI: str = os.environ.get(
        "DATABASE_URL",
        "sqlite:///gpushare.db",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    # Mail settings.  These defaults will cause mail sending to fail
    # unless you run a local SMTP server.  Always configure these in
    # production.
    MAIL_SERVER: str | None = os.environ.get("MAIL_SERVER", "localhost")
    MAIL_PORT: int = int(os.environ.get("MAIL_PORT", 25))
    MAIL_USE_TLS: bool = os.environ.get("MAIL_USE_TLS", "False").lower() == "true"
    MAIL_USE_SSL: bool = os.environ.get("MAIL_USE_SSL", "False").lower() == "true"
    MAIL_USERNAME: str | None = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD: str | None = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER: str | None = os.environ.get("MAIL_DEFAULT_SENDER")

    # Application base URL.  Used when generating absolute URLs in
    # notifications.  It is important to set this correctly in
    # production (e.g. ``https://gpushare.example.com``).
    BASE_URL: str = os.environ.get("BASE_URL", "http://localhost:5000")

    # Nextcloud configuration for storing uploaded code or other assets.
    # When configured these credentials will be used to connect to a Nextcloud
    # server via WebDAV.  The application does not currently integrate
    # with Nextcloud directly, but these settings are provided here
    # for future use and are loaded from the environment.
    NEXTCLOUD_URL: str | None = os.environ.get("NEXTCLOUD_URL")
    NEXTCLOUD_USERNAME: str | None = os.environ.get("NEXTCLOUD_USERNAME")
    NEXTCLOUD_PASSWORD: str | None = os.environ.get("NEXTCLOUD_PASSWORD")

    # Storage provider selection.  Determines which backend is used by
    # ``gpushare_app.cloud.storage.upload_file``.  Valid values:
    # 'local' (default), 'nextcloud', 'gcs', 's3', 'r2'.
    STORAGE_PROVIDER: str = os.environ.get("STORAGE_PROVIDER", "local")
    # Generic bucket name used by GCS and S3 providers.  You may also set
    # provider-specific variables such as S3_BUCKET or GCS_BUCKET.
    STORAGE_BUCKET: str | None = os.environ.get("STORAGE_BUCKET")
