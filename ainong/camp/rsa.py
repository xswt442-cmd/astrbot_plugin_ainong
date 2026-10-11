"""分块 RSA 加密。

营地客户端把设备指纹用内置公钥加密后放进登录表单。明文超过单块容量时
按块切开逐块加密再顺序拼接，接收端按同样的顺序还原。
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

__all__ = ["分块加密", "载入公钥"]

_公钥b64 = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC0h62mV/zjJtFsNdfFNlxksfUOpjDI2KCcBrPiA8T7"
    "szABT4InLDTrdXAW84QyGNiazB0i7pgPCNGSAYbiJrCRutZ5jQsVS0Wg/RnXfwVQDJcAHJDjP5IXyroe"
    "LX7NUxDai8nPcpfRsvq6sneobyPexZSH0TlVSnecsJZTj5wu/wIDAQAB"
)


def 载入公钥():
    """载入营地客户端内置的 RSA 公钥（1024 位）。"""
    行 = [_公钥b64[i : i + 64] for i in range(0, len(_公钥b64), 64)]
    pem = "-----BEGIN PUBLIC KEY-----\n" + "\n".join(行) + "\n-----END PUBLIC KEY-----"
    return serialization.load_pem_public_key(pem.encode("ascii"))


def 分块加密(数据: bytes) -> bytes:
    """按单块容量切分后逐块加密，结果顺序拼接。"""
    公钥 = 载入公钥()
    单块容量 = 公钥.key_size // 8 - 11
    输出 = bytearray()
    for 起点 in range(0, len(数据), 单块容量):
        输出.extend(公钥.encrypt(数据[起点 : 起点 + 单块容量], padding.PKCS1v15()))
    return bytes(输出)


def 分块加密b64(数据: bytes) -> str:
    """加密并直接给出 base64，便于放进表单字段。"""
    return base64.b64encode(分块加密(数据)).decode("ascii")
