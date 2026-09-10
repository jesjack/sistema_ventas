from __future__ import annotations

import hashlib
import re
import threading
import time
import uuid


def md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def new_nonce() -> str:
    return uuid.uuid4().hex


def parse_authorization(header_value: str) -> dict[str, str]:
    """Parsea un header 'Authorization: Digest ...' a un dict de campos.
    Acepta valores con o sin comillas (qop y nc suelen venir sin comillas)."""
    if not header_value or not header_value.lower().startswith("digest "):
        return {}

    fields: dict[str, str] = {}
    body = header_value[len("Digest "):]
    for match in re.finditer(r'(\w+)=(?:"([^"]*)"|([^,\s]*))', body):
        key = match.group(1)
        value = match.group(2) if match.group(2) is not None else match.group(3)
        fields[key] = value
    return fields


class NonceStore:
    """Nonces con expiracion. A diferencia de un esquema de un solo uso, un
    mismo nonce se puede reutilizar en requests sucesivos de la misma sesion
    (asi es como FFmpeg maneja RTSP: negocia el reto 401 una vez con
    OPTIONS y reusa ese nonce, incrementando nc, para SETUP/DESCRIBE/PLAY
    sin volver a retar) -- la proteccion real contra repeticion es exigir
    que nc crezca estrictamente en cada uso de un mismo nonce."""

    def __init__(self, ttl_seconds: float = 300.0) -> None:
        self._ttl = ttl_seconds
        self._issued: dict[str, dict[str, float | int]] = {}
        self._lock = threading.Lock()

    def issue(self) -> str:
        nonce = new_nonce()
        with self._lock:
            self._prune()
            self._issued[nonce] = {"issued_at": time.monotonic(), "last_nc": 0}
        return nonce

    def validate_nc(self, nonce: str, nc_hex: str) -> bool:
        """True si el nonce existe, no expiro, y nc es mayor al ultimo nc
        visto para ese nonce (monotonico, evita reproducir la misma
        respuesta digest dos veces)."""
        try:
            nc_value = int(nc_hex, 16)
        except ValueError:
            return False

        with self._lock:
            self._prune()
            entry = self._issued.get(nonce)
            if entry is None or nc_value <= entry["last_nc"]:
                return False
            entry["last_nc"] = nc_value
            return True

    def _prune(self) -> None:
        cutoff = time.monotonic() - self._ttl
        expired = [nonce for nonce, entry in self._issued.items() if entry["issued_at"] < cutoff]
        for nonce in expired:
            del self._issued[nonce]


def validate_digest_response(
    fields: dict[str, str],
    *,
    method: str,
    username: str,
    password: str,
    realm: str,
) -> bool:
    """Valida la formula RFC 2617 con qop=auth (la que usa
    requests.auth.HTTPDigestAuth y el protocolo http de FFmpeg)."""
    required = ("username", "nonce", "uri", "response", "nc", "cnonce", "qop")
    if any(key not in fields for key in required):
        return False

    if fields["username"] != username or fields["qop"] != "auth":
        return False

    ha1 = md5(f"{username}:{realm}:{password}")
    ha2 = md5(f"{method}:{fields['uri']}")
    expected = md5(f"{ha1}:{fields['nonce']}:{fields['nc']}:{fields['cnonce']}:{fields['qop']}:{ha2}")
    return expected == fields["response"]
