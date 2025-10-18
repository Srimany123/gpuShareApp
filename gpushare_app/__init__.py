"""
gpushare_app
================

This package provides a fully fledged Flask application for hosting and
sharing GPUs.  It is a refactored and modularised version of the original
monolithic ``run.py``.  The goal of this refactor is to improve security,
maintainability and ease of contribution.  Sensitive settings are now
loaded from environment variables, routes are organised into blueprints
based on their area of responsibility (authentication, API, admin,
token management and GPU management) and common extensions are
initialised in a single place.

To create an instance of the application use the :func:`create_app`
factory.  When run in a production environment you should ensure
environment variables for the secret key, database URI and mail
credentials are set appropriately.  See ``config.py`` for details.

Example::

    from gpushare_app import create_app
    app = create_app()
    app.run()

"""

from __future__ import annotations

import os
from flask import Flask

from .config import Config
from .extensions import db, mail, login_manager

def create_app(config_class: type[Config] | None = None) -> Flask:
    """Application factory used by the flask CLI and the tests.

    Parameters
    ----------
    config_class: type[Config], optional
        A configuration class to use.  If not provided the default
        ``Config`` class will be used.  This allows tests to supply
        their own configuration without modifying environment variables.

    Returns
    -------
    Flask
        A fully configured Flask application.
    """
    # Instantiate the app
    app = Flask(__name__, instance_relative_config=False)

    # Load configuration from the provided class or the default
    config_obj = config_class() if config_class else Config()
    app.config.from_object(config_obj)

    # Initialise Flask extensions
    db.init_app(app)
    mail.init_app(app)
    login_manager.init_app(app)

    # Register blueprints.  Importing here avoids circular imports.
    from .auth.routes import auth_bp
    from .api.routes import api_bp
    from .admin.routes import admin_bp
    from .gpu.routes import gpu_bp
    from .tokens.routes import tokens_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(gpu_bp)
    app.register_blueprint(tokens_bp, url_prefix="/manage_token")

    # Create database tables if they don't exist
    with app.app_context():
        db.create_all()

    return app