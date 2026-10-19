from urllib.parse import urlsplit

import httpx
import jwt
from jwt import PyJWKClient

from billshield.ports import Identity


class AuthenticationError(ValueError):
    pass


class JWTAuth:
    """Pinned issuer/JWKS; never use a token-supplied key URL or symmetric secret."""

    ALGORITHMS = ("RS256", "ES256")

    def __init__(
        self,
        issuer: str,
        audience: str,
        jwks_client=None,
        *,
        jwks_url: str | None = None,
        userinfo_url: str | None = None,
        publishable_key: str = "",
        http_client=None,
    ):
        parsed = urlsplit(issuer)
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
        ):
            raise ValueError("Auth issuer must use HTTPS (HTTP allowed only on loopback)")
        if parsed.query or parsed.fragment or parsed.username:
            raise ValueError("Invalid issuer")
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.userinfo_url = userinfo_url
        self.publishable_key = publishable_key
        self.http = http_client or httpx.Client(timeout=5, follow_redirects=False)
        self.jwks = jwks_client or PyJWKClient(
            jwks_url or f"{self.issuer}/.well-known/jwks.json", cache_keys=True, timeout=5
        )

    def verify(self, token: str) -> Identity:
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") not in self.ALGORITHMS or not header.get("kid"):
                raise AuthenticationError("Unsupported signing key")
            key = self.jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=list(self.ALGORITHMS),
                issuer=self.issuer,
                audience=self.audience,
                options={"require": ["exp", "iss", "aud", "sub", "email"]},
            )
            # Only issuer-controlled top-level claims or authenticated provider user-info
            # can prove verification. User-editable metadata is never consulted.
            if not isinstance(claims["sub"], str) or not claims["sub"]:
                raise AuthenticationError("Invalid subject")
            email = claims["email"]
            if not isinstance(email, str) or "@" not in email or "\n" in email or "\r" in email:
                raise AuthenticationError("Invalid email")
            if claims.get("email_verified") is not True:
                self._verify_provider_email(token, claims["sub"], email)
            return Identity(self.issuer, claims["sub"], email)
        except (jwt.PyJWTError, KeyError, TypeError, ValueError, httpx.HTTPError) as exc:
            raise AuthenticationError("Invalid or unverified access token") from exc

    def _verify_provider_email(self, token: str, subject: str, email: str) -> None:
        if not self.userinfo_url:
            raise AuthenticationError("Trusted verified email evidence required")
        headers = {"Authorization": f"Bearer {token}"}
        if self.publishable_key:
            headers["apikey"] = self.publishable_key
        response = self.http.get(self.userinfo_url, headers=headers)
        response.raise_for_status()
        user = response.json()
        if not isinstance(user, dict):
            raise AuthenticationError("Invalid provider user-info response")
        # GoTrue /user uses id + email_confirmed_at. OIDC uses sub + email_verified.
        confirmed = user.get("email_verified") is True or bool(user.get("email_confirmed_at"))
        if (
            (user.get("sub") or user.get("id")) != subject
            or str(user.get("email", "")).casefold() != email.casefold()
            or not confirmed
        ):
            raise AuthenticationError("Provider did not confirm this subject/email")
