"""
Authentication dependencies — Firebase Auth ID Token & App Check Verification.

Ensures that caller identity is validated server-side using the verified UID.
"""

from __future__ import annotations

import logging
from fastapi import Depends, HTTPException, Header, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import app_check, auth

from .settings import settings

logger = logging.getLogger(__name__)
security_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(
        security_bearer),
) -> str:
    """
    Validate the Firebase ID token in the Authorization header or X-Authorization header.

    Extracts and returns the verified user ID (uid).
    """
    token = None
    if credentials and credentials.credentials:
        token = credentials.credentials
    else:
        # Fallback to X-Authorization header to bypass Google Frontend (GFE) interception
        x_auth = request.headers.get("x-authorization")
        if x_auth and x_auth.startswith("Bearer "):
            token = x_auth[7:]
        elif x_auth:
            token = x_auth

    if not token:
        logger.warning(
            "Request missing Authorization or X-Authorization header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization token",
        )

    try:
        # Verify the Firebase ID token using admin SDK
        # This checks expiry and signature authenticity
        decoded_token = auth.verify_id_token(token)
        uid = decoded_token.get("uid")
        if not uid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing UID",
            )
        return uid
    except Exception as e:
        logger.error("Token verification failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token verification failed: {e}",
        )


def verify_app_check(
    x_firebase_appcheck: str | None = Header(default=None),
) -> None:
    """
    Verify Firebase App Check token to establish request authenticity.

    Supports 'monitor' (soft enforcement) and 'enforce' (strict rejection) modes.
    """
    mode = settings.app_check_mode
    if not x_firebase_appcheck or not x_firebase_appcheck.strip():
        msg = "Missing X-Firebase-AppCheck header"
        if mode == "enforce":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=msg,
            )
        logger.warning("%s (soft mode)", msg)
        return

    token = x_firebase_appcheck.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    # Verify JWT segment structure before passing to Admin SDK
    parts = token.split(".")
    if len(parts) != 3:
        msg = f"Malformed X-Firebase-AppCheck token structure (expected 3 JWT parts, got {len(parts)})"
        if mode == "enforce":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=msg,
            )
        logger.warning("%s (soft mode)", msg)
        return

    try:
        app_check.verify_token(token)
        logger.debug("App Check token verified successfully")
    except Exception as e:
        msg = f"App Check token verification failed: {e}"
        if mode == "enforce":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=msg,
            )
        logger.warning("%s (soft mode)", msg)

