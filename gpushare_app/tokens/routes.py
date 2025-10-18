"""
API token management routes
===========================

This blueprint provides a simple web interface for authenticated users
to create, list and revoke API tokens.  Tokens are generated using
secure random strings and have an optional expiry time.  When a token
is created or revoked an email notification is sent to the user.

Blueprint: ``tokens_bp``

URL rules:

``/manage_token`` (GET)
    Show existing tokens and a form to create a new one.

``/manage_token`` (POST)
    Create a new token.  The JSON body may include ``expires_in`` as
    relativedelta parameters (e.g. ``{"days": 1}``) to set an
    expiry.

``/manage_token/<int:token_id>`` (DELETE)
    Revoke an existing token.
"""

from __future__ import annotations

from datetime import datetime
from dateutil.relativedelta import relativedelta
from typing import Any, Dict, Optional

from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from flask_mail import Message

from ..extensions import db, mail
from ..models import APIToken
from ..utils.security import generate_random_token


tokens_bp = Blueprint(
    "tokens",
    __name__,
    template_folder="../templates",
)


@tokens_bp.route("/", methods=["GET"])
@login_required
def manage_tokens():
    """Render the API token management page."""
    tokens = (
        APIToken.query
        .filter_by(user_id=current_user.id, revoked=False)
        .order_by(APIToken.expires_at.is_(None), APIToken.expires_at.desc())
        .all()
    )
    return render_template("manage_tokens.html", tokens=tokens)


@tokens_bp.route("/", methods=["POST"])
@login_required
def create_token():
    """Create a new API token.

    The request should contain JSON with an optional ``expires_in``
    dictionary mapping keyword arguments accepted by
    :class:`dateutil.relativedelta.relativedelta` (e.g. ``{"hours": 1}``).
    """
    data: Dict[str, Any] = request.get_json() or {}
    expires_in: Optional[Dict[str, int]] = data.get("expires_in")
    expires_at: Optional[datetime] = (
        datetime.utcnow() + relativedelta(**expires_in) if expires_in else None
    )
    token_str = generate_random_token(32)
    tok = APIToken(
        user_id=current_user.id,
        token=token_str,
        created_at=datetime.utcnow(),
        expires_at=expires_at,
        revoked=False,
    )
    db.session.add(tok)
    db.session.commit()
    # Send email notification
    try:
        created_str = tok.created_at.strftime("%Y-%m-%d %H:%M UTC")
        expires_str = tok.expires_at.strftime("%Y-%m-%d %H:%M UTC") if tok.expires_at else "Never"
        msg = Message(
            subject="🔑 Your New GPUShare API Token",
            recipients=[current_user.email],
        )
        msg.body = f"""
Hello {current_user.username},

Your new GPUShare API token has been generated successfully.

----------------------------------------
Token:  {tok.token}

Created: {created_str}
Expires: {expires_str}
----------------------------------------

Use this token as a Bearer token in your Authorization header when interacting with the GPUShare API.

If you did NOT request this token, please log in to your account and revoke any tokens you do not recognise immediately.

Thank you for using GPUShare!
"""
        mail.send(msg)
    except Exception:  # pragma: no cover
        pass
    return jsonify({
        "id": tok.id,
        "token": tok.token,
        "created_at": tok.created_at.isoformat(),
        "expires_at": tok.expires_at.isoformat() if tok.expires_at else None,
    }), 201


@tokens_bp.route("/<int:token_id>", methods=["DELETE"])
@login_required
def revoke_token(token_id: int):
    """Revoke an existing token."""
    tok: APIToken = APIToken.query.filter_by(id=token_id, user_id=current_user.id, revoked=False).first_or_404()
    tok.revoked = True
    db.session.commit()
    try:
        msg = Message(
            subject="🔒 Your GPUShare API token has been revoked",
            recipients=[current_user.email],
        )
        msg.body = f"""
Hello {current_user.username},

Your API token (ID: {tok.id}) was revoked on {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} UTC.

If you did this intentionally, no further action is needed.
If you did NOT revoke this token and suspect unauthorised use, please generate a new token.

Thank you for using GPUShare!
"""
        mail.send(msg)
    except Exception:  # pragma: no cover
        pass
    return jsonify({"message": "Token revoked"}), 200