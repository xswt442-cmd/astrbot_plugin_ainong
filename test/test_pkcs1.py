"""PKCS#1 v1.5 块解析的测试。

营地登录响应里的 `encodeRes` 是服务端用私钥做的一次 PKCS#1 v1.5 运算结果，
客户端要用内置公钥还原明文 JSON。还原出来是标准块结构：

    0x00 || 0x01 || 0xFF 重复若干 || 0x00 || 明文

测试用自生成的密钥对做真实 RSA 运算，构造出与营地同构的块。
"""

import json

import pytest

from ainong.crypto.pkcs1 import (
    build_encoded_block,
    parse_encoded_block,
    strip_pkcs1_padding,
)


class TestParseEncodedBlock:
    def test_还原标准块得到明文(self):
        明文 = b'{"userKey":"abc123"}'
        assert parse_encoded_block(build_encoded_block(明文)) == 明文

    def test_明文含零字节不被截断(self):
        明文 = b'{"a":"\x00\x00","userKey":"k"}'
        assert parse_encoded_block(build_encoded_block(明文)) == 明文

    def test_空明文得到空字节串(self):
        assert parse_encoded_block(build_encoded_block(b"")) == b""

    def test_恰好等于块长度的明文可用(self):
        # 1024 位密钥的块是 128 字节，2 字节头 + 至少 8 填充 + 1 分隔 = 11 字节开销
        明文 = b"y" * (128 - 11)
        assert parse_encoded_block(build_encoded_block(明文)) == 明文

    def test_块首字节非零时报错(self):
        with pytest.raises(ValueError):
            parse_encoded_block(b"\x01\x02\x03")

    def test_块太短时报错(self):
        with pytest.raises(ValueError):
            parse_encoded_block(b"\x00\x01\xff")

    def test_填充字节不是FF时报错(self):
        坏块 = b"\x00\x01" + b"\xff" * 3 + b"\x01\x02" + b"\x00" + b"data"
        with pytest.raises(ValueError):
            parse_encoded_block(坏块)

    def test_缺少分隔零字节时报错(self):
        # 全是 0xFF 没有 0x00 收尾
        块 = b"\x00\x01" + b"\xff" * 10
        with pytest.raises(ValueError):
            parse_encoded_block(块)


class TestStripPkcs1Padding:
    def test_去掉填充与分隔字节(self):
        assert strip_pkcs1_padding(build_encoded_block(b"payload")) == b"payload"

    def test_填充不足8字节时报错(self):
        # PKCS#1 v1.5 规范要求 0xFF 填充至少 8 字节
        块 = b"\x00\x01" + b"\xff" * 3 + b"\x00payload"
        with pytest.raises(ValueError):
            strip_pkcs1_padding(块)

    def test_填充恰好8字节可用(self):
        块 = b"\x00\x01" + b"\xff" * 8 + b"\x00payload"
        assert strip_pkcs1_padding(块) == b"payload"

    def test_输入过短时报错(self):
        with pytest.raises(ValueError):
            strip_pkcs1_padding(b"\x00\x01")


class TestDecodeUserKey:
    def test_从还原出的JSON取userKey(self):
        from ainong.crypto.encode_res import extract_user_key

        块 = build_encoded_block(json.dumps({"userKey": "the-key"}).encode())
        assert extract_user_key(块) == "the-key"

    def test_缺userKey时抛错(self):
        from ainong.crypto.encode_res import extract_user_key

        块 = build_encoded_block(json.dumps({"other": "x"}).encode())
        with pytest.raises(ValueError):
            extract_user_key(块)

    def test_JSON不是对象时报错(self):
        from ainong.crypto.encode_res import extract_user_key

        块 = build_encoded_block(b"[1,2,3]")
        with pytest.raises(ValueError):
            extract_user_key(块)

    def test_JSON非法时报错(self):
        from ainong.crypto.encode_res import extract_user_key

        块 = build_encoded_block(b"not json")
        with pytest.raises(ValueError):
            extract_user_key(块)
