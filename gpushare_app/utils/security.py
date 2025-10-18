"""
Security helpers
================

This module collects security related helpers used throughout the
application.  The functions herein are designed to be self-contained
and easily testable.  In particular, code scanning utilities are
provided to detect obviously malicious or dangerous code patterns
before execution.  A decorator is also provided to enforce API token
authentication on JSON API endpoints.
"""

from __future__ import annotations

import ast
import secrets
import string
from datetime import datetime
from functools import wraps
from typing import Callable, Tuple, Any

from flask import request, jsonify

from ..extensions import db
from ..models import APIToken


class UnsafeCodeVisitor(ast.NodeVisitor):
    """An AST visitor that flags potentially dangerous constructs.

    The visitor can be extended to catch additional classes of
    malicious behaviour.  Currently it blocks imports of modules such
    as ``os`` and ``subprocess`` and calls to functions like
    ``eval`` and ``exec``.
    """

    def __init__(self) -> None:
        self.unsafe: bool = False
        self.reason: str = ""

    def generic_visit(self, node: ast.AST) -> None:
        if self.unsafe:
            return  # Short-circuit if already unsafe
        super().generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        dangerous_modules = {"os", "sys", "subprocess", "shutil", "socket", "psutil"}
        for alias in node.names:
            if alias.name.split(".")[0] in dangerous_modules:
                self.unsafe = True
                self.reason = f"Importing module '{alias.name}' is not allowed."
                return
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        dangerous_modules = {"os", "sys", "subprocess", "shutil", "socket", "psutil"}
        if node.module and node.module.split(".")[0] in dangerous_modules:
            self.unsafe = True
            self.reason = f"Importing from module '{node.module}' is not allowed."
            return
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        dangerous_functions = {"eval", "exec", "open", "__import__"}
        if isinstance(node.func, ast.Name) and node.func.id in dangerous_functions:
            self.unsafe = True
            self.reason = f"Call to function '{node.func.id}' is not allowed."
            return
        if isinstance(node.func, ast.Attribute):
            dangerous_attrs = {"system", "popen", "remove", "rmdir", "mkdir", "chdir"}
            if node.func.attr in dangerous_attrs:
                self.unsafe = True
                self.reason = f"Call to method '{node.func.attr}' is not allowed."
                return
        self.generic_visit(node)


def safe_code_check(code: str) -> Tuple[bool, str]:
    """Parse ``code`` and detect dangerous constructs.

    Returns a tuple ``(is_safe, reason)`` where ``is_safe`` is ``True`` if
    no dangerous constructs are found.  If ``is_safe`` is ``False`` the
    second element of the tuple contains the reason why the code was
    rejected.
    """
    try:
        tree = ast.parse(code)
    except Exception as exc:  # pragma: no cover - parse errors return directly
        return False, f"Code could not be parsed: {exc}"
    visitor = UnsafeCodeVisitor()
    visitor.visit(tree)
    if visitor.unsafe:
        return False, visitor.reason
    return True, "Code is safe."


def automated_code_scan(code: str) -> Tuple[bool, str]:
    """Run a basic pattern scan over the submitted code.

    This heuristic check looks for obviously malicious patterns such as
    ``eval(``, ``exec(``, ``os.system`` and so forth.  It is not meant
    to be exhaustive but serves as a second line of defence beyond the
    AST-based :func:`safe_code_check`.
    """
    suspicious_patterns = [
        "import virus", "eval(", "exec(", "os.system", "subprocess.Popen", "__import__"
    ]
    for pattern in suspicious_patterns:
        if pattern in code:
            return False, f"Suspicious pattern '{pattern}' detected."
    return True, "Code passed automated scan."


def require_api_token(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator ensuring a valid API token is present in the request.

    The token must be supplied in the ``Authorization`` header as a
    bearer token (e.g. ``Authorization: Bearer <token>``).  If the
    token is missing, expired or revoked a 401 JSON response will be
    returned.  Upon success the associated user and token objects are
    attached to the Flask ``request`` object as ``api_user`` and
    ``api_token_obj`` for downstream handlers.
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401
        token_str = auth_header.split(None, 1)[1]
        token_obj: APIToken | None = APIToken.query.filter_by(token=token_str).first()
        if not token_obj or not token_obj.is_valid():
            return jsonify({"error": "Invalid or expired API token"}), 401
        # Attach to request for downstream use
        request.api_user = token_obj.user  # type: ignore[attr-defined]
        request.api_token_obj = token_obj  # type: ignore[attr-defined]
        return func(*args, **kwargs)

    return wrapper


def generate_random_token(length: int = 32) -> str:
    """Generate a URL-safe random token of ``length`` characters."""
    alphabet = string.ascii_letters + string.digits + "-_"
    return ''.join(secrets.choice(alphabet) for _ in range(length))
