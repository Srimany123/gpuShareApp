"""
Administrative routes
=====================

This blueprint provides views and actions for site administrators.
Administrators can see all users and GPUs, promote users to
moderators or admins, demote moderators back to clients and
process pending approval requests.  Certain actions (demoting or
banning an administrator) require approval by a superadmin.  There
must always be at least one administrator (admin or superadmin) in
the system.  Superadmins cannot be removed or demoted by any other
administrator.

URL rules:

``/admin/dashboard``
    View the admin dashboard and, if you are a superadmin, see
    pending approval requests.

``/admin/make_moderator/<int:user_id>``
    Promote a client to moderator.  Admins and superadmins may
    perform this action directly.

``/admin/make_admin/<int:user_id>``
    Promote a client or moderator to administrator.  Admins and
    superadmins may perform this action directly.

``/admin/demote/<int:user_id>``
    Demote a moderator to client, or demote an admin to moderator.
    Demoting an admin requires superadmin approval.

``/admin/ban/<int:user_id>``
    Deactivate a user's account.  Banning an admin requires
    superadmin approval.

``/admin/approve/<int:request_id>``
    Approve a pending approval request (superadmin only).

``/admin/deny/<int:request_id>``
    Deny a pending approval request (superadmin only).

"""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user

from ..extensions import db
from ..models import User, GPU, ApprovalRequest


admin_bp = Blueprint(
    "admin",
    __name__,
    template_folder="../templates",
)


def require_admin() -> bool:
    """Helper to enforce that the current user is an admin or superadmin.

    If the user is not an administrator, a flash message is shown and
    they are redirected to the index page.  Returns ``True`` if the
    user is an admin and ``False`` otherwise.
    """
    if current_user.role not in {"admin", "superadmin"}:
        flash("Access denied: Admins only.", "danger")
        return False
    return True


@admin_bp.route("/dashboard")
@login_required
def dashboard():
    """Display all users and GPUs to administrators.

    Superadmins also see pending approval requests that require
    their attention.
    """
    if not require_admin():
        return redirect(url_for("auth.index"))
    users = User.query.all()
    gpus = GPU.query.all()
    approval_requests: list[ApprovalRequest] = []
    if current_user.role == "superadmin":
        approval_requests = ApprovalRequest.query.filter_by(status="pending").all()
    return render_template(
        "admin_dashboard.html",
        users=users,
        gpus=gpus,
        approval_requests=approval_requests,
    )


def count_active_admins() -> int:
    """Return the number of active users with role admin or superadmin."""
    return (
        User.query.filter(User.active.is_(True), User.role.in_(["admin", "superadmin"]))
        .count()
    )


@admin_bp.route("/make_moderator/<int:user_id>")
@login_required
def make_moderator(user_id: int):
    """Promote a client to moderator.

    Only users with role admin or superadmin may perform this action.
    """
    if not require_admin():
        return redirect(url_for("auth.index"))
    user = User.query.get_or_404(user_id)
    if user.role == "client":
        user.role = "moderator"
        db.session.commit()
        flash(f"User {user.username} promoted to moderator.", "success")
    else:
        flash(f"User {user.username} cannot be promoted to moderator.", "danger")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/make_admin/<int:user_id>")
@login_required
def make_admin(user_id: int):
    """Promote a client or moderator to administrator.

    Only users with role admin or superadmin may perform this action.
    """
    if not require_admin():
        return redirect(url_for("auth.index"))
    user = User.query.get_or_404(user_id)
    if user.role in {"client", "moderator"}:
        user.role = "admin"
        db.session.commit()
        flash(f"User {user.username} promoted to admin.", "success")
    else:
        flash("User cannot be promoted to admin.", "danger")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/demote/<int:user_id>")
@login_required
def demote_user(user_id: int):
    """Demote a moderator or admin.

    * Moderators are demoted to clients directly.
    * Admins are demoted to moderators.  If the current user is not
      a superadmin, an approval request is created instead of
      performing the demotion immediately.  If the current user is a
      superadmin, the demotion proceeds as long as it does not leave
      the system without any active administrator.
    """
    if not require_admin():
        return redirect(url_for("auth.index"))
    if current_user.id == user_id:
        flash("You cannot demote yourself.", "danger")
        return redirect(url_for("admin.dashboard"))
    user = User.query.get_or_404(user_id)
    if user.role == "superadmin":
        flash("Superadmins cannot be demoted.", "danger")
        return redirect(url_for("admin.dashboard"))
    # Demote moderator to client immediately
    if user.role == "moderator":
        user.role = "client"
        db.session.commit()
        flash(f"User {user.username} demoted to client.", "success")
        return redirect(url_for("admin.dashboard"))
    # Demote admin to moderator
    if user.role == "admin":
        # If current user is superadmin, demote directly but ensure at least one admin remains
        if current_user.role == "superadmin":
            # Count number of admin or superadmin after demotion
            admin_count = count_active_admins()
            # If there is only one admin (target) and no other, abort
            if admin_count <= 1:
                flash(
                    "Cannot demote the last remaining admin. There must be at least one admin or superadmin.",
                    "danger",
                )
                return redirect(url_for("admin.dashboard"))
            user.role = "moderator"
            db.session.commit()
            flash(f"User {user.username} demoted to moderator.", "success")
        else:
            # Not superadmin, create approval request
            req = ApprovalRequest(
                action="demote_admin",
                requester_id=current_user.id,
                target_user_id=user.id,
                new_role="moderator",
            )
            db.session.add(req)
            db.session.commit()
            flash(
                f"Demotion request for {user.username} created and awaits superadmin approval.",
                "info",
            )
        return redirect(url_for("admin.dashboard"))
    flash("User cannot be demoted.", "danger")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/ban/<int:user_id>")
@login_required
def ban_user(user_id: int):
    """Deactivate a user's account.

    Banning an admin requires superadmin approval.  Superadmins cannot
    be banned.  Administrators may ban clients and moderators
    directly.  The system ensures that at least one admin (or
    superadmin) remains active.
    """
    if not require_admin():
        return redirect(url_for("auth.index"))
    if current_user.id == user_id:
        flash("You cannot ban yourself.", "danger")
        return redirect(url_for("admin.dashboard"))
    user = User.query.get_or_404(user_id)
    if not user.active:
        flash("User is already banned.", "info")
        return redirect(url_for("admin.dashboard"))
    if user.role == "superadmin":
        flash("Superadmins cannot be banned.", "danger")
        return redirect(url_for("admin.dashboard"))
    if user.role == "admin":
        # If superadmin performing ban, enforce at least one admin remains
        if current_user.role == "superadmin":
            if count_active_admins() <= 1:
                flash(
                    "Cannot ban the last remaining admin. There must be at least one admin or superadmin.",
                    "danger",
                )
                return redirect(url_for("admin.dashboard"))
            user.active = False
            db.session.commit()
            flash(f"Admin {user.username} banned.", "success")
        else:
            # Not superadmin, create approval request
            req = ApprovalRequest(
                action="ban_admin",
                requester_id=current_user.id,
                target_user_id=user.id,
            )
            db.session.add(req)
            db.session.commit()
            flash(
                f"Ban request for {user.username} created and awaits superadmin approval.",
                "info",
            )
        return redirect(url_for("admin.dashboard"))
    # Non-admin users can be banned directly
    user.active = False
    db.session.commit()
    flash(f"User {user.username} banned.", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/approve/<int:request_id>")
@login_required
def approve_request(request_id: int):
    """Approve an administrative approval request (superadmin only)."""
    if current_user.role != "superadmin":
        flash("Access denied: Superadmins only.", "danger")
        return redirect(url_for("admin.dashboard"))
    req = ApprovalRequest.query.get_or_404(request_id)
    if req.status != "pending":
        flash("Request is no longer pending.", "info")
        return redirect(url_for("admin.dashboard"))
    target = User.query.get(req.target_user_id)
    if not target:
        flash("Target user no longer exists.", "danger")
        req.status = "denied"
        req.resolved_at = datetime.utcnow()
        db.session.commit()
        return redirect(url_for("admin.dashboard"))
    if req.action == "demote_admin":
        # ensure not demoting last admin
        if count_active_admins() <= 1:
            flash(
                "Cannot demote the last remaining admin. There must be at least one admin or superadmin.",
                "danger",
            )
            req.status = "denied"
            req.resolved_at = datetime.utcnow()
            db.session.commit()
            return redirect(url_for("admin.dashboard"))
        target.role = req.new_role or "moderator"
        db.session.commit()
        flash(f"Admin {target.username} demoted to {target.role}.", "success")
    elif req.action == "ban_admin":
        # ensure not banning last admin
        if count_active_admins() <= 1:
            flash(
                "Cannot ban the last remaining admin. There must be at least one admin or superadmin.",
                "danger",
            )
            req.status = "denied"
            req.resolved_at = datetime.utcnow()
            db.session.commit()
            return redirect(url_for("admin.dashboard"))
        target.active = False
        db.session.commit()
        flash(f"Admin {target.username} banned.", "success")
    # mark request as approved
    req.status = "approved"
    req.resolved_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/deny/<int:request_id>")
@login_required
def deny_request(request_id: int):
    """Deny an administrative approval request (superadmin only)."""
    if current_user.role != "superadmin":
        flash("Access denied: Superadmins only.", "danger")
        return redirect(url_for("admin.dashboard"))
    req = ApprovalRequest.query.get_or_404(request_id)
    if req.status != "pending":
        flash("Request is no longer pending.", "info")
        return redirect(url_for("admin.dashboard"))
    req.status = "denied"
    req.resolved_at = datetime.utcnow()
    db.session.commit()
    flash("Request denied.", "success")
    return redirect(url_for("admin.dashboard"))