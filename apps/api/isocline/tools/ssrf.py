"""SSRF protection for outbound HTTP made on behalf of agents."""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

from isocline.core.config import get_settings

from .base import ToolError

METADATA_HOSTS = {"metadata.google.internal", "metadata", "metadata.azure.com", "instance-data"}
METADATA_IPS = {ipaddress.ip_address("169.254.169.254"), ipaddress.ip_address("fd00:ec2::254"),
                ipaddress.ip_address("100.100.100.200")}


def ip_is_blocked(ip: ipaddress._BaseAddress) -> bool:
    if ip in METADATA_IPS:
        return True
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return ip_is_blocked(ip.ipv4_mapped)
    return (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
            or ip.is_unspecified or (isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10")))


async def check_url(url: str) -> str:
    """Validates scheme and every resolved address. Returns the hostname. Raises ToolError when blocked.

    This check alone does not stop DNS rebinding (the client resolves again when it connects); callers that make the
    request themselves should use pinned_request() so the connection goes to the address that was checked."""
    host, _ = await _check(url)
    return host


async def _check(url: str) -> tuple[str, str | None]:
    """(hostname, pinned IP or None when the host was allowlisted by the administrator)."""
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise ToolError("Only http and https URLs are allowed")
    host = (p.hostname or "").lower().rstrip(".")
    if not host:
        raise ToolError("URL has no host")
    allowed = {h.lower() for h in get_settings().allow_private_network_hosts}
    if host in allowed:
        return host, None
    if host in METADATA_HOSTS or host == "localhost" or host.endswith(".localhost") or host.endswith(".internal"):
        raise ToolError(f"Blocked host: {host}")
    try:
        ip = ipaddress.ip_address(host)
        if ip_is_blocked(ip):
            raise ToolError(f"Blocked address: {host}")
        return host, str(ip)
    except ValueError:
        pass
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ToolError(f"Could not resolve {host}") from e
    first = None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip_is_blocked(ip):
            raise ToolError(f"Blocked: {host} resolves to a private or internal address")
        first = first or str(ip)
    return host, first


async def pinned_request(url: str) -> tuple[str, dict, dict]:
    """Checks `url` and returns (request_url, extra_headers, httpx_extensions) that connect to the exact address that
    was checked. The Host header and TLS SNI keep the original name, so virtual hosting and certificate verification
    are unchanged. This closes the DNS-rebinding gap between check and connect."""
    host, ip = await _check(url)
    if ip is None:
        return url, {}, {}
    p = urlparse(url)
    literal = f"[{ip}]" if ":" in ip else ip
    netloc = literal + (f":{p.port}" if p.port else "")
    headers = {"Host": p.netloc.rsplit("@", 1)[-1]}
    ext = {"sni_hostname": host} if p.scheme == "https" else {}
    return p._replace(netloc=netloc).geturl(), headers, ext
