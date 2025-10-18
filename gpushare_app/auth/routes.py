"""
Authentication routes
=====================

This module contains the routes responsible for user authentication
including registration, login, logout and OTP verification.  It
implements two-factor authentication similar to the original
application: after a user successfully enters their email, password and
random token an OTP is generated and emailed.  The user must then
enter the OTP to complete the login process.

Blueprint: ``auth_bp``

URL rules:

``/``
    Home page; shows a welcome message and navigation.

``/register`` (GET, POST)
    Render the registration form and handle new user registration.

``/login`` (GET, POST)
    Render the login form and handle the first stage of login.

``/verify_otp`` (GET, POST)
    Render the OTP form and verify the one‑time code.

``/logout``
    Log the current user out.

Note
----
If you wish to disable two-factor authentication simply call
``login_user`` directly after checking the email, password and
random token.
"""

from __future__ import annotations

import secrets
import string
from datetime import datetime, timedelta
from typing import Optional

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
)
from flask_login import login_user, login_required, logout_user, current_user
from flask_mail import Message

from ..extensions import db, login_manager, mail
from ..models import User


auth_bp = Blueprint(
    "auth",
    __name__,
    template_folder="../templates",
)


@login_manager.user_loader
def load_user(user_id: str) -> Optional[User]:
    """Load a user by primary key for Flask-Login."""
    return User.query.get(int(user_id))


@auth_bp.route("/")
def index() -> str:
    """Home page showing a welcome message."""
    return render_template("index.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Register a new user.

    On GET renders the registration form.  On POST validates the
    submitted data and creates the new user.  A random 8‑character
    token is generated and emailed to the user.  The user must
    provide this token along with their email and password when
    logging in.
    """
    if current_user.is_authenticated:
        flash("Already logged in.", "info")
        return redirect(url_for("auth.index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        # Basic validation
        if len(username) < 3 or len(password) < 8:
            flash("Username must be ≥3 chars; password ≥8 chars.", "danger")
            return redirect(url_for("auth.register"))

        # Uniqueness checks
        if User.query.filter_by(username=username).first():
            flash("Username already taken.", "danger")
            return redirect(url_for("auth.register"))
        if User.query.filter_by(email=email).first():
            flash("Email already registered.", "danger")
            return redirect(url_for("auth.register"))

        # Generate a random 8‑character token used during login
        token = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))

        # Create the user
        user = User(
            username=username,
            email=email,
            random_token=token,
            role="client",
            active=True,
            first_login_done=True,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        # Email the token to the user
        try:
            created_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
            msg = Message(
                subject="🎉 Welcome to GPUShare! Your Login Token",
                recipients=[email],
            )
            msg.body = f"""
Hello {username},

Thank you for registering with GPUShare!

----------------------------------------
Username: {username}
Email:    {email}
Token:    {token}
Created:  {created_str}
----------------------------------------

To log in:
  1. Visit the login page
  2. Enter your email and password
  3. When prompted, enter this 8‑character token

Keep this token secure.  If you ever lose it you can request it again
from the login page.

Happy computing!
— The GPUShare Team
"""
            mail.send(msg)
        except Exception as exc:  # pragma: no cover - mail may not be configured
            flash(f"Failed to send registration email: {exc}", "warning")

        flash("Registration successful! Check your email for your login token.", "success")
        return redirect(url_for("auth.login"))

    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Initial login stage.

    On POST verifies the email, password and random token.  If
    successful it generates a 6‑digit OTP, emails it to the user and
    stores it on the user record.  The user is then redirected to
    ``/verify_otp``.  On GET renders the login form.
    """
    if current_user.is_authenticated:
        flash("Already logged in.", "info")
        return redirect(url_for("auth.index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        token = request.form.get("token", "")
        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash("Invalid email or password.", "danger")
            return redirect(url_for("auth.login"))
        if token != user.random_token:
            flash("Invalid random token.", "danger")
            return redirect(url_for("auth.login"))
        if not user.active:
            flash("Your account is inactive.", "danger")
            return redirect(url_for("auth.login"))

        # Generate and email OTP
        otp = ''.join(secrets.choice(string.digits) for _ in range(6))
        user.current_otp = otp
        user.otp_expires = datetime.utcnow() + timedelta(minutes=5)
        db.session.commit()

        try:
            msg = Message(
                subject="Your GPUShare OTP",
                recipients=[user.email],
            )
            msg.body = f"Your one‑time login code is: {otp}\nIt expires in 5 minutes."
            mail.send(msg)
        except Exception as exc:  # pragma: no cover
            flash(f"Failed to send OTP email: {exc}", "warning")

        session["pre_otp_user"] = user.id
        flash("OTP sent to your email.  Please enter it below.", "info")
        return redirect(url_for("auth.verify_otp"))

    return render_template("login.html")


@auth_bp.route("/verify_otp", methods=["GET", "POST"])
def verify_otp():
    """Verify the one‑time password.

    This route finalises the login process.  The user must provide the
    correct 6‑digit OTP sent to their email within the 5 minute
    validity window.  If successful ``login_user`` is called and
    ``pre_otp_user`` is removed from the session.
    """
    user_id = session.get("pre_otp_user")
    if not user_id:
        return redirect(url_for("auth.login"))
    user: User = User.query.get(int(user_id))  # type: ignore[assignment]
    if request.method == "POST":
        otp = request.form.get("otp", "")
        if otp == user.current_otp and user.otp_expires and datetime.utcnow() < user.otp_expires:
            # Clear OTP to prevent reuse
            user.current_otp = None
            user.otp_expires = None
            db.session.commit()
            login_user(user)
            session.pop("pre_otp_user", None)
            return redirect(url_for("auth.index"))
        flash("Invalid or expired OTP.", "danger")

    return render_template("verify_otp.html")


@auth_bp.route("/logout")
@login_required
def logout():
    """Log out the current user."""
    logout_user()
    flash("Logged out successfully.", "success")
    return redirect(url_for("auth.index"))