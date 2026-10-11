"""A/B 对照：签名正确与签名错误时，服务端返回是否不同。

如果两者返回相同，说明服务端没有实际验签，这个测试就没有意义；
只有两者不同，才能证明签名构造真的被服务端校验。
"""

import asyncio
import json
import sys
import time

import aiohttp

sys.path.insert(0, ".")

from ainong.auth.ysdk import YSDK_URL, build_auth_headers

BODY = json.dumps(
    {"appID": "1105200115", "loginCode": "invalid-code-for-signature-check"},
    separators=(",", ":"),
)


async def 发送(session: aiohttp.ClientSession, headers: dict[str, str]) -> tuple[int, str]:
    async with session.post(YSDK_URL, headers=headers, data=BODY.encode("utf-8")) as resp:
        return resp.status, await resp.text()


async def main() -> int:
    timestamp = str(int(time.time()))
    正确头 = build_auth_headers(BODY, timestamp)

    错误头 = dict(正确头)
    错误头["Auth-Secret-Digest"] = "AAAAAAAAAAAAAAAAAAAAAAAAAAAA"

    # 时间戳改成别的值，签名随之为另一串，也应被拒
    错时间头 = dict(正确头)
    错时间头["Auth-Request-Time"] = str(int(time.time()) - 3600)

    async with aiohttp.ClientSession() as session:
        正确状态, 正确响应 = await 发送(session, 正确头)
        错误状态, 错误响应 = await 发送(session, 错误头)
        错时间状态, 错时间响应 = await 发送(session, 错时间头)

    print(f"签名正确      HTTP {正确状态}  {正确响应[:200]}")
    print(f"摘要篡改      HTTP {错误状态}  {错误响应[:200]}")
    print(f"时间戳错配    HTTP {错时间状态}  {错时间响应[:200]}")

    三者互不相同 = len({正确响应, 错误响应, 错时间响应}) == 3
    if 三者互不相同:
        print("\n结论：三种情况的响应各不相同，服务端确实在验签。签名构造正确。")
        return 0
    if 正确响应 != 错误响应:
        print("\n结论：签名正确与摘要篡改的响应不同，服务端在验签。")
        return 0
    print("\n结论：响应相同，无法证明服务端验签通过。这个验证没有得出结论。")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
