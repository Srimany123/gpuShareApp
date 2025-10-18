"""
JSON API routes
===============

This blueprint implements a minimal JSON API suitable for use with the
public ``gpushare`` client library.  Authentication is via bearer
tokens created through the web interface or the API itself.  For
illustrative purposes only a handful of endpoints are implemented.

Blueprint: ``api_bp``

URL rules:

``/api/login`` (POST)
    Verify email, password and random token.  Generates and emails an
    OTP.  Returns ``{"otp_required": true}`` if successful.

``/api/verify_otp`` (POST)
    Verify the OTP and return a new API token valid for one hour.

``/api/available_gpus`` (GET)
    List GPUs owned by or approved for the authenticated user.

``/api/token_info`` (GET)
    Retrieve metadata about the current token.

``/api/refresh_token`` (POST)
    Extend the expiry of the current token by one hour.

``/api/revoke_token`` (POST)
    Revoke the current token.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify
from flask_mail import Message

from ..extensions import db, mail
from ..models import User, GPU, GPUAccessRequest, APIToken
from ..utils.security import require_api_token, generate_random_token


api_bp = Blueprint("api", __name__)


@api_bp.route("/login", methods=["POST"])
def api_login():
    """Authenticate by email/password/token and send an OTP."""
    data = request.get_json() or {}
    email = data.get("email", "").lower()
    password = data.get("password", "")
    rand = data.get("random_token", "")
    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify({"error": "Invalid credentials"}), 401
    if rand != user.random_token or not user.active:
        return jsonify({"error": "Invalid or inactive random token"}), 401
    # Generate OTP
    otp = ''.join(__import__('random').choice('0123456789') for _ in range(6))
    user.current_otp = otp
    user.otp_expires = datetime.utcnow() + timedelta(minutes=5)
    db.session.commit()
    # Send email
    try:
        msg = Message(subject="Your GPUShare OTP", recipients=[user.email])
        msg.body = f"Your one‑time login code is: {otp}\nIt expires in 5 minutes."
        mail.send(msg)
    except Exception:
        pass
    return jsonify({"otp_required": True}), 200


@api_bp.route("/verify_otp", methods=["POST"])
def api_verify_otp():
    """Verify OTP and return a new API token."""
    data = request.get_json() or {}
    email = data.get("email", "").lower()
    otp = data.get("otp", "")
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "Invalid user"}), 401
    if otp != user.current_otp or not user.otp_expires or datetime.utcnow() > user.otp_expires:
        return jsonify({"error": "Invalid or expired OTP"}), 401
    # Clear OTP
    user.current_otp = None
    user.otp_expires = None
    # Create token
    token_str = generate_random_token(32)
    api_tok = APIToken(
        user_id=user.id,
        token=token_str,
        expires_at=datetime.utcnow() + timedelta(hours=1),
        created_at=datetime.utcnow(),
        revoked=False,
    )
    db.session.add(api_tok)
    db.session.commit()
    # Email notification
    try:
        msg = Message(subject="🔐 GPUShare Login Successful", recipients=[user.email])
        msg.body = f"""
Hello {user.username},

Your one‑time password was verified on {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} UTC, and a new API token has been generated for you:

    {token_str}

Be sure to keep this token secure.  If you suspect it has been compromised, revoke or regenerate it.

Thank you for using GPUShare!
"""
        mail.send(msg)
    except Exception:
        pass
    return jsonify({"api_token": token_str}), 200


@api_bp.route("/available_gpus")
@require_api_token
def api_available_gpus():
    """Return GPUs owned by or approved for the authenticated user."""
    user = request.api_user  # type: ignore[attr-defined]
    # Owner GPUs
    owner_gpus = GPU.query.filter_by(host_user_id=user.id).all()
    # Approved access GPUs
    approved_reqs = GPUAccessRequest.query.filter_by(client_id=user.id, status="approved").all()
    approved_gpu_ids = {req.gpu_id for req in approved_reqs}
    approved_gpus = GPU.query.filter(GPU.id.in_(approved_gpu_ids)).all()
    combined = {gpu.id: gpu for gpu in owner_gpus + approved_gpus}.values()
    result = []
    for gpu in combined:
        result.append({
            "id": gpu.id,
            "name": gpu.name,
            "owned": gpu.host_user_id == user.id,
            "status": "active" if (gpu.connected and not gpu.idle) else "unavailable",
        })
    return jsonify(result), 200


@api_bp.route("/token_info")
@require_api_token
def api_token_info():
    """Return information about the current API token."""
    token_obj: APIToken = request.api_token_obj  # type: ignore[attr-defined]
    return jsonify({
        "created_at": token_obj.created_at.isoformat(),
        "expires_at": token_obj.expires_at.isoformat() if token_obj.expires_at else None,
        "revoked": token_obj.revoked,
    }), 200


@api_bp.route("/refresh_token", methods=["POST"])
@require_api_token
def api_refresh_token():
    """Extend the expiry of the current token by one hour."""
    token_obj: APIToken = request.api_token_obj  # type: ignore[attr-defined]
    token_obj.expires_at = datetime.utcnow() + timedelta(hours=1)
    db.session.commit()
    return jsonify({
        "token": token_obj.token,
        "created_at": token_obj.created_at.isoformat(),
        "expires_at": token_obj.expires_at.isoformat() if token_obj.expires_at else None,
    }), 200


@api_bp.route("/revoke_token", methods=["POST"])
@require_api_token
def api_revoke_token():
    """Revoke the current API token."""
    token_obj: APIToken = request.api_token_obj  # type: ignore[attr-defined]
    user = token_obj.user  # type: ignore[attr-defined]
    token_str = token_obj.token
    token_obj.revoked = True
    db.session.commit()
    # Notification email
    try:
        msg = Message(subject="🔒 Your GPUShare API token has been revoked", recipients=[user.email])
        msg.body = f"""
Hello {user.username},

Your GPUShare API token was revoked on {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} UTC.

Token: {token_str}

If you did this intentionally, no further action is needed.
If you did NOT revoke this token and suspect unauthorised use, please generate a new token immediately.

Thank you,
The GPUShare Team
"""
        mail.send(msg)
    except Exception:
        pass
    return jsonify({"message": "Token revoked"}), 200


# ---------------------------------------------------------------------------
# GPU Host API
# ---------------------------------------------------------------------------
@api_bp.route("/register_gpu", methods=["POST"])
@require_api_token
def api_register_gpu() -> tuple[dict, int]:
    """Register a new GPU owned by the authenticated user.

    Expects a JSON payload with a ``gpu_info`` object.  At minimum,
    ``gpu_info`` should contain a ``name``.  Other fields like
    ``uuid``, ``memory_total``, ``memory_used``, ``memory_free``,
    ``driver`` and ``host_address`` are optional and will be stored in
    the GPU's ``details`` field for later reference.
    Returns the new GPU's ID.
    """
    user = request.api_user  # type: ignore[attr-defined]
    data = request.get_json() or {}
    gpu_info = data.get("gpu_info") or {}
    # Validate name
    name = gpu_info.get("name") or gpu_info.get("gpu_name") or "Unnamed GPU"
    if not name:
        return jsonify({"error": "GPU name missing"}), 400
    details_lines: list[str] = []
    for key in ["memory_total", "memory_used", "memory_free", "driver", "uuid"]:
        if key in gpu_info and gpu_info[key] is not None:
            details_lines.append(f"{key.replace('_', ' ').title()}: {gpu_info[key]}")
    details_lines: list[str] = []
    for key in ["memory_total", "memory_used", "memory_free", "driver", "uuid"]:
        if key in gpu_info and gpu_info[key] is not None:
            details_lines.append(f"{key.replace('_', ' ').title()}: {gpu_info[key]}")
    details = "\n".join(details_lines) if details_lines else None
    
    host_addr = gpu_info.get("host_address")
    from ..extensions import db
    from ..models import GPU
    # Handle duplicate UUIDs: if the same UUID is already registered by
    # this user then this is a reconnection.  Otherwise, prevent reuse
    # across different owners.
    existing = None
    gpu_uuid = gpu_info.get("uuid")
    if gpu_uuid:
        existing = GPU.query.filter_by(uuid=gpu_uuid).first()
        if existing:
            if existing.host_user_id != user.id:
                # Another user already owns this GPU
                return jsonify({"error": "A GPU with this UUID is already registered by another user."}), 409
            # Reconnection: update host info and mark as connected
            existing.connected = True
            existing.host_address = host_addr
            existing.details = details
            existing.disconnect_time = None
            existing.last_update = datetime.utcnow()
            db.session.commit()
            return jsonify({
                "message": "GPU reconnected successfully",
                "gpu_id": existing.id
            }), 200
    # Otherwise, register new GPU
    new_gpu = GPU(
        uuid=gpu_uuid,
        name=name,
        details=details,
        host_user_id=user.id,
        host_address=host_addr,
        start_time=datetime.utcnow(),
        usage_time=0.0,
        connected=True,
        idle=False,
        last_update=datetime.utcnow(),
    )
    db.session.add(new_gpu)
    db.session.commit()
    return jsonify({
        "message": "GPU registered successfully",
        "gpu_id": new_gpu.id
    }), 200


@api_bp.route("/update_gpu_stats", methods=["POST"])
@require_api_token
def api_update_gpu_stats() -> tuple[dict, int]:
    """Update the usage statistics for a GPU.

    Expects JSON ``{gpu_id: int, usage_time: float}``.  Only the owner
    of the GPU (or an admin/superadmin) can update its stats.  The
    ``usage_time`` is stored as seconds.  Updates the ``last_update``
    timestamp.
    """
    data = request.get_json() or {}
    gpu_id = data.get("gpu_id")
    usage_time = data.get("usage_time")
    if gpu_id is None or usage_time is None:
        return jsonify({"error": "gpu_id and usage_time are required"}), 400
    from ..extensions import db
    from ..models import GPU, User
    gpu: GPU | None = GPU.query.filter_by(id=gpu_id).first()
    if not gpu or gpu.host_user_id != user.id:
        return jsonify({"error": "GPU not found or unauthorized"}), 404
    try:
        gpu.usage_time = float(usage_time)
    except (ValueError, TypeError):
        return jsonify({"error": "usage_time must be a number"}), 400
    gpu.last_update = datetime.utcnow()
    db.session.commit()
    return jsonify({"message": "GPU stats updated"}), 200


@api_bp.route("/set_gpu_idle/<int:gpu_id>", methods=["POST"])
@require_api_token
def api_set_gpu_idle(gpu_id: int) -> tuple[dict, int]:
    """Set or clear the idle flag on a GPU.

    Accepts JSON ``{"idle": true/false}``.  Only the owner or an
    admin/superadmin can change the idle state.  Updates the GPU's
    ``idle`` attribute and ``last_update`` timestamp.
    """
    data = request.get_json() or {}
    idle = data.get("idle")
    if idle is None or not isinstance(idle, bool):
        return jsonify({"error": "idle must be a boolean"}), 400
    from ..extensions import db
    from ..models import GPU, User
    gpu: GPU | None = GPU.query.filter_by(id=gpu_id).first()
    if not gpu:
        return jsonify({"error": "GPU not found"}), 404
    user: User = request.api_user  # type: ignore[attr-defined]
    # Only the owner can change idle status
    if gpu.host_user_id != user.id:
        return jsonify({"error": "Forbidden"}), 403
    gpu.idle = idle
    db.session.commit()
    status = "idle" if gpu.idle else "busy"
    return jsonify({
        "message": f"GPU {gpu.id} marked as {status}.",
        "idle": gpu.idle
    })