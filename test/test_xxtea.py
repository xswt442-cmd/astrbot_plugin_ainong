"""XXTEA 实现的测试。

营地接口的请求参数用 XXTEA 加密，明文末尾追加 4 字节原始长度，
密钥不足 16 字节右侧补零、超过则截断到 16。

`test/fixtures/xxtea_vectors.json` 里的密文由参考实现
（`qsc20001102/astrbot_plugin_gok` 的 `core/xxtea.py`，已与 Node 端逐字节交叉校验）
经 `test/gen_xxtea_vectors.py` 生成。本文件读它断言密文逐字节一致，
所以实现改了而算法写错时，测试会失败。
"""

import json
from pathlib import Path

import pytest

from ainong.crypto.xxtea import decrypt, encrypt, normalize_key

向量文件 = Path(__file__).parent / "fixtures" / "xxtea_vectors.json"
向量 = json.loads(向量文件.read_text(encoding="utf-8"))
向量按名称 = {v["名称"]: v for v in 向量}


class TestNormalizeKey:
    def test_短密钥右侧补零到16字节(self):
        assert normalize_key(b"short") == b"short" + b"\x00" * 11

    def test_恰好16字节不动(self):
        assert normalize_key(b"0123456789abcdef") == b"0123456789abcdef"

    def test_超长密钥截断到16字节(self):
        assert normalize_key(b"0123456789abcdefEXTRA") == b"0123456789abcdef"


class TestAgainstReferenceVectors:
    """逐字节对照参考实现。这是本文件最主要的一组断言。"""

    @pytest.mark.parametrize("名称", [v["名称"] for v in 向量])
    def test_密文与参考实现一致(self, 名称):
        v = 向量按名称[名称]
        assert encrypt(bytes.fromhex(v["明文"]), bytes.fromhex(v["密钥"])).hex() == v["密文"]

    @pytest.mark.parametrize("名称", [v["名称"] for v in 向量])
    def test_参考密文能正确解开(self, 名称):
        v = 向量按名称[名称]
        assert decrypt(bytes.fromhex(v["密文"]), bytes.fromhex(v["密钥"])).hex() == v["明文"]


class TestRoundTrip:
    @pytest.mark.parametrize(
        "明文", [b"", b"A", b"0123456789abcdef", b"x" * 1000, b"ab\x00cd\x00\x00\x00"]
    )
    def test_加解密往返(self, 明文):
        assert decrypt(encrypt(明文, b"k"), b"k") == 明文

    def test_不同密钥加出不同密文(self):
        assert encrypt(b"same data", b"key1") != encrypt(b"same data", b"key2")

    def test_密文与明文不同(self):
        assert encrypt(b"a" * 16, b"k") != b"a" * 16


class TestRejectsCorruptInput:
    def test_密文长度非4的倍数时失败(self):
        with pytest.raises(ValueError):
            decrypt(b"\x01\x02\x03", b"key")

    def test_长度字段越界时失败(self):
        # 构造一个尾部长度字段远大于数据区的密文
        with pytest.raises(ValueError):
            decrypt(b"\x00" * 16, b"key")
