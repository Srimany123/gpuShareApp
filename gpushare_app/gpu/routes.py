"""
GPU management routes
=====================

This blueprint contains routes related to hosting GPUs and managing
access requests.  Users can view their hosted GPUs, browse available
GPUs owned by others, submit access requests, and review the status of
their requests.  Owners, moderators and administrators can approve or
deny requests.

Blueprint: ``gpu_bp``

URL rules:

``/my_gpu``
    List GPUs hosted by the current user.

``/available_gpus``
    Show GPUs available to the current user.  Allows a search query via
    the ``q`` query parameter.

``/request_gpu/<int:gpu_id>`` (GET, POST)
    Display a form to submit an access request.  Accepts optional code
    or a file upload.  Uses code scanning utilities to reject obvious
    malware.

``/my_requests``
    Display the current user's access requests.

``/gpu/<int:gpu_id>/requests``
    Show access requests for a particular GPU.  Only owners,
    moderators and administrators can view this page.

``/approve_request/<int:req_id>``
    Approve a pending access request.  Only owners, moderators and
    administrators can perform this action.

``/deny_request/<int:req_id>``
    Deny a pending access request.

Note
----
For brevity this blueprint does not implement all features present in
the original monolithic application, such as disconnection and
reconnection of GPUs or code review workflows.  Those features can be
added as separate routes or blueprints using the same patterns shown
here.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
)
from flask_login import login_required, current_user
from flask_mail import Message

from ..extensions import db, mail
from ..models import GPU, GPUAccessRequest, User
from ..utils.security import safe_code_check, automated_code_scan


gpu_bp = Blueprint(
    "gpu",
    __name__,
    template_folder="../templates",
)


@gpu_bp.route("/my_gpu")
@login_required
def my_gpu() -> str:
    """List GPUs hosted by the current user."""
    my_gpus: List[GPU] = GPU.query.filter_by(host_user_id=current_user.id).all()
    return render_template("my_gpu.html", gpus=my_gpus)


@gpu_bp.route("/add_gpu", methods=["GET", "POST"])
@login_required
def add_gpu() -> str:
    """Disable GPU registration via the web interface.

    To prevent users from forging GPU details through the website,
    this route simply informs the user that GPU registration must be
    performed by running the official host agent script.  Any POST
    requests are ignored and redirected back to the My GPU page.
    """
    flash(
        "GPU registration via the web interface is disabled. "
        "Please run the provided GPUShare host agent script on the machine hosting your GPU.",
        "warning",
    )
    return redirect(url_for("gpu.my_gpu"))


@gpu_bp.route("/available_gpus")
@login_required
def available_gpus() -> str:
    """Display GPUs available for access by the current user."""
    query = request.args.get("q", "")
    gpus_query = GPU.query.filter(
        GPU.connected.is_(True),
        GPU.idle.is_(False),
        GPU.host_user_id != current_user.id,
    )
    if query:
        gpus_query = gpus_query.filter(GPU.name.ilike(f"%{query}%"))
    gpus = gpus_query.all()
    return render_template("available_gpus.html", gpus=gpus, query=query)


@gpu_bp.route("/request_gpu/<int:gpu_id>", methods=["GET", "POST"])
@login_required
def request_gpu(gpu_id: int):
    """Submit an access request for a GPU."""
    gpu: GPU = GPU.query.get_or_404(gpu_id)
    if gpu.host_user_id == current_user.id:
        flash("You already host this GPU.", "info")
        return redirect(url_for("gpu.available_gpus"))

    if request.method == "POST":
        # Extract submitted code from textarea
        code = request.form.get("code", "")
        # If a file is uploaded, use its contents instead
        uploaded_file = request.files.get("code_file")
        if uploaded_file and uploaded_file.filename:
            try:
                code = uploaded_file.read().decode("utf-8")
            except Exception:
                flash("Uploaded file could not be decoded as UTF‑8.", "danger")
                return redirect(url_for("gpu.request_gpu", gpu_id=gpu_id))
        # Run code safety checks if any code was provided
        if code:
            safe, reason = safe_code_check(code)
            if not safe:
                flash(f"Code rejected: {reason}", "danger")
                # Record a denied request to avoid repeated submissions
                req_obj = GPUAccessRequest(
                    gpu_id=gpu_id,
                    client_id=current_user.id,
                    code=code,
                    status="denied",
                )
                db.session.add(req_obj)
                db.session.commit()
                return redirect(url_for("gpu.available_gpus"))
            safe2, reason2 = automated_code_scan(code)
            if not safe2:
                flash(f"Automated scan failed: {reason2}", "danger")
                req_obj = GPUAccessRequest(
                    gpu_id=gpu_id,
                    client_id=current_user.id,
                    code=code,
                    status="denied",
                )
                db.session.add(req_obj)
                db.session.commit()
                return redirect(url_for("gpu.available_gpus"))

        # Check for existing pending request
        existing = GPUAccessRequest.query.filter(
            GPUAccessRequest.gpu_id == gpu_id,
            GPUAccessRequest.client_id == current_user.id,
            GPUAccessRequest.status.in_(["requested", "pending"]),
        ).first()
        if existing:
            flash("You have already submitted a request for this GPU.", "info")
        else:
            new_req = GPUAccessRequest(
                gpu_id=gpu_id,
                client_id=current_user.id,
                code=code if code else None,
                status="requested",
            )
            db.session.add(new_req)
            db.session.commit()
            # Notify the owner via email
            try:
                owner: User = User.query.get(gpu.host_user_id)
                subject = f"🔔 New GPU Access Request #{new_req.id}"
                requested_at = new_req.request_time.strftime("%Y-%m-%d %H:%M UTC")
                body = f"""
Hello {owner.username},

You have a new access request for your GPU:

----------------------------------------
Request ID:   {new_req.id}
Client:       {current_user.username} ({current_user.email})
GPU:          {gpu.name} (ID {gpu.id})
Requested At: {requested_at}
----------------------------------------

Next steps:
  • Visit your dashboard to Approve or Deny this request.
  • Approved requests grant the client temporary access.
  • Denied requests will notify the client of the decision.

Thank you for managing your GPU resources responsibly!

— GPUShare Notification System
"""
                msg = Message(subject=subject, recipients=[owner.email])
                msg.body = body
                mail.send(msg)
            except Exception:  # pragma: no cover
                pass
            flash("GPU access request submitted.", "success")
        return redirect(url_for("gpu.available_gpus"))

    return render_template("request_gpu.html", gpu=gpu)


@gpu_bp.route("/my_requests")
@login_required
def my_requests():
    """List requests submitted by the current user."""
    reqs: List[GPUAccessRequest] = GPUAccessRequest.query.filter_by(client_id=current_user.id).all()
    return render_template("my_requests.html", requests=reqs)


@gpu_bp.route("/gpu/<int:gpu_id>/requests")
@login_required
def gpu_requests(gpu_id: int):
    """Show requests for a GPU.  Only owners, moderators and admins may view."""
    gpu: GPU = GPU.query.get_or_404(gpu_id)
    if not (current_user.id == gpu.host_user_id or current_user.role in ["admin", "moderator"]):
        flash("Unauthorized to view requests for this GPU.", "danger")
        return redirect(url_for("auth.index"))
    reqs: List[GPUAccessRequest] = GPUAccessRequest.query.filter_by(gpu_id=gpu_id).all()
    return render_template("gpu_requests.html", gpu=gpu, requests=reqs)


@gpu_bp.route("/approve_request/<int:req_id>")
@login_required
def approve_request(req_id: int):
    """Approve an access request.  Only owners, moderators and admins may approve."""
    req_obj: GPUAccessRequest = GPUAccessRequest.query.get_or_404(req_id)
    gpu: GPU = GPU.query.get(req_obj.gpu_id)
    if not (current_user.id == gpu.host_user_id or current_user.role in ["admin", "moderator"]):
        flash("Unauthorized to approve requests.", "danger")
        return redirect(url_for("auth.index"))
    if req_obj.status != "requested":
        flash("Request is not pending.", "info")
        return redirect(url_for("gpu.gpu_requests", gpu_id=gpu.id))
    req_obj.status = "approved"
    req_obj.verified_by = current_user.username
    req_obj.verified_time = datetime.utcnow()
    req_obj.access_expires = datetime.utcnow() + timedelta(hours=1)
    db.session.commit()
    # Notify the client
    try:
        requester: User = User.query.get(req_obj.client_id)
        expires_str = req_obj.access_expires.strftime("%Y-%m-%d %H:%M UTC")
        subject = f"✅ GPUShare Access Approved (Request #{req_obj.id})"
        body = f"""
Hello {requester.username},

Good news—your access request for GPU “{gpu.name}” (ID {gpu.id}) has been approved!

----------------------------------------
Request ID:   {req_obj.id}
Approved By:  {current_user.username}
Expires At:   {expires_str}
----------------------------------------

You may now use the GPU until the expiry time above.

If you have any questions, or if this was unexpected, please contact your GPU owner or an administrator.

Happy computing!
— GPUShare Access Team
"""
        msg = Message(subject=subject, recipients=[requester.email])
        msg.body = body
        mail.send(msg)
    except Exception:  # pragma: no cover
        pass
    flash(f"Request {req_obj.id} approved.", "success")
    return redirect(url_for("gpu.gpu_requests", gpu_id=req_obj.gpu_id))


@gpu_bp.route("/deny_request/<int:req_id>")
@login_required
def deny_request(req_id: int):
    """Deny an access request."""
    req_obj: GPUAccessRequest = GPUAccessRequest.query.get_or_404(req_id)
    gpu: GPU = GPU.query.get(req_obj.gpu_id)
    if not (current_user.id == gpu.host_user_id or current_user.role in ["admin", "moderator"]):
        flash("Unauthorized to deny requests.", "danger")
        return redirect(url_for("auth.index"))
    if req_obj.status != "requested":
        flash("Request is not pending.", "info")
        return redirect(url_for("gpu.gpu_requests", gpu_id=gpu.id))
    req_obj.status = "denied"
    req_obj.verified_by = current_user.username
    req_obj.verified_time = datetime.utcnow()
    db.session.commit()
    # Notify the client
    try:
        requester: User = User.query.get(req_obj.client_id)
        subject = f"🚫 GPUShare Access Denied (Request #{req_obj.id})"
        body = f"""
Hello {requester.username},

We’re sorry, but your request to access GPU “{gpu.name}” (ID {gpu.id}) has been denied.

----------------------------------------
Request ID: {req_obj.id}
Denied By:  {current_user.username}
----------------------------------------

If you believe this is an error, you can reach out to the GPU owner or an administrator directly.
You’re also welcome to submit a new request if your needs change.

Thank you for understanding.
— GPUShare Support Team
"""
        msg = Message(subject=subject, recipients=[requester.email])
        msg.body = body
        mail.send(msg)
    except Exception:  # pragma: no cover
        pass
    flash(f"Request {req_obj.id} denied.", "info")
    return redirect(url_for("gpu.gpu_requests", gpu_id=req_obj.gpu_id))