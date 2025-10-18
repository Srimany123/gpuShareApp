"""
Flask extension instances
=========================

This module instantiates the Flask extensions used by the application.
By keeping these objects in a separate module we avoid circular import
issues when models or routes need to import the database or mail
objects.  Each extension is initialised in the application factory
defined in ``gpushare_app.__init__``.

"""

from __future__ import annotations

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail

# SQLAlchemy database object
db = SQLAlchemy()

# Flask-Login manager
login_manager = LoginManager()
login_manager.login_view = "auth.login"

# Flask-Mail object
mail = Mail()
