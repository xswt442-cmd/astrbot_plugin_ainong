"""微信出码的真实验证。

走到二维码出来为止，不需要人扫码。出码成功说明签名正确、
AppID 有效、SDK 票据拿到手。轮询与营地登录要人参与，另行验证。
"""

import asyncio
import json
import sys
import uuid

import aiohttp

sys.path.insert(0, ".")

from ainong.auth.wechat import (
    WECHAT_POLL_URL,
    WECHAT_QR_URL,
    build_poll_query,
    build_qr_query,
    解析出码响应,
    解析扫码状态,
)
from ainong.camp.transport import _公共头, 营地网关

SDK票据接口 = f"{营地网关}/a/getwxsdkticket"


async def main() -> int:
    日志标识 = str(uuid.uuid4()).upper()

    头 = dict(_公共头)
    头["x-log-uid"] = 日志标识

    async with aiohttp.ClientSession() as 会话:
        # 第一步：取 SDK 票据。签名不同，这一步用的是微信的 SHA-1 规则。
        async with 会话.post(SDK票据接口, headers=头) as 响应:
            载荷 = json.loads(await 响应.text())

        print(f"[票据] returnCode={载荷.get('returnCode')}")
        if 载荷.get("returnCode") != 0:
            print(f"  完整响应：{json.dumps(载荷, ensure_ascii=False)[:300]}")
            return 1
        票据 = str((载荷.get("data") or {}).get("sdkTicket") or "")
        print(f"  拿到票据，长度 {len(票据)}（内容不打印）")
        if not 票据:
            return 1

        # 第二步：用票据换二维码。
        查询 = build_qr_query(票据)
        async with 会话.get(WECHAT_QR_URL, params=查询) as 响应:
            出码载荷 = json.loads(await 响应.text())

        print(f"\n[出码] errcode={出码载荷.get('errcode')}")
        if 出码载荷.get("errcode") != 0:
            print(f"  完整响应：{json.dumps(出码载荷, ensure_ascii=False)[:300]}")
            return 1

        结果 = 解析出码响应(出码载荷)
        print(f"  uuid={结果['uuid']}")
        print(f"  二维码长度={len(结果['二维码'])} base64 字符")
        print(f"  图片类型={结果['图片类型']}")

        # 第三步：轮询一次，确认签名与 uuid 有效（此时应返回等待扫码）。
        async with 会话.get(WECHAT_POLL_URL, params=build_poll_query(结果["uuid"])) as 响应:
            轮询载荷 = json.loads(await 响应.text())

        状态 = 解析扫码状态(轮询载荷)
        print(f"\n[轮询] wx_errcode={轮询载荷.get('wx_errcode')}")
        print(f"  解析状态={状态['状态']} 终态={状态['终态']}")
        print(f"  原始响应：{json.dumps(轮询载荷, ensure_ascii=False)[:200]}")

        if 状态["状态"] == "等待":
            print("\n结论：签名正确，出码与轮询链路可用。二维码在等待扫码。")
            return 0
        print(f"\n结论：链路返回了 {状态['状态']}，需要检查。")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
