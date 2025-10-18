"""
Command line interface for GPUShare
=================================

This module provides a simple command line interface for common
administrative tasks such as starting the development server,
initialising the database and creating the initial admin user.  It
uses Python's built-in :mod:`argparse` to parse command line
arguments.
"""

from __future__ import annotations

import argparse
import getpass
import os
from datetime import datetime

from flask import current_app
from werkzeug.security import generate_password_hash

from gpushare_app import create_app
from gpushare_app.extensions import db
from gpushare_app.models import User


def init_db() -> None:
    """Create all database tables."""
    app = create_app()
    with app.app_context():
        db.create_all()
        print("Database initialised.")


def create_admin() -> None:
    """Interactively create an administrator account with OTP verification.

    The administrator account is only activated after the OTP
    generated below is confirmed.  This mirrors the normal user
    registration flow to ensure that the email address is valid and
    prevents accidental creation of unused admin accounts.
    """
    app = create_app()
    with app.app_context():
        # Admin accounts may be created even if one already exists.  Only
        # enforce that at least one admin exists when running the server.
        username = input("Admin username: ").strip()
        email = input("Admin email: ").strip().lower()
        password = getpass.getpass("Admin password: ")
        token = input("Random login token (8 chars): ").strip()
        if len(token) != 8:
            raise SystemExit("Token must be 8 characters long.")
        # Create admin but do not fully activate
        admin = User(
            username=username,
            email=email,
            random_token=token,
            role="admin",
            active=True,
            first_login_done=True,
        )
        admin.password_hash = generate_password_hash(password)
        # Generate an OTP for verification
        otp = ''.join(__import__('random').choice('0123456789') for _ in range(6))
        admin.current_otp = otp
        from datetime import datetime, timedelta
        admin.otp_expires = datetime.utcnow() + timedelta(minutes=10)
        db.session.add(admin)
        db.session.commit()
        # Attempt to send OTP via email using Flask-Mail
        try:
            from flask_mail import Message
            from gpushare_app.extensions import mail
            msg = Message(
                subject="Your GPUShare admin verification code",
                recipients=[email],
            )
            msg.body = f"Hello {username},\n\nYour one-time password for admin account creation is: {otp}\nIt will expire in 10 minutes."
            mail.send(msg)
            print("A verification code has been sent to your email. Please check your inbox (and spam folder).")
        except Exception:
            # If mail fails, display the OTP in the console so the user can still verify
            print(f"Mail sending failed. Use this OTP to verify the admin account: {otp}")
        # Prompt for OTP
        entered = input("Enter the OTP sent to your email: ").strip()
        if entered == otp:
            # Clear OTP and confirm admin creation
            admin.current_otp = None
            admin.otp_expires = None
            db.session.commit()
            print(f"Admin user '{username}' created and verified.")
        else:
            # Remove the partially created admin
            db.session.delete(admin)
            db.session.commit()
            raise SystemExit("OTP verification failed. Admin account not created.")


def create_superadmin() -> None:
    """Interactively create a superadmin account with OTP verification.

    Superadmins have all the privileges of admins but cannot be
    removed or demoted by other administrators.  Only one
    superadmin is needed but you may create multiple if desired.
    This function follows the same flow as ``create_admin``.
    """
    app = create_app()
    with app.app_context():
        username = input("Superadmin username: ").strip()
        email = input("Superadmin email: ").strip().lower()
        password = getpass.getpass("Superadmin password: ")
        token = input("Random login token (8 chars): ").strip()
        if len(token) != 8:
            raise SystemExit("Token must be 8 characters long.")
        # Create superadmin but do not fully activate
        user = User(
            username=username,
            email=email,
            random_token=token,
            role="superadmin",
            active=True,
            first_login_done=True,
        )
        user.password_hash = generate_password_hash(password)
        # Generate OTP for verification
        otp = ''.join(__import__('random').choice('0123456789') for _ in range(6))
        user.current_otp = otp
        from datetime import timedelta
        user.otp_expires = datetime.utcnow() + timedelta(minutes=10)
        db.session.add(user)
        db.session.commit()
        # send email or show
        try:
            from flask_mail import Message
            from gpushare_app.extensions import mail
            msg = Message(
                subject="Your GPUShare superadmin verification code",
                recipients=[email],
            )
            msg.body = (
                f"Hello {username},\n\n"
                f"Your one-time password for superadmin account creation is: {otp}\n"
                f"It will expire in 10 minutes."
            )
            mail.send(msg)
            print(
                "A verification code has been sent to your email. Please check your inbox (and spam folder)."
            )
        except Exception:
            print(f"Mail sending failed. Use this OTP to verify the superadmin account: {otp}")
        entered = input("Enter the OTP sent to your email: ").strip()
        if entered == otp:
            user.current_otp = None
            user.otp_expires = None
            db.session.commit()
            print(f"Superadmin user '{username}' created and verified.")
        else:
            db.session.delete(user)
            db.session.commit()
            raise SystemExit("OTP verification failed. Superadmin account not created.")


def run_server(host: str, port: int, debug: bool) -> None:
    """Run the Flask development server.

    Before starting the server ensure that at least one administrator
    (admin or superadmin) exists in the database.  If no admin
    accounts are present the server will refuse to start to prevent
    locking yourself out of the system.
    """
    app = create_app()
    with app.app_context():
        if not User.query.filter(User.role.in_(["admin", "superadmin"])).first():
            raise SystemExit(
                "No admin accounts exist. Please run `python argument.py create-admin` or create a superadmin before starting the server."
            )
    app.run(host=host, port=port, debug=debug)


def main() -> None:
    parser = argparse.ArgumentParser(description="GPUShare administration CLI")
    subparsers = parser.add_subparsers(dest="command")
    # init-db command
    subparsers.add_parser("init-db", help="Initialise the database")
    # create-admin command
    subparsers.add_parser("create-admin", help="Create the initial admin user interactively")
    # create-superadmin command
    subparsers.add_parser("create-superadmin", help="Create a superadmin user interactively")
    # run-server command
    server_parser = subparsers.add_parser("run-server", help="Run the Flask development server")
    server_parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    server_parser.add_argument("--port", type=int, default=5000, help="Port to listen on")
    server_parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()
    if args.command == "init-db":
        init_db()
    elif args.command == "create-admin":
        create_admin()
    elif args.command == "create-superadmin":
        create_superadmin()
    elif args.command == "run-server":
        run_server(args.host, args.port, args.debug)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()