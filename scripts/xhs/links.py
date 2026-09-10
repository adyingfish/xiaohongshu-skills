"""小红书笔记地址生成及短链接解析；不调用私有接口或读取浏览器凭据。"""

from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import ssl
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

_NOTE_HOSTS = {"xiaohongshu.com", "www.xiaohongshu.com"}
_SHORT_HOSTS = {"xhslink.com", "www.xhslink.com"}
_ID = re.compile(r"[0-9a-fA-F]{24}\Z")
_NOTE_PATH = re.compile(
    r"/(?:explore|discovery/item|user/profile/[0-9a-fA-F]{24})/([0-9a-fA-F]{24})/?\Z"
)
_URL = re.compile(r"https?://[^\s<>\"'，。；！？、）》]+", re.IGNORECASE)


def validate_feed_id(feed_id: str) -> str:
    if not isinstance(feed_id, str) or not _ID.fullmatch(feed_id):
        raise ValueError("笔记 ID 必须为 24 位十六进制字符")
    return feed_id


def make_share_url(feed_id: str, xsec_token: str = "", source: str = "pc_search") -> str:
    """生成可分享地址；令牌按原值编码，不保证无令牌地址的访问权限。"""
    validate_feed_id(feed_id)
    if not isinstance(xsec_token, str) or not isinstance(source, str):
        raise ValueError("令牌和来源必须为字符串")
    params = {"xsec_source": source}
    if xsec_token:
        params = {"xsec_token": xsec_token, **params}
    return f"https://www.xiaohongshu.com/explore/{feed_id}?{urlencode(params)}"


def _validate_url(url: str):
    if "\\" in url or any(ord(char) < 32 or ord(char) == 127 for char in url):
        raise ValueError("链接包含非法控制字符或反斜线")
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        raise ValueError("仅支持 HTTP 或 HTTPS 链接")
    if parts.username is not None or parts.password is not None:
        raise ValueError("链接不得包含用户名或密码")
    if parts.hostname not in _NOTE_HOSTS | _SHORT_HOSTS:
        raise ValueError("仅支持小红书笔记域名和 xhslink.com 短链接")
    if parts.port is not None and parts.port != (443 if parts.scheme == "https" else 80):
        raise ValueError("链接不得使用非标准端口")
    return parts


def extract_link(value: str) -> str:
    """接受单条 URL 或包含一条 URL 的分享文案；多链接时要求用户明确选择。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("请提供笔记链接或分享文案")
    urls = list(dict.fromkeys(
        match.rstrip("，。；！!？?、）)]}》") for match in _URL.findall(value.strip())
    ))
    if len(urls) != 1:
        raise ValueError("分享文案必须包含且仅包含一条 HTTP/HTTPS 链接")
    _validate_url(urls[0])
    return urls[0]


def parse_note_link(url: str) -> dict:
    """纯本地解析长链接，缺失令牌时明确返回 hasToken=false。"""
    parts = _validate_url(url)
    match = _NOTE_PATH.fullmatch(parts.path)
    if parts.hostname not in _NOTE_HOSTS or not match:
        raise ValueError("链接不是受支持的笔记详情地址（explore 或 discovery/item）")
    query = parse_qs(parts.query, keep_blank_values=True)
    tokens = query.get("xsec_token", [""])
    if len(tokens) != 1:
        raise ValueError("链接包含多个 xsec_token，无法确定使用哪一个")
    token = tokens[0]
    feed_id = match.group(1)
    return {
        "feedId": feed_id,
        "xsecToken": token,
        "hasToken": bool(token),
        "shareUrl": make_share_url(feed_id, token),
    }


def _public_address(host: str, port: int) -> str:
    """仅向公开地址建立连接；连接固定在已校验 IP，避免 DNS 二次解析。"""
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError("短链接域名没有可用地址")
    ips = list(dict.fromkeys(item[4][0] for item in addresses))
    if any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise ValueError("短链接域名解析到非公开地址，已拒绝连接")
    return ips[0]


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, ip: str, port: int, timeout: float):
        super().__init__(host, port=port, timeout=timeout)
        self._address = ip

    def connect(self):
        self.sock = socket.create_connection((self._address, self.port), self.timeout)


class _PinnedHTTPSConnection(_PinnedHTTPConnection):
    default_port = 443

    def connect(self):
        super().connect()
        try:
            self.sock = ssl.create_default_context().wrap_socket(
                self.sock, server_hostname=self.host,
            )
        except Exception:
            self.close()
            raise


def _redirect_location(url: str, timeout: float) -> str:
    parts = _validate_url(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    address = _public_address(parts.hostname, port)
    cls = _PinnedHTTPSConnection if parts.scheme == "https" else _PinnedHTTPConnection
    connection = cls(parts.hostname, address, port, timeout)
    target = urlunsplit(("", "", parts.path or "/", parts.query, ""))
    try:
        connection.request("GET", target, headers={"User-Agent": "XHS-Skills-LinkResolver/1.0"})
        response = connection.getresponse()
        location = response.getheader("Location")
        if response.status not in {301, 302, 303, 307, 308} or not location:
            raise ValueError(
                f"短链接未返回可解析的 HTTP 重定向（状态 {response.status}）；"
                "请在浏览器打开后复制完整笔记地址"
            )
        return location
    finally:
        connection.close()


def resolve_link(value: str, *, max_redirects: int = 5, timeout: float = 10) -> dict:
    """逐跳解析可信短链；每次请求前验证域名、端口和公开 IP，不执行网页脚本。"""
    if not 1 <= max_redirects <= 10 or not 0 < timeout <= 30:
        raise ValueError("重定向次数应为 1–10，超时应大于 0 且不超过 30 秒")
    url = extract_link(value)
    visited = set()
    for hop in range(max_redirects + 1):
        parts = _validate_url(url)
        if parts.hostname in _NOTE_HOSTS:
            result = parse_note_link(url)
            result.update(resolvedUrl=url, redirects=hop, accessVerified=False)
            return result
        if url in visited:
            raise ValueError("短链接出现循环重定向")
        if hop == max_redirects:
            raise ValueError("短链接重定向次数超过限制")
        visited.add(url)
        url = urljoin(url, _redirect_location(url, timeout))
    raise ValueError("无法解析短链接")
