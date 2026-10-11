"""XXTEA 加密解密。

营地接口的请求参数用 XXTEA 加密，约定：
- 明文按小端切成 32 位字，末尾追加 4 字节的原始明文长度
- 密钥不足 16 字节右侧补零，超过则截断到 16
- 轮数 `6 + 52 // n`（n 为字数组长度）

密文与 `test/fixtures/xxtea_vectors.json` 中的参考向量逐字节一致。
"""

from __future__ import annotations

import struct

__all__ = ["decrypt", "encrypt", "normalize_key"]

_MASK = 0xFFFFFFFF
_DELTA = 0x9E3779B9
_KEY_BYTES = 16


def normalize_key(key: bytes) -> bytes:
    """把密钥规整成 16 字节：不足右侧补零，超过截断。"""
    return key[:_KEY_BYTES].ljust(_KEY_BYTES, b"\x00")


def _to_words(data: bytes) -> list[int]:
    """小端 32 位字数组。"""
    padded = data + b"\x00" * (-len(data) % 4)
    return list(struct.unpack(f"<{len(padded) // 4}I", padded))


def _from_words(words: list[int], size: int) -> bytes:
    """字数组转回字节，取前size 字节。"""
    return struct.pack(f"<{len(words)}I", *words)[:size]


def _mx(sum_: int, y: int, z: int, p: int, e: int, key: list[int]) -> int:
    a = ((z >> 5) ^ ((y << 2) & _MASK)) & _MASK
    b = ((y >> 3) ^ ((z << 4) & _MASK)) & _MASK
    c = (a + b) & _MASK
    d = ((sum_ ^ y) + (key[(p & 3) ^ e] ^ z)) & _MASK
    return (c ^ d) & _MASK


def encrypt(data: bytes, key: bytes) -> bytes:
    """加密，返回按 4 字节对齐的字节串（尚未 base64）。"""
    if not data:
        return b""

    words = _to_words(data)
    words.append(len(data))
    key_words = _to_words(normalize_key(key))[:4]
    n = len(words)
    rounds = 6 + 52 // n
    last = n - 1

    total = 0
    z = words[last]
    for _ in range(rounds):
        total = (total + _DELTA) & _MASK
        e = (total >> 2) & 3
        for i in range(last):
            y = words[i + 1]
            words[i] = (words[i] + _mx(total, y, z, i, e, key_words)) & _MASK
            z = words[i]
        y = words[0]
        words[last] = (words[last] + _mx(total, y, z, last, e, key_words)) & _MASK
        z = words[last]

    return _from_words(words, len(words) * 4)


def decrypt(data: bytes, key: bytes) -> bytes:
    """解密，按密文尾部记录的长度还原原始明文。"""
    if not data:
        return b""

    if len(data) % 4 != 0:
        raise ValueError(f"密文长度必须是 4的倍数，实际 {len(data)}")

    words = _to_words(data)
    key_words = _to_words(normalize_key(key))[:4]
    n = len(words)
    last = n - 1
    rounds = 6 + 52 // n

    total = (rounds * _DELTA) & _MASK
    y = words[0]
    while total != 0:
        e = (total >> 2) & 3
        for i in range(last, 0, -1):
            z = words[i - 1]
            words[i] = (words[i] - _mx(total, y, z, i, e, key_words)) & _MASK
            y = words[i]
        z = words[last]
        words[0] = (words[0] - _mx(total, y, z, 0, e, key_words)) & _MASK
        y = words[0]
        total = (total - _DELTA) & _MASK

    size = words[-1]
    if size < 0 or size > n * 4 - 4:
        raise ValueError(f"密文记录的长度字段越界：{size}")

    return _from_words(words, size)
