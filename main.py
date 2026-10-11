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
from astrbot.core.star.filter.command import GreedyStr

# 全部在模块顶层导入。插件加载时就把整个包摸清：少文件、依赖缺失都在启动
# 阶段报错，而不是等用户发了指令才在懒加载里抛模块不存在。
from .ainong.auth.wechat_flow import 微信出码会话
from .ainong.camp.battles import 读战绩摘要
from .ainong.camp.transport import 营地传输
from .ainong.storage import 凭据仓库

_帮助文本 = """爱农 · 王者营地战绩

/爱农 绑定
  微信扫码绑定你自己的营地账号，出二维码后用微信扫。
  一个 Bot 用户对应一个营地账号，账号下的多个游戏角色可以切换。

/爱农 角色 [角色ID]
  不带参数：列出这个营地账号下的游戏角色，标出当前选中的。
  带角色ID：切换到该角色，之后的查询都看它。

/爱农 战绩
  当前角色的近期战绩摘要：胜率、KDA、模式分布、英雄池、MVP 与连败。

/爱农 锐评
  让模型基于上面的数据写一段评价，指出打得好的地方和明显的问题。

/爱农 解绑
  解除绑定并立即删除本地凭据。

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
        self._扫码会话: dict[str, _扫码] = {}
        # 主动发消息定位会话要的是会话标识，与用户标识不是一回事。
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
        self._会话标识.clear()

    # ---------------------------------------------------------------- 绑定

    @爱农.command("帮助", alias={"help", "菜单"})
    async def 帮助(self, event: AstrMessageEvent):
        """列出所有指令。"""
        yield event.plain_result(_帮助文本)

    @爱农.command("绑定")
    async def 绑定(self, event: AstrMessageEvent):
        """扫码绑定王者营地账号。"""
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
            yield event.plain_result("扫码已经在进行中，看上一条消息里的二维码。")
            return

        会话 = _扫码(self._扫码超时())
        try:
            图片 = await 会话.出码()
        except Exception as exc:
            await 会话.关闭()
            yield event.plain_result(f"取二维码失败：{exc}")
            return

        self._扫码会话[用户] = 会话
        # 主动发消息要的是会话标识，不是用户标识，两者不能混。
        self._会话标识[用户] = event.unified_msg_origin
        会话.开始等待(self._收到授权码)

        from astrbot.api.message_components import Image

        yield event.chain_result([Image.fromBase64(图片), "用微信扫这个码。"])

    async def _收到授权码(self, 用户: str, 授权码: str) -> None:
        """扫码完成后登录营地并存凭据。"""
        会话 = self._扫码会话.pop(用户, None)
        if 会话 is None:
            return

        try:
            传输 = 营地传输()
            try:
                账号 = await 传输.登录(微信授权码=授权码)
            finally:
                await 传输.关闭()

            self._凭据.写入(用户, 账号)
            logger.info(f"[ainong] 用户绑定营地账号 {账号['营地ID']}")
            await self._通知(用户, f"绑定成功，营地账号 {账号['营地ID']}。发 /爱农 战绩 试试。")
        except Exception as exc:
            logger.warning(f"[ainong] 绑定失败：{type(exc).__name__}: {exc}")
            await self._通知(用户, f"绑定失败：{exc}")
        finally:
            self._会话标识.pop(用户, None)
            await 会话.关闭()

    async def _通知(self, 用户: str, 文本: str) -> None:
        """给用户发一条消息。用绑定时记下的会话标识定位会话。"""
        会话标识 = self._会话标识.get(用户)
        if not 会话标识:
            return
        try:
            from astrbot.api.message_components import Plain
            from astrbot.core.message.message_event_result import MessageChain

            await self.context.send_message(会话标识, MessageChain(chain=[Plain(文本)]))
        except Exception as exc:
            logger.warning(f"[ainong] 通知用户失败：{type(exc).__name__}: {exc}")

    @爱农.command("解绑")
    async def 解绑(self, event: AstrMessageEvent):
        """解除绑定并删除凭据。"""
        用户 = event.get_sender_id()
        会话 = self._扫码会话.pop(用户, None)
        if 会话 is not None:
            await 会话.关闭()
        self._会话标识.pop(用户, None)

        记录 = self._凭据.删除(用户)
        if not 记录:
            yield event.plain_result("你还没有绑定营地账号。")
            return
        yield event.plain_result(f"已解绑，凭据已删除（营地账号 {记录['营地ID']}）。")

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


class _扫码:
    """一次扫码绑定会话。

    微信出码是纯 HTTP，不需要浏览器：先给用户二维码，再在后台轮询等授权码。
    出码与等待分成两步，二维码才能立刻发出去。
    """

    def __init__(self, 超时秒: int) -> None:
        self._超时 = 超时秒
        self._会话: Any = None
        self._待等: asyncio.Task | None = None

    async def 出码(self) -> str:
        """出二维码，立刻返回 base64 图片。"""
        self._会话 = 微信出码会话()
        return await self._会话.出码()

    def 开始等待(self, 完成: Callable[[str], Any]) -> None:
        """后台等扫码完成，拿到授权码后回调。"""
        self._待等 = asyncio.create_task(self._会话.等授权码(self._超时, 完成))

    async def 关闭(self) -> None:
        if self._待等 is not None:
            self._待等.cancel()
        if self._会话 is not None:
            await self._会话.关闭()
