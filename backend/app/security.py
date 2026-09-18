import ipaddress
import socket
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException

from .config import settings


def normalize_video_url(value: str) -> str:
    """Convert known platform listing links into their canonical video URL."""
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if host.endswith("douyin.com") and parsed.path.rstrip("/") == "/jingxuan":
        modal_id = parse_qs(parsed.query).get("modal_id", [""])[0]
        if modal_id.isdigit():
            return f"https://www.douyin.com/video/{modal_id}"
    return value


def validate_source_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(422, "仅支持有效的 HTTP/HTTPS 公开链接")
    host = parsed.hostname.lower()
    if settings.allowlist and host not in settings.allowlist:
        raise HTTPException(403, "该来源不在服务允许列表中")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, None)}
    except socket.gaierror as exc:
        raise HTTPException(422, "无法解析该链接的主机名") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise HTTPException(403, "不允许访问本地或私有网络地址")


def safe_filename(value: str, fallback: str = "video") -> str:
    filtered = "".join(char if char.isalnum() or char in " ._-" else "_" for char in value).strip(" .")
    return (filtered or fallback)[:180]
