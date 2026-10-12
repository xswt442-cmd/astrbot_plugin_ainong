"""爱农：王者营地战绩查询。

用户绑定自己的营地账号后，指令与模型都能读到他自己的战绩数据。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.event.filter import command_group, llm_tool
from astrbot.api.star import Context, Star
from astrbot.core.message.message_event_result import MessageEventResult
from astrbot.core.star.filter.command import GreedyStr

# 全部在模块顶层导入。插件加载时就把整个包摸清：少文件、依赖缺失都在启动
# 阶段报错，而不是等用户发了指令才在懒加载里抛模块不存在。
from .ainong.auth.qq_login import QQ扫码会话, 换取平台凭据
from .ainong.auth.scan_session import 扫码会话
from .ainong.camp.battles import 读战绩摘要
from .ainong.camp.transport import 营地传输
from .ainong.storage import 凭据仓库

_帮助文本 = """爱农 · 王者营地战绩

/爱农 绑定微信
  微信扫码绑定你自己的营地账号。纯 HTTP，不需要浏览器。

/爱农 绑定QQ
  手机 QQ 扫码绑定。码两分钟就过期，我会在过期前发新的，以最后一张为准。
  需要浏览器侧车（在服务器上单独跑着 Chromium）。

/爱农 角色 [角色ID]
  不带参数：列出这个营地账号下的游戏角色，标出当前选中的。
  带角色ID：切换到该角色，之后的查询都看它。

/爱农 战绩
  当前角色的近期战绩摘要：胜率、KDA、模式分布、英雄池、MVP 与连败。

/爱农 锐评
  让模型基于上面的数据写一段评价，指出打得好的地方和明显的问题。

/爱农 解绑
  解除绑定并立即删除本地凭据。扫码卡住时也可以用它清掉当前会话。

/爱农 状态
  看自己的标识、绑定情况和有没有卡住的扫码会话。排查用。

/爱农 帮助
  就是这条。

直接问模型「我的王者战绩怎么样」也会走同一套数据。"""


class Main(Star):
    @command_group("爱农")
    def 爱农(self):
        """王者营地战绩查询。指令都在这个组下，不占用通用名字。"""

    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self._凭据 = 凭据仓库(self._数据目录())
        # 两种授权的会话都放这儿：微信的纯 HTTP，QQ 的要浏览器。用基线类型标注，
        # 两者都实现出码/开始等待/关闭。
        self._扫码会话: dict[str, 扫码会话 | QQ扫码会话] = {}
        # 留着原始事件，扫码完成后用它回复。QQ 官方 bot 的主动消息要群授权、
        # 每条还消耗额度（日志里是「主动消息失败, 无权限」），而带 msg_id 的
        # 被动回复不需要。两者用时不同，所以事件和会话标识都留着。
        self._事件: dict[str, AstrMessageEvent] = {}
        self._会话标识: dict[str, str] = {}

    def _数据目录(self) -> Path:
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path

        return Path(get_astrbot_data_path()) / "plugin_data" / "ainong"

    def _扫码超时(self) -> int:
        return int(self.config.get("browser_timeout_seconds", 180) or 180)

    async def terminate(self) -> None:
        for 会话 in list(self._扫码会话.values()):
            await 会话.关闭()
        self._扫码会话.clear()
        self._事件.clear()
        self._会话标识.clear()

    # ---------------------------------------------------------------- 绑定

    @爱农.command("帮助", alias={"help", "菜单"})
    async def 帮助(self, event: AstrMessageEvent):
        """列出所有指令。"""
        yield event.plain_result(_帮助文本)

    @爱农.command("绑定微信", alias={"绑定"})
    async def 绑定微信(self, event: AstrMessageEvent):
        """扫码绑定王者营地账号，走微信授权。"""
        async for 结果 in self._绑定(event, 平台="微信"):
            yield 结果

    @爱农.command("绑定QQ", alias={"绑定qq"})
    async def 绑定QQ(self, event: AstrMessageEvent):
        """扫码绑定王者营地账号，走 QQ 授权。需要浏览器侧车。"""
        async for 结果 in self._绑定(event, 平台="QQ"):
            yield 结果

    async def _绑定(self, event: AstrMessageEvent, 平台: str):
        """两种授权的公共流程。差异只在出码与等待，各自在下面分支。"""
        用户 = event.get_sender_id()
        if not 用户:
            yield event.plain_result("拿不到你的用户标识，无法绑定。")
            return

        已有 = self._凭据.读取(用户)
        if 已有:
            yield event.plain_result(
                f"你已经绑定了营地账号 {已有['营地ID']}。要换号先用 /爱农 解绑。"
            )
            return

        if 用户 in self._扫码会话:
            yield event.plain_result(
                f"{平台}扫码已经在进行中，看上一条消息里的二维码。"
                "如果那张码已经失效，发 /爱农 解绑 清掉当前会话后重试。"
            )
            return

        # 两种回话方式要用的东西不一样：event 走被动回复（带 msg_id，不需要
        # 主动消息权限），会话标识走主动消息兜底。
        self._事件[用户] = event
        self._会话标识[用户] = event.unified_msg_origin

        if 平台 == "QQ":
            会话 = QQ扫码会话(self._侧车地址(), self._扫码超时())
            try:
                图片 = await 会话.出码()
            except Exception as exc:
                await 会话.关闭()
                await self._清理会话(用户, None)
                yield event.plain_result(f"QQ 扫码启动失败：{exc}")
                return

            self._扫码会话[用户] = 会话
            提示 = (
                "用手机 QQ 扫这个码。这张码很快会过期，我会在过期前发新的，"
                "以最后一张为准。\n扫完我自动回你结果，没反应就发 /爱农 状态。"
            )
        else:
            会话 = 扫码会话(self._扫码超时())
            try:
                图片 = await 会话.出码()
            except Exception as exc:
                await 会话.关闭()
                await self._清理会话(用户, None)
                yield event.plain_result(f"取二维码失败：{exc}")
                return

            self._扫码会话[用户] = 会话
            提示 = (
                "用微信扫这个码，扫完等一会儿。\n"
                "扫完我会自动回你结果；如果一直没反应，发 /爱农 状态 查一下。"
            )

        # 回调只收授权码，用户标识在这里绑掉。原来直接把 _收到授权码 传进去，
        # 而它要 (用户, 授权码) 两个参数，等授权码只传一个，调用即 TypeError；
        # 后台 task 崩了没人收，用户看到"扫码已登上"却没绑定成功，日志里只有
        # 一行 Traceback。绑成零参在这里，出错也由下面的兜底通知用户。
        async def _完成(平台凭据: dict[str, str] | str) -> None:
            await self._收到授权码(用户, 平台凭据)

        if 平台 == "QQ":
            会话.开始等待(
                lambda code: self._完成(换取平台凭据(code)),
                self._换码通知(用户),
                self._扫码失败(用户, 平台),
            )
        else:
            会话.开始等待(_完成, self._扫码失败(用户, 平台))

        # 用链式接口而不是 event.chain_result([...])：后者要的是消息组件列表，
        # 塞裸字符串进去，发送前的日志环节会 AttributeError 崩掉整条流水线，
        # 用户那边只看到没反应。组件由这里的接口负责转换。
        yield event.plain_result(提示).base64_image(图片)

    def _侧车地址(self) -> str:
        """浏览器侧车的地址。QQ 扫码要靠它，微信那条不需要。"""
        return str(self.config.get("playwright_url", "") or "http://playwright:3000")

    def _换码通知(self, 用户: str) -> Callable[[str], Any]:
        """二维码换了就再推一张。QQ 的码两分钟就过期，用户手上那张会废掉。"""

        async def _通知(图片: str) -> None:
            await self._通知图片(用户, 图片, "刚才那张码过期了，用这张新的。")

        return _通知

    def _扫码失败(self, 用户: str, 平台: str = "") -> Callable[[BaseException], Any]:
        """后台等待出问题时清场并告知用户。

        原来这类异常只是让 task 静默崩掉：不清理 _扫码会话，用户再发绑定
        只会一直看到"扫码已经在进行中"，而他其实什么都没在扫。
        """

        async def _处理(exc: BaseException) -> None:
            if isinstance(exc, asyncio.CancelledError):
                raise exc
            logger.warning(f"[ainong] 扫码等待失败：{type(exc).__name__}: {exc}")
            # 先通知再清理：_通知 依赖 _事件 与 _会话标识，清理会把它们丢掉。
            await self._通知(用户, f"{平台}扫码没走完：{exc}\n发 /爱农 状态 可以随时查进度。")
            await self._清理会话(用户, 会话=self._扫码会话.pop(用户, None))

        return _处理

    async def _收到授权码(self, 用户: str, 授权: dict[str, str] | str) -> None:
        """扫码完成后登录营地并存凭据。

        `授权` 有两种形态：微信给的是授权码字符串，走 `微信授权码` 参数；
        QQ 那条已经换好了平台凭据，走 `平台凭据`。营地按这两条路径用不同的
        客户端版本号，不能混——传错会被服务端拒。
        """
        会话 = self._扫码会话.pop(用户, None)
        if 会话 is None:
            return

        try:
            传输 = 营地传输()
            try:
                if isinstance(授权, str):
                    账号 = await 传输.登录(微信授权码=授权)
                else:
                    账号 = await 传输.登录(平台凭据=授权)
            finally:
                await 传输.关闭()

            self._凭据.写入(用户, 账号)
            logger.info(f"[ainong] 用户绑定营地账号 {账号['营地ID']}")
            await self._通知(用户, f"绑定成功，营地账号 {账号['营地ID']}。发 /爱农 战绩 试试。")
        except Exception as exc:
            logger.warning(f"[ainong] 绑定失败：{type(exc).__name__}: {exc}")
            await self._通知(用户, f"绑定失败：{exc}")
        finally:
            await self._清理会话(用户, 会话)

    async def _清理会话(self, 用户: str, 会话: 扫码会话 | QQ扫码会话 | None) -> None:
        """关掉会话、丢掉事件与会话标识。

        三样都要丢。事件持有平台侧的上下文，留着既可能让通知发到上一轮的
        会话里去，也长期占着平台对象不放。
        """
        self._事件.pop(用户, None)
        self._会话标识.pop(用户, None)
        if 会话 is not None:
            await 会话.关闭()

    async def _通知(self, 用户: str, 文本: str) -> None:
        """扫码完成后告诉用户结果。

        两条路，按可靠性排：

        1. 用原始事件回复。带 msg_id 走的是被动回复，不需要主动消息权限。
           QQ 官方 bot 在群里的主动消息要群授权、每条还消耗额度，实测报
           「主动消息失败, 无权限」（40034105），所以这条路必须先试。
           代价是有时效——扫码久了 msg_id 就失效了。
        2. 用会话标识主动发。作为兜底，但在群里同样可能被拒。

        两条都不通时只记日志。用户可以发 /爱农 状态 自己查。
        """
        from astrbot.api.message_components import Plain
        from astrbot.core.message.message_event_result import MessageChain

        await self._发消息(用户, MessageChain(chain=[Plain(文本)]))

    async def _通知图片(self, 用户: str, 图片: str, 文本: str) -> None:
        """推一张新二维码。QQ 的码两分钟就过期，换码必须真的发出去。"""
        结果 = MessageEventResult().message(文本).base64_image(图片)
        await self._发消息(用户, 结果)

    async def _发消息(self, 用户: str, 消息: Any) -> None:
        """按可靠性依次尝试被动回复与主动发送，见 `_通知` 的说明。"""
        事件 = self._事件.get(用户)
        if 事件 is not None:
            try:
                await 事件.send(消息)
                return
            except Exception as exc:
                logger.info(f"[ainong] 被动回复失败，试主动发送：{type(exc).__name__}: {exc}")

        会话标识 = self._会话标识.get(用户)
        if not 会话标识:
            return
        try:
            await self.context.send_message(会话标识, 消息)
        except Exception as exc:
            logger.warning(f"[ainong] 主动通知用户失败：{type(exc).__name__}: {exc}")

    @爱农.command("解绑")
    async def 解绑(self, event: AstrMessageEvent):
        """解除绑定并删除凭据。"""
        用户 = event.get_sender_id()
        await self._清理会话(用户, self._扫码会话.pop(用户, None))

        记录 = self._凭据.删除(用户)
        if not 记录:
            yield event.plain_result("你还没有绑定营地账号。")
            return
        yield event.plain_result(f"已解绑，凭据已删除（营地账号 {记录['营地ID']}）。")

    @爱农.command("状态", alias={"status"})
    async def 状态(self, event: AstrMessageEvent):
        """看当前绑定与扫码会话的情况。排查用。"""
        用户 = event.get_sender_id()
        记录 = self._凭据.读取(用户)

        行 = [f"你的标识：{用户 or '（拿不到）'}"]
        if 记录:
            行.append(
                f"已绑定营地账号 {记录['营地ID']}，"
                f"当前角色 {记录.get('角色ID') or '（未选择，用 /爱农 角色 选）'}"
            )
        else:
            行.append("未绑定营地账号")

        if 用户 in self._扫码会话:
            行.append("有一个扫码会话在进行中。卡住的话发 /爱农 解绑 清掉它。")

        yield event.plain_result("\n".join(行))

    # ---------------------------------------------------------------- 查询

    @爱农.command("角色")
    async def 角色(self, event: AstrMessageEvent, 角色ID: GreedyStr):
        """列出该营地账号下的游戏角色。不带参数时只列出，带角色ID则切换到它。"""
        用户 = event.get_sender_id()
        记录 = self._凭据.读取(用户)
        if not 记录:
            yield event.plain_result("还没绑定营地账号，先发 /爱农 绑定。")
            return

        参数 = str(角色ID).strip()

        async with 营地传输() as 传输:
            传输.绑定账号(**{k: 记录[k] for k in ("营地ID", "令牌", "对称密钥")})
            try:
                列表 = await 传输.取角色列表()
            except Exception as exc:
                yield event.plain_result(f"取角色列表失败：{exc}")
                return

        if not 列表:
            yield event.plain_result("这个营地账号下没有游戏角色。")
            return

        if not 参数:
            当前 = self._凭据.当前角色(用户)
            行 = [
                f"{'（当前）' if 角色['角色ID'] == 当前 else ''}{角色['名称']}"
                f"｜{角色['区服描述']}｜{角色['角色ID']}"
                for 角色 in 列表
            ]
            yield event.plain_result(
                "游戏角色：\n" + "\n".join(行) + "\n\n发 /爱农 角色 <角色ID> 切换。"
            )
            return

        匹配 = next((角色 for 角色 in 列表 if 角色["角色ID"] == 参数), None)
        if 匹配 is None:
            可用 = "、".join(角色["角色ID"] for 角色 in 列表)
            yield event.plain_result(f"没有这个角色。可选：{可用}")
            return

        self._凭据.选角色(用户, 匹配["角色ID"])
        yield event.plain_result(
            f"已切到{匹配['名称']}（{匹配['区服描述']}）。发 /爱农 战绩 看这个角色的数据。"
        )

    @爱农.command("战绩")
    async def 战绩(self, event: AstrMessageEvent):
        """当前角色的近期战绩摘要。"""
        文本 = await self._读战绩(event.get_sender_id())
        yield event.plain_result(文本)

    @llm_tool(name="get_king_of_glory_profile")
    async def 查询玩家画像(self, event: AstrMessageEvent) -> str:
        """读取提问者自己绑定的王者荣耀账号战绩，并给出结构化摘要。

        Returns:
            段位、常用英雄与位置、近期胜率与评分等统计结果。玩家关闭了
            战绩展示时返回说明文字。
        """
        return await self._读战绩(event.get_sender_id())

    @爱农.command("锐评")
    async def 锐评(self, event: AstrMessageEvent):
        """让模型基于近期战绩给一段评价。"""
        数据 = await self._读战绩(event.get_sender_id())
        if 数据.startswith(("还没绑定", "提问者还没有", "读取战绩失败")):
            yield event.plain_result(数据)
            return

        try:
            提供方 = await self.context.get_current_chat_provider_id(event.unified_msg_origin)
        except Exception as exc:
            yield event.plain_result(f"取不到当前对话用的模型：{exc}")
            return

        提示 = (
            "下面是这个玩家的王者荣耀近期战绩统计。"
            "请基于这些数据写一段有话说的锐评：先说数据说明了什么，"
            "再指出打得好的地方和明显的问题，最后给一条能改进的具体建议。"
            "语气直接，不要客套，不要复述数据原文，控制在 200 字以内。\n\n"
            f"{数据}"
        )

        try:
            结果 = await self.context.tool_loop_agent(
                event=event,
                chat_provider_id=提供方,
                prompt=提示,
                max_steps=8,
            )
        except Exception as exc:
            logger.warning(f"[ainong] 锐评失败：{type(exc).__name__}: {exc}")
            yield event.plain_result(f"锐评失败：{exc}")
            return

        yield event.plain_result(结果.completion_text or "模型没有返回内容。")

    async def _读战绩(self, 用户: str) -> str:
        记录 = self._凭据.读取(用户)
        if not 记录:
            return "提问者还没有绑定王者营地账号，无法查询战绩。"

        async with 营地传输() as 传输:
            传输.绑定账号(**{k: 记录[k] for k in ("营地ID", "令牌", "对称密钥")})
            try:
                return await 读战绩摘要(传输, 记录.get("角色ID") or "")
            except Exception as exc:
                logger.warning(f"[ainong] 读战绩失败：{type(exc).__name__}: {exc}")
                return f"读取战绩失败：{exc}"
