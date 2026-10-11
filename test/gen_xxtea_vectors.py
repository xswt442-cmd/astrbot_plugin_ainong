"""用参考实现生成真值向量，供测试锁定算法行为。

参考实现是第三方代码，不随本仓库分发。需要重新生成向量时，
把参考实现保存为 `test/gen/xxtea_ref.py`，然后运行本脚本。
已提交的 `test/fixtures/xxtea_vectors.json` 是它的输出，日常开发不需要本脚本。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "gen"))

try:
    import xxtea_ref as ref
except ModuleNotFoundError as exc:
    raise SystemExit("缺少参考实现：把参考文件放到 test/gen/xxtea_ref.py 后重跑") from exc

CASES = [
    ("空字节串", b"", b"key"),
    ("单字节", b"A", b"key"),
    ("正好一块", b"0123456789abcdef", b"k"),
    ("短密钥", b"hello world", b"short"),
    ("长密钥", b"hello world", b"0123456789abcdefEXTRA"),
    ("含零字节", b"ab\x00cd\x00\x00\x00", b"k"),
    ("恰好16字节密钥", b"payload", b"0123456789abcdef"),
    ("多块明文", b"x" * 1000, b"key"),
    (
        "真实请求体形态",
        b'{"timestamp":1700000000000,'
        b'"nonce":"1234:abcdef0123456789abcdef0123456789:1700000000000"}',
        b"userkey-bytes",
    ),
    ("中文", "爱农".encode(), b"key"),
]


def main() -> None:
    向量 = []
    for 名称, 明文, 密钥 in CASES:
        向量.append(
            {
                "名称": 名称,
                "明文": 明文.hex(),
                "密钥": 密钥.hex(),
                "密文": ref.encrypt(明文, 密钥).hex(),
                "解密结果": ref.decrypt(ref.encrypt(明文, 密钥), 密钥).hex(),
            }
        )

    目标 = Path(__file__).parent / "fixtures" / "xxtea_vectors.json"
    目标.parent.mkdir(parents=True, exist_ok=True)
    目标.write_text(json.dumps(向量, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {len(向量)} 个向量到 {目标}")

    # 自检：每个向量的解密结果必须等于明文
    for v in 向量:
        assert v["解密结果"] == v["明文"], f"参考实现自身往返失败：{v['名称']}"
    print("参考实现往返自检通过")


if __name__ == "__main__":
    main()
