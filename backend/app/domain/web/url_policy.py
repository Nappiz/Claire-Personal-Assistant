import ipaddress
from urllib.parse import urlsplit, urlunsplit

def normalize_public_url(value: object) -> str | None:
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return None
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address and not address.is_global:
        return None

    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))[:2048]
