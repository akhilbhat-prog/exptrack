"""Auth decorators for Flask blueprints.

Admin access: ADMIN_TOKEN env var — passed as ?token= or Authorization: Bearer header.
User access:  valid Flask session cookie (role='user') set at /login.

Dev mode: if neither ADMIN_TOKEN nor INVITE_CODE is set, all routes are open.
"""

import os
from datetime import timedelta
from functools import wraps

from flask import abort, redirect, request, session, url_for


def _auth_disabled() -> bool:
    return not os.environ.get("ADMIN_TOKEN") and not os.environ.get("INVITE_CODE")


def _provided_token() -> str:
    return request.args.get("token") or (
        request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    )


def _is_valid_admin_token() -> bool:
    admin = os.environ.get("ADMIN_TOKEN", "").strip()
    return bool(admin and _provided_token().strip() == admin)


def _is_valid_user_session() -> bool:
    return session.get("role") in ("user", "admin")


def _is_valid_admin_session() -> bool:
    return session.get("role") == "admin"


def require_admin(f):
    """Allow if ADMIN_TOKEN matches OR session role is admin. Dev mode passes all."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if _auth_disabled() or _is_valid_admin_token() or _is_valid_admin_session():
            return f(*args, **kwargs)
        abort(401)
    return wrapper


def require_any_auth(f):
    """Allow if ADMIN_TOKEN matches OR a valid user session exists. Returns 401 JSON if neither."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if _auth_disabled() or _is_valid_admin_token() or _is_valid_user_session():
            return f(*args, **kwargs)
        abort(401)
    return wrapper


def require_user_page(f):
    """Allow if ADMIN_TOKEN matches OR a valid user session exists. Redirects to /login if neither."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if _auth_disabled() or _is_valid_admin_token() or _is_valid_user_session():
            return f(*args, **kwargs)
        return redirect(url_for("auth.login_page"))
    return wrapper
