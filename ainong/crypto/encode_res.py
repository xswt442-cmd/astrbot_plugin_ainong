"""从 `encodeRes` 中取对称密钥。

营地登录响应的 `encodeRes` 用服务端私钥做过一次 PKCS#1 v1.5 运算，
客户端用内置公钥还原明文 JSON，其中 `userKey` 是后续请求参数的加密密钥。
"""

from __future__ import annotations

import json

from ainong.crypto.pkcs1 import strip_pkcs1_padding

__all__ = ["extract_user_key"]

_字段 = "userKey"


def extract_user_key(block: bytes) -> str:
    """从还原后的块中取出对称密钥。缺字段或格式不对时抛错。"""
    明文 = strip_pkcs1_padding(block)
    try:
        payload = json.loads(明文.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"还原出的内容不是 JSON：{exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"还原出的内容不是对象：{type(payload).__name__}")

    密钥 = payload.get(_字段)
    if not 密钥:
        raise ValueError(f"还原出的 JSON 缺少 {_字段} 字段")

    return str(密钥)
