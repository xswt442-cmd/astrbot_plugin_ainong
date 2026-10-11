"""PKCS#1 v1.5 块结构的构造与解析。

营地登录响应里的 `encodeRes` 是服务端用私钥做一次 PKCS#1 v1.5 运算的结果，
客户端用内置公钥还原出明文。还原结果的结构是：

    0x00 || 0x01 || 0xFF 重复若干 || 0x00 || 明文

分隔符 `0x00` 的位置由填充规则确定，不是"第一个 0x00"——明文本身可以以零字节开头。
"""

from __future__ import annotations

__all__ = ["build_encoded_block", "parse_encoded_block", "strip_pkcs1_padding"]

_头 = b"\x00\x01"
_填充 = b"\xff"
_分隔 = b"\x00"


def build_encoded_block(明文: bytes, size: int = 128) -> bytes:
    """构造 PKCS#1 v1.5 块。仅测试与构造样例用，不参与生产解码路径。"""
    填充长度 = size - len(明文) - len(_头) - 1
    if 填充长度 < 8:
        raise ValueError(f"明文过长，{size} 字节块放不下")
    return _头 + _填充 * 填充长度 + _分隔 + 明文


def strip_pkcs1_padding(block: bytes) -> bytes:
    """剥掉块头、填充与分隔字节，返回明文。"""
    if len(block) < 3:
        raise ValueError(f"块长度不足 3 字节：{len(block)}")
    if block[0] != 0x00 or block[1] != 0x01:
        raise ValueError(f"块类型字节应为 0x00 0x01，实际 {block[0]:02x} {block[1]:02x}")

    填充结束 = 2
    while 填充结束 < len(block) and block[填充结束] == 0xFF:
        填充结束 += 1

    if 填充结束 < 10:
        raise ValueError(f"填充少于 8 字节：{填充结束 - 2}")

    if 填充结束 >= len(block) or block[填充结束] != 0x00:
        raise ValueError("填充之后缺少 0x00 分隔字节")

    return block[填充结束 + 1 :]


def parse_encoded_block(block: bytes) -> bytes:
    """还原 PKCS#1 v1.5 块中的明文。"""
    return strip_pkcs1_padding(block)
