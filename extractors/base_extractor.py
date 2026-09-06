import re
import socket
import ipaddress
import urllib.parse
from typing import Tuple
from fastapi import Request

DISALLOWED_HOSTNAMES = {
    "localhost", "localhost.localdomain", "local", "internal",
    "0.0.0.0", "127.0.0.1", "::1", "metadata.google.internal",
    "instance-data", "169.254.169.254"
}


def is_safe_public_url(raw_url: str) -> Tuple[bool, str]:
    """
    Validates URL against Server-Side Request Forgery (SSRF) and DNS rebinding:
    1. Validates scheme is strictly http or https.
    2. Resolves target hostname via DNS.
    3. Verifies every resolved IP is a public unicast IP address.
    """
    if not raw_url or not isinstance(raw_url, str):
        return False, "Invalid URL string"

    url_str = raw_url.strip()
    try:
        parsed = urllib.parse.urlparse(url_str)
    except Exception:
        return False, "Unparseable URL format"

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return False, f"Forbidden URL scheme '{scheme}'. Only http and https are allowed."

    hostname = parsed.hostname
    if not hostname:
        return False, "URL contains no target hostname"

    host_lower = hostname.lower()

    # Block explicit local/metadata hostnames
    if host_lower in DISALLOWED_HOSTNAMES or host_lower.endswith(".local") or host_lower.endswith(".internal"):
        return False, f"Access to local/internal host '{hostname}' is blocked."

    # DNS Resolution to check resolved IP addresses against private/reserved subnets
    try:
        # Resolve both IPv4 and IPv6 addresses
        addr_info = socket.getaddrinfo(host_lower, parsed.port or (443 if scheme == "https" else 80), socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        # Unable to resolve domain (or invalid hostname)
        return False, f"Domain name resolution failed for '{hostname}'"
    except Exception as resolve_err:
        return False, f"DNS lookup error: {resolve_err}"

    if not addr_info:
        return False, f"No IP addresses resolved for domain '{hostname}'"

    for family, socktype, proto, canonname, sockaddr in addr_info:
        ip_str = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            return False, f"Invalid IP address resolved: {ip_str}"

        if (
            ip_obj.is_loopback
            or ip_obj.is_private
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
            or ip_obj.is_unspecified
        ):
            return False, f"Security Block: Target domain resolves to non-public IP ({ip_str})"

    return True, "OK"


def sanitize_filename(name: str, extension: str) -> str:
    """
    Sanitizes string for HTTP Content-Disposition headers.
    Strips non-ASCII characters, smart quotes, and illegal path characters.
    """
    name = name.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    cleaned = re.sub(r'[^\x00-\x7F]+', '', name)
    cleaned = re.sub(r'[\\/*?:"<>|]', '', cleaned)
    cleaned = cleaned.strip() or "downloaded_media"
    return f"{cleaned}.{extension}"


def sanitize_cli_argument(text: str) -> str:
    """
    Sanitizes user input strings passed as CLI arguments to yt-dlp or FFmpeg
    to prevent command/argument injection.
    Strips leading hyphens, control characters, and dangerous characters.
    """
    if not text:
        return ""
    # Remove control characters and non-printable characters
    cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', str(text))
    # Strip leading hyphens to prevent argument injection (--option)
    cleaned = cleaned.lstrip('-')
    # Keep alphanumeric, spaces, and basic safe punctuation
    cleaned = re.sub(r'[^\w\s\.\,\!\?\-]', ' ', cleaned)
    return " ".join(cleaned.split()[:8]).strip()


def is_valid_ip(ip_str: str) -> bool:
    """Validates that a string is a well-formed IP address and not a loopback/unspecified address."""
    try:
        ip_obj = ipaddress.ip_address(ip_str.strip())
        return not (ip_obj.is_loopback or ip_obj.is_unspecified)
    except Exception:
        return False


def is_private_or_local_ip(ip_str: str) -> bool:
    try:
        ip_obj = ipaddress.ip_address(ip_str.strip())
        return (
            ip_obj.is_loopback
            or ip_obj.is_private
            or ip_obj.is_link_local
            or ip_obj.is_reserved
            or ip_obj.is_unspecified
        )
    except Exception:
        return True


def get_client_ip(request: Request) -> str:
    """
    Extracts the end-user public client IP address:
    1. Query parameter (?client_ip=...)
    2. Header: X-Client-IP
    3. Header: CF-Connecting-IP (Cloudflare)
    4. Header: X-Real-IP (Nginx / Reverse Proxy)
    5. Header: X-Forwarded-For (leftmost public client IP from Google Cloud Load Balancer)
    6. Direct socket client host (if public)
    7. Local fallback (127.0.0.1)
    """
    # 1. Query parameter
    q_ip = request.query_params.get("client_ip")
    if q_ip and is_valid_ip(q_ip):
        return q_ip.strip()

    # 2. X-Client-IP header
    c_ip = request.headers.get("x-client-ip")
    if c_ip and is_valid_ip(c_ip):
        return c_ip.strip()

    # 3. CF-Connecting-IP header (Cloudflare)
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip and is_valid_ip(cf_ip):
        return cf_ip.strip()

    # 4. X-Real-IP header (Reverse Proxy)
    real_ip = request.headers.get("x-real-ip")
    if real_ip and is_valid_ip(real_ip):
        return real_ip.strip()

    # 5. X-Forwarded-For header (Google Cloud Load Balancer / Proxy chain)
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        for p in parts:
            if is_valid_ip(p) and not is_private_or_local_ip(p):
                return p
        if parts and is_valid_ip(parts[0]):
            return parts[0]

    # 6. Socket client host (Direct connection)
    host = request.client.host if request.client else None
    if host and is_valid_ip(host) and not is_private_or_local_ip(host):
        return host

    # 7. Local fallback (avoids server egress NAT IP on Google Cloud)
    return (request.client.host if request.client else None) or "127.0.0.1"


def clean_target_url(raw_url: str) -> str:
    """
    Decodes target URLs and strips tracking query parameters while preserving media IDs.
    """
    unquoted = urllib.parse.unquote(raw_url.strip())
    while "/api/download" in unquoted and "url=" in unquoted:
        parsed = urllib.parse.urlparse(unquoted)
        qs = urllib.parse.parse_qs(parsed.query)
        if "url" in qs and qs["url"]:
            unquoted = urllib.parse.unquote(qs["url"][0].strip())
        else:
            break

    # Clean tracking query parameters for clean target URL processing
    parsed = urllib.parse.urlparse(unquoted)
    if parsed.query and not any(p in unquoted for p in ["spotify.com", "reddit.com", "scsearch:", "ytsearch"]):
        qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        # Strip tracking params: si, utm_*, igsh, fbclid, ref, share_id
        filtered_qs = {
            k: v for k, v in qs.items()
            if not (k.startswith("utm_") or k in ("si", "igsh", "fbclid", "ref", "share_id", "s"))
        }
        clean_query = urllib.parse.urlencode(filtered_qs, doseq=True)
        return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, clean_query, parsed.fragment))

    return unquoted

