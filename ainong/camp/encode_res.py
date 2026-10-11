"""从营地登录响应的 `encodeRes` 中取对称密钥。

`encodeRes` 有两种实际出现的形态，这里按内容分派：

- 明文形态：base64 编码的 JSON，解出来直接就是含`userKey` 的对象
- 密文形态：base64 编码的 RSA 运算结果。服务端持有私钥，对填充后的明文做
  一次幂运算；客户端方向相反，用营地内置公钥做逆运算取出明文

注意密文形态不能用 `cryptography` 的 `recover_data_from_signature`：
那个接口要求输入是对某个哈希的签名，还原出的是摘要结构。而营地做的是
raw private-key op（PKCS#1 v1.5 type 1 填充），传进去会抛 `InvalidSignature`。
"""

from __future__ import annotations

import base64
import binascii
import json

from ainong.camp.rsa import 载入公钥
from ainong.crypto.pkcs1 import strip_pkcs1_padding

__all__ = ["取出对称密钥"]

_字段 = "userKey"


def 取出对称密钥(encodeRes: str) -> str:
    """从 `encodeRes` 取出对称密钥。"""
    if not encodeRes:
        raise ValueError("encodeRes 为空")

    try:
        原始 = base64.b64decode(encodeRes, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"encodeRes 不是合法的 base64：{exc}") from exc

    明文 = _按形态解出(原始)
    return _从JSON取密钥(明文)


def _按形态解出(原始: bytes) -> bytes:
    """明文形态直接解，密文形态做一次 RSA 逆运算。"""
    候选 = 原始.lstrip()
    if 候选[:1] == b"{":
        return 原始

    公钥 = 载入公钥()
    期望长度 = 公钥.key_size // 8
    if len(原始) != 期望长度:
        raise ValueError(f"既不是明文 JSON，长度 {len(原始)} 也不是 RSA 块长度 {期望长度}")

    数字 = 公钥.public_numbers()
    明文块 = pow(int.from_bytes(原始, "big"), 数字.e, 数字.n).to_bytes(期望长度, "big")
    return strip_pkcs1_padding(明文块)


def _从JSON取密钥(明文: bytes) -> str:
    try:
        载荷 = json.loads(明文.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"还原出的内容不是 JSON：{exc}") from exc

    if not isinstance(载荷, dict):
        raise ValueError(f"还原出的内容不是对象：{type(载荷).__name__}")

    密钥 = 载荷.get(_字段)
    if not 密钥:
        raise ValueError(f"还原出的 JSON 缺少 {_字段} 字段")

    return str(密钥)
