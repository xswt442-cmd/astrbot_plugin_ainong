# Agent guide

`ainong`：通过王者营地接口读取玩家战绩，交给模型。

文档规范见 [.github/engineering/STANDARD.md](.github/engineering/STANDARD.md)。

## 约定

- 包内一律相对导入。插件目录被 AstrBot 当作包加载，顶层包名在容器里 import 不到。
- 指令全在 `爱农` 组下（`/爱农 战绩`），不占通用名。改动指令时提示文本中的示例同步修改。
- `requirements.txt` **手写**：AstrBot 用 pip 安装它，而同一环境里已有 AstrBot 核心依赖并带版本护栏；`uv export` 会钉成 `==`，与护栏冲突导致安装失败。加依赖时 `pyproject.toml` 与它同步修改，`test/test_requirements.py` 校验。
- 仅验证脚本需要的依赖放入 `[dependency-groups] qq-verify`。缺失时插件仍可加载，只是无法提供 QQ 扫码。
- 网络请求只用 `aiohttp`。
- 数据落在 `data/plugin_data/ainong/`，不写插件目录。
- 凭据不进日志、不进异常消息、不进提交。解绑时删除文件。
- `__init__` 的 `config` 必须是可省参数（`AstrBotConfig | None = None`）。AstrBot 只在读到配置项时传入，声明为必需参数会使插件无法加载。
- 图标必须是根目录 `logo.png`，文件名与位置由 AstrBot 硬编码（`star_manager.py` 的 `logo_fname`）。WebUI 通过 300 秒有效的文件 token 拉图，体积过大会反复重传。改图标改 `logo.png`，不另建目录。

## 结构

- `main.py` — 插件入口：指令组、指令、落空兜底
- `ainong/crypto/` — XXTEA、PKCS#1 块解析
- `ainong/auth/` — YSDK 签名、微信与 QQ 扫码、浏览器会话
- `ainong/camp/` — 营地接口：传输层、频控、战绩
- `ainong/stats.py` — 战绩统计、文本汇总、PK 逐项对比
- `ainong/prompts.py` — 锐评、PK、开一局的提示词（独立成模块以便单测）
- `ainong/pk.py` — PK 对手标识解析
- `ainong/storage.py` — 凭据与绑定关系
- `ainong/兜底.py` — 指令落空的判据与提示
- `ainong/日志.py` — 供不 import astrbot 的模块使用的日志出口
- `ainong/verify/` — 可行性验证脚本，不参与运行
- `test/` — pytest 用例与真实响应快照
- `deploy/` — 浏览器服务的 compose 片段、Dockerfile、seccomp 配置
- `docs/` — 更新日志与发版说明

## 源码级约束

`main.py` 顶层 import astrbot，本地无此包，无法单测，以下约束由 `test/test_main_wiring.py` 做源码检查：

- **`_通知` 必须在 `_清理会话` 之前。** 通知依赖 `_事件` 与 `_会话标识`，清理会 pop 两者。
- **扫码回调只能是单参协程。** `等授权码` 以 `完成(授权码)` 调用；用户标识用闭包绑定。
- **QQ 回调必须 await 换票，且不能写 `self._完成`。** `_完成` 是 `_绑定` 内的局部函数，`self._完成` 抛 AttributeError；`换取平台凭据` 是协程函数，不 await 会把协程对象当作凭据传递。两者都在扫码成功后触发，表现为「扫描完成但绑定失败」。
- **缺失 f 前缀的字符串、except 中读取 try 体内变量**同由源码检查覆盖：两种写法语法合法，运行时才失败。

## 指令落空要自己接住

`/爱农 <未匹配子命令的内容>` 时 `CommandGroupFilter.filter` 的 `startswith` 返回 False，指令被跳过，消息进模型，模型会自行作答。

指令组挂 `_落空兜底`（`CustomFilter`）：仅在落空时 `set_result` + `stop_event`。判据在 `ainong/兜底.是否落空`，**必须与 `CommandGroupFilter.startswith` 一致（字面前缀匹配）**，否则会拦截正常指令。

`ainong/兜底.子命令名` 是手抄的别名清单，改动 `main.py` 的指令或别名时同步修改，`test_main_wiring.py` 核对。

`.filter` 返回值的语义是「本组是否处理这条消息」，不是「是否命中」，**所有出口必须 `return True`**：写成「命中返回 False」会使整个指令组失效。

组名另挂 `_组别名 = {f"/{_组名}"}`：QQ 官方的 At 唤醒分支不剥 `message_str` 里的 `/`，缺少该别名时 `@机器人 /爱农 战绩` 无响应。

## 战绩字段语义

列表接口（`/game/morebattlelist`，`apiVersion: 5`）的字段语义已用真实响应逐条核实，不按字段名推断：

| 字段 | 语义 | 备注 |
| --- | --- | --- |
| `gameresult` | 1 胜 / 2 负 | |
| `mvpcnt` | MVP（0/1） | 与 `mvpUrlV2` 中 mvp 图数量一致 |
| `losemvp` | 败方 MVP，即 SVP（0/1） | 没有名为 `svp` 的字段 |
| `firstBlood` / `godLikeCnt` / `hero1TripleKillCnt` / `hero1UltraKillCnt` | 一血 / 超神 / 三杀 / 四杀（0/1） | |
| `stars` | 段位星数 | 每场都带，最新一场为当前值 |
| `newMasterMatchScore` | 巅峰赛分 | 未打过巅峰赛的账号为初始分 1200，直接展示会把「未打过」表述为「1200 分」 |
| `evaluateUrl` | 奖牌图，形如 `…/evaluateV3/silver_archer.png` | 等级与职业在文件名中 |
| `desc` | 局内评价文案 | 实力局 / 翻车局 / 尽力局 / 躺赢局… |
| `AcntCamp` | 阵营（1/2，红蓝方） | 曾误判为「参团率」，线上出现「平均参团率 1.6%」 |
| `mapName` | 模式名（`排位赛 五排`） | |
| `usedTime` / `gradeGame` | 秒 / 评分（字符串） | |
| — | 经济 / 伤害 | 列表接口不返回，需另走 `battledetail` |

`stats.py` 用 `_可选数` 按候选键名取值。**取不到时返回 None，该项从汇总文本中消失**，不能填 0：0 是合法数据，「该项不存在」不是；混淆后模型会把「无此字段」读作「该值为 0」并据此输出结论。

新增统计维度时，测试须包含「字段缺失时该项不出现在文本中」。

## 日志只能从 astrbot.api 取

插件规范要求 `logger` 只能从 `astrbot.api` 导入，**禁止使用 Python 内置 `logging`**。v0.1.14 上架审核因此被驳回：`ainong/auth/scan_session.py` 在模块顶层 `import logging`，`qq_login.py` 在异常处理中重复引入，两者都在发布包内，只检查 `main.py` 发现不了。

`ainong/auth/` 与 `ainong/camp/` 不 import astrbot（本地 pytest 需要直接运行），日志走 `ainong/日志.py`：`main.py` 在 `__init__` 中 `挂日志(lambda 级别, 一句: getattr(logger, 级别)(f"[ainong] {一句}"))`，模块内用 `记("warning", "……")`。`aiva/transport.py` 是同一做法。

约束由 `test_main_wiring.py` 的 `Test日志出口` 扫描整个包校验。

## 有无数据靠返回值判断

`_读战绩` 与 `_读战绩与统计` 返回 `(文本, 统计字典)`，无可用数据时统计字典为 `None`，调用方据此决定是否继续。

**不改为按文本前缀判断。** 角色没有可查近期战绩时，`汇总文本` 返回「这个角色还没有可查的近期战绩。」，既不以「还没绑定」也不以「读取战绩失败」开头。作为数据输入锐评后，提示要求「全文至少出现 3 个具体数字」，模型只能虚构。

## PK：对手靠名字定位，对比由代码计算

**QQ 官方平台拿不到被 @ 者的标识。** 实测被 @ 者不出现在组件中，正文也没有 `<@!id>`：`qqofficial_platform_adapter` 只把「@机器人」转成 `At`，引用消息只构造 `Reply(id=消息ID)`，不带作者。定位顺序为 ① `@` 组件 → ② 正文 `<@!id>` → ③ PK 名字（`凭据仓库.按昵称找`），前两步在 `ainong/pk.py`。

名字默认取绑定时的 `get_sender_name()`，QQ 官方返回的是 QQ 昵称而非群昵称，因此提供 `/爱农 昵称` 供用户修改。记录额外存 `用户` 字段——文件名是标识的哈希，无法反推。按名字只能查到**记录**而非标识，查询对手战绩走 `_读战绩与统计`。

**逐项对比由代码计算，模型只做解说。** 不把两份数据交给模型自行比较：实测输出「83 对 87」与一段双方都不否定的评价——比较是模糊任务，模型倾向于给出不得罪双方的答案。分工：

- `stats.对比要点` 逐项计算高低（胜率／KDA／平均评分／MVP 次数／场均击杀／场均死亡／最近 10 场胜场），返回带 `优` 字段的结构；**场均死亡越小越好**；一方无场次时返回空。
- `stats.对比文本` / `占优项数` 折成文字随提示交给模型。**项数只陈述事实，不推导「占优项多者更强」**——强弱取决于哪几项占优，判断交给模型。
- `prompts.端水词` 是显式禁用词表；列词表比写「不要端水」有效。

锐评同理：称号须带段位或招牌英雄，正文至少 3 个具体数字，「问题」段落必须落到具体一项。改动提示词时同步修改 `test_prompts.py`。

## 微信与 QQ 扫码的差别

两条路径都是「出码 → 推给用户 → 后台等待 → 换凭据 → 登录营地」，差异如下：

| | 微信 | QQ |
| --- | --- | --- |
| 出码 | 纯 HTTP | 需要浏览器侧车 |
| 码的有效期 | 约五分钟 | 约两分钟 |
| 换码 | 不需要 | 当前码**用满有效期**才换，每次换码都需推送给用户 |
| 营地登录参数 | `微信授权码=...` | `平台凭据={...}` |

「用满有效期才换」是实测结论：等待协程原在每次循环开始时换页取图，而出码时已推送一张给用户，用户会连续收到两张，且换页会使第一张失效，扫描第一张必然失败。

两条路径的客户端版本号不同，营地按参数区分来源，**传错参数会被服务端拒绝**。`_收到授权码` 按入参类型分流，不统一包装成平台凭据。

`playwright` 只在 `qq-verify` 依赖组中，因此 `ainong/auth/browser.py` 的 playwright import 必须留在 `浏览器会话.__aenter__` 内：放在模块顶层时，未安装 playwright 的环境加载插件即崩溃，微信路径也不可用。

## 验证

```sh
uv run pytest                    # 测试
uv run ruff check .              # lint
uv run ruff format --check .     # 格式
```

测试只覆盖不需要凭据、不发网络请求的纯逻辑。营地接口需要登录态且有频控，不做自动化测试，链路验证用 `ainong/verify/` 下的脚本。

真实响应存于 `test/fixtures/` 作快照，不用 mock 构造数据。改动协议相关代码后，先重新录制快照再改实现：接口改版时参照旧快照容易把错误当作新行为。
