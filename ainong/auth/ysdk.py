"""YSDK 请求签名。

QQ 授权码换取平台凭据时，请求头里的签名必须与请求体逐字节对应。
签名串是六段换行连接，密钥与算法固定。
"""

from __future__ import annotations

import base64
import hashlib
import hmac

__all__ = [
    "YSDK_SIGN_KEY",
    "YSDK_URL",
    "build_auth_headers",
    "build_sign_text",
    "sign",
]

YSDK_SIGN_KEY = b"yyb@cloud_game:CQ8FA#"
YSDK_URL = "https://ysdk.qq.com/cmd/QQCodeLogin?"

_方法 = "POST"
_路径 = "/cmd/QQCodeLogin"
_内容类型 = "json"
_服务名 = "ysdk"


def build_sign_text(timestamp: str, body: str) -> str:
    """构造签名串。body 必须与实际发出的请求体逐字节相同。"""
    return "\n".join([_方法, _路径, _内容类型, _服务名, timestamp, body])


def sign(sign_text: str) -> str:
    """对签名串做 HMAC-SHA256，返回 base64 字符串。"""
    digest = hmac.new(YSDK_SIGN_KEY, sign_text.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def build_auth_headers(body: str, timestamp: str) -> dict[str, str]:
    """构造请求头。"""
    return {
        "Content-Type": _内容类型,
        "Auth-Secret-ID": _服务名,
        "Auth-Secret-Digest": sign(build_sign_text(timestamp, body)),
        "Auth-Request-Time": timestamp,
    }
