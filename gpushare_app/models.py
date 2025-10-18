"""
Database models
===============

This module defines the SQLAlchemy models for the GPUShare application.
Models are separated from the application factory so they can be
imported by tasks, blueprints and command line scripts without causing
circular imports.  All relationships are defined explicitly and some
helper methods (e.g. password hashing) are provided on the user
model.

"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from .extensions import db


class APIToken(db.Model):
    """API authentication token issued to a user.

    Tokens are stored in the database and can be revoked or allowed to
    expire.  Each token is associated with a single user and has a
    creation timestamp and an optional expiry timestamp.
    """

    id: int = db.Column(db.Integer, primary_key=True)
    user_id: int = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    token: str = db.Column(db.String(100), unique=True, nullable=False)
    created_at: datetime = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at: Optional[datetime] = db.Column(db.DateTime, nullable=True)
    revoked: bool = db.Column(db.Boolean, default=False, nullable=False)

    # Relationship back to user
    user = db.relationship("User", backref=db.backref("api_tokens", lazy=True))

    def is_valid(self) -> bool:
        """Return ``True`` if this token is not revoked and has not expired."""
        if self.revoked:
            return False
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False
        return True


class CodeReview(db.Model):
    """Record of a submitted code review request.

    A client may submit code for review before running it on a host GPU.
    The GPU owner or an administrator can then approve or deny the
    request.  Optionally, the client may upload a file instead of
    pasting code.  When a review is approved the client can download
    and execute the approved code.
    """

    id: int = db.Column(db.Integer, primary_key=True)
    gpu_id: int = db.Column(db.Integer, db.ForeignKey("gpu.id"), nullable=False)
    client_id: int = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    code: Optional[str] = db.Column(db.Text, nullable=True)
    file_data: Optional[bytes] = db.Column(db.LargeBinary, nullable=True)
    filename: Optional[str] = db.Column(db.String(200), nullable=True)
    status: str = db.Column(db.String(20), default="pending")  # pending, approved, denied
    submitted_time: datetime = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_by: Optional[str] = db.Column(db.String(80), nullable=True)
    reviewed_time: Optional[datetime] = db.Column(db.DateTime, nullable=True)

    gpu = db.relationship("GPU", backref=db.backref("code_reviews", lazy=True))
    client = db.relationship("User")


class User(db.Model, UserMixin):
    """User account.

    Inherits from :class:`flask_login.UserMixin` to integrate with
    Flask-Login.  Passwords are stored as hashes; see
    :meth:`set_password` and :meth:`check_password`.
    """

    id: int = db.Column(db.Integer, primary_key=True)
    username: str = db.Column(db.String(80), unique=True, nullable=False)
    email: str = db.Column(db.String(120), unique=True, nullable=False)
    password_hash: str = db.Column(db.String(128), nullable=False)
    random_token: str = db.Column(db.String(8), nullable=False)
    current_otp: Optional[str] = db.Column(db.String(6), nullable=True)
    otp_expires: Optional[datetime] = db.Column(db.DateTime, nullable=True)
    #: Role of the user.  Valid values are ``client``, ``moderator``,
    #: ``admin`` or ``superadmin``.  Superadmins have the same
    #: permissions as admins but cannot be removed or demoted by any
    #: other administrator.  There must always be at least one
    #: administrator (admin or superadmin) in the system.
    role: str = db.Column(db.String(20), nullable=False, default="client")
    active: bool = db.Column(db.Boolean, default=True)
    first_login_done: bool = db.Column(db.Boolean, default=False)
    reset_token: Optional[str] = db.Column(db.String(128), nullable=True, unique=True)
    reset_expires: Optional[datetime] = db.Column(db.DateTime, nullable=True)

    # Relationships
    gpus = db.relationship("GPU", backref="host_user", lazy=True)
    requests = db.relationship("GPUAccessRequest", backref="client", lazy=True)

    def set_password(self, password: str) -> None:
        """Hash and store the password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Return ``True`` if the supplied password matches the stored hash."""
        return check_password_hash(self.password_hash, password)


class GPU(db.Model):
    """A GPU hosted by a user.

    The GPU model stores metadata about the GPU, who hosts it and
    runtime state such as whether it is connected or idle.  The host
    communicates with the server via the API to update usage stats.
    """

    id: int = db.Column(db.Integer, primary_key=True)
    uuid: Optional[str] = db.Column(db.String(100), nullable=True)
    name: str = db.Column(db.String(100), nullable=False)
    details: Optional[str] = db.Column(db.String(500))
    host_address: Optional[str] = db.Column(db.String(50))
    host_user_id: int = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    start_time: Optional[datetime] = db.Column(db.DateTime, nullable=True)
    disconnect_time: Optional[datetime] = db.Column(db.DateTime, nullable=True)
    usage_time: float = db.Column(db.Float, default=0)
    connected: bool = db.Column(db.Boolean, default=True)
    idle: bool = db.Column(db.Boolean, default=False)
    last_update: Optional[datetime] = db.Column(db.DateTime, nullable=True)

    # Access requests relationship defined in GPUAccessRequest


class GPUAccessRequest(db.Model):
    """Request from a client to access a GPU.

    A request has a status field which may be one of ``requested``,
    ``approved`` or ``denied``.  When approved it can optionally have
    an expiry timestamp.  A request can also include code submitted for
    review; the review process is stored in :class:`CodeReview`.
    """

    id: int = db.Column(db.Integer, primary_key=True)
    gpu_id: int = db.Column(db.Integer, db.ForeignKey("gpu.id"), nullable=False)
    client_id: int = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    status: str = db.Column(db.String(20), default="requested")
    request_time: datetime = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_time: Optional[datetime] = db.Column(db.DateTime, nullable=True)
    reviewed_by: Optional[str] = db.Column(db.String(80), nullable=True)
    access_expires: Optional[datetime] = db.Column(db.DateTime, nullable=True)
    code: Optional[str] = db.Column(db.Text, nullable=True)
    verified_by: Optional[str] = db.Column(db.String(80), nullable=True)
    verified_time: Optional[datetime] = db.Column(db.DateTime, nullable=True)

    # Relationships
    gpu = db.relationship("GPU", backref=db.backref("access_requests", lazy=True))


class ApprovalRequest(db.Model):
    """Record of an administrative action requiring superadmin approval.

    When an administrator attempts to promote, demote or ban another
    administrator, an ApprovalRequest entry is created instead of
    directly applying the action.  Superadmins can view all pending
    requests and either approve or deny them.  Requests contain
    metadata about the requested action and the users involved.
    """

    id: int = db.Column(db.Integer, primary_key=True)
    action: str = db.Column(db.String(50), nullable=False)  # e.g., 'promote_to_admin', 'demote_admin', 'ban_admin'
    requester_id: int = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    target_user_id: int = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    new_role: db.Column = db.Column(db.String(20), nullable=True)  # optional new role for promotion/demotion
    status: str = db.Column(db.String(20), default="pending")  # pending, approved, denied
    created_at: datetime = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at: db.Column = db.Column(db.DateTime, nullable=True)

    requester = db.relationship("User", foreign_keys=[requester_id])
    target_user = db.relationship("User", foreign_keys=[target_user_id])
