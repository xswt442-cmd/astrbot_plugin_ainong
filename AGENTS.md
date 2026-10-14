# Agent guide

`ainong` 是 AstrBot 插件，通过王者营地接口读取玩家战绩，交给模型。

## 约定

- 包内一律用相对导入。插件目录被 AstrBot 当成包加载，顶层包名在容器里
  import 不到。
- 指令全在 `爱农` 指令组下（`/爱农 战绩`），不占用通用名字。改动指令时
  提示文本里的示例要一起改。
- `requirements.txt` **手写**：AstrBot 装插件时把它喂给 pip，而 pip 装的同一环境里
  就有 AstrBot 核心自己的依赖，核心给这些包加了版本护栏。`uv export` 会把包钉成
  `==`，正好撞上护栏，安装整体失败。理由与检查项见 `docs/RELEASING.md`，
  约束由 `test/test_requirements.py` 钉住。加依赖时 `pyproject.toml` 与它一起改。
- 只有验证脚本需要的依赖放进 `[dependency-groups] qq-verify`。缺它插件仍能加载，
  只是提供不了 QQ 扫码。
- 网络请求只用 `aiohttp`。
- 持久化数据放 AstrBot 的 `data/plugin_data/ainong/`，不放插件目录。
- 凭据不写日志、不进异常消息、不进提交。解绑时删文件，不保留。
- `__init__` 的 `config` 必须是可省参数（`AstrBotConfig | None = None`）。AstrBot 只在
  读到配置项时才把它传进来，声明成必需参数会让插件整个加载不起来。
- 插件图标必须是根目录的 `logo.png`，文件名与位置都是 AstrBot 硬编码的
  （`star_manager.py` 里的 `logo_fname`）。WebUI 通过一个 300 秒有效的文件
  token 拉图，所以体积要小——超过几百 KB 每次刷新都会重传。改图标时改
  `logo.png`，不要另建目录。

## 结构

```
main.py             插件入口，指令组、指令与落空兜底
ainong/crypto/       XXTEA、PKCS#1 块解析
ainong/auth/         YSDK 签名、微信与 QQ 扫码、浏览器会话
ainong/camp/         营地接口：传输层、频控、战绩
ainong/stats.py      战绩统计、文本汇总、PK 的逐项对比
ainong/prompts.py    锐评、PK 与开一局的提示词（放这儿是为了能跑单测）
ainong/pk.py         PK 对手标识的解析
ainong/storage.py    凭据与绑定关系
ainong/兜底.py       指令落空的判据与提示
ainong/日志.py       给不 import astrbot 的模块用的日志出口（见下）
ainong/verify/       可行性验证脚本，不参与运行
test/                pytest 用例与真实响应快照
deploy/              浏览器服务的 compose 片段、Dockerfile 与 seccomp 配置
docs/                更新日志与术语表
```

## 三条容易踩的约束

`main.py` 跑不了单测（顶层 import astrbot，本地没这个包），所以下面几条靠
`test/test_main_wiring.py` 做源码检查。

- **`_通知` 必须在 `_清理会话` 之前。** 通知依赖 `_事件` 与 `_会话标识`，
  清理会把两者 pop 掉。
- **扫码回调只能是单参协程。** `等授权码` 按 `完成(授权码)` 调用，回调要写成
  协程，用户标识用闭包绑掉。
- **QQ 的回调要把换票 await 掉，且不能写 `self._完成`。** `_完成` 是 `_绑定`
  里的局部函数，`self._完成` 直接 AttributeError；`换取平台凭据` 是协程函数，
  不 await 就把一个协程对象当凭据传下去。两者都在**扫码成功之后**才炸，
  用户看到的是「扫完了却绑不上」。
- **漏 f 前缀的字符串与 except 里读 try 体内的变量**也由源码检查钉住：
  两者语法都合法，只有运行时才炸。`test_main_wiring.py` 的 `Test源码卫生`。

## 指令落空要自己接住

`/爱农 <没匹配上子命令的内容>`，`CommandGroupFilter.filter` 的 `startswith`
返回 False，指令被跳过，**消息原样进模型**——模型收到一句普通提问，于是自己编。
爱完美实测过：用户发一个主页链接，模型回「打不开Steam，你发链接干嘛」。

所以指令组挂了 `_落空兜底`（`CustomFilter`）：只在真落空时 `set_result` +
`stop_event`。判据在 `ainong/兜底.是否落空`，**必须与
`CommandGroupFilter.startswith` 一致（字面前缀匹配）**，否则会吃掉正常指令。

`ainong/兜底.子命令名` 是手抄的别名清单，改 `main.py` 的指令或别名要跟着改——
`test_main_wiring.py` 会核对。

`.filter` 的返回值语义是「这条消息我管不管」，不是「命中没有」，**所有出口都必须
`return True`**：写成「命中返回 False」会让整个指令组失效。

组名另外挂了 `_组别名 = {f"/{_组名}"}`：QQ 官方的 At 唤醒分支不剥 `message_str`
里的 `/`，没有这个别名时 `@机器人 /爱农 战绩` 整条指令静默失败。

## 战绩字段：先核实语义，取不到就不显示

列表接口（`/game/morebattlelist`，`apiVersion: 5`）的字段语义**已用真实响应逐条
核实过**，别按字段名猜：

| 字段 | 语义 | 备注 |
|---|---|---|
| `gameresult` | 1 胜 / 2 负 | |
| `mvpcnt` | MVP（0/1） | 与 `mvpUrlV2` 里 mvp 图的数量一致 |
| `losemvp` | **败方 MVP，即 SVP**（0/1） | 别按名字找 `svp`，没有这个字段 |
| `firstBlood` / `godLikeCnt` / `hero1TripleKillCnt` / `hero1UltraKillCnt` | 一血 / 超神 / 三杀 / 四杀（0/1） | |
| `stars` | 段位星数 | 每场都带，最新一场才是「现在」 |
| `newMasterMatchScore` | 巅峰赛分 | **没打过巅峰赛的号全是 1200 初始分**，照直显示就是把「没打过」说成「1200 分」 |
| `evaluateUrl` | 奖牌图，形如 `…/evaluateV3/silver_archer.png` | 等级与职业都写在文件名里 |
| `desc` | 局内评价文案 | 实力局 / 翻车局 / 尽力局 / 躺赢局… |
| `AcntCamp` | **阵营（1/2，红蓝方）** | ⚠ 曾误当「参团率」，线上真出过「平均参团率 1.6%」 |
| `mapName` | 模式名（`排位赛 五排`） | |
| `usedTime` / `gradeGame` | 秒 / 评分（字符串） | |
| — | 经济 / 伤害 | **列表接口根本没有**，要这些得另走 `battledetail` |

`stats.py` 用 `_可选数` 按候选键名挨个试。**试不出来就返回 None，让这一项从
汇总文本里消失**，不能填 0——0 是合法数据，「这一项没有」不是；混起来模型会把
「没这个字段」读成「这项就是 0」，凭空编出结论。

新增统计维度时，测试里必须有一条是「缺字段时不出现在文本里」。

## 日志只能从 astrbot.api 取

插件规范：`logger` 必须且只能从 `astrbot.api` 导入，**严禁用 Python 内置
`logging`**。v0.1.14 上架审核就是被这一条驳回的——`ainong/auth/scan_session.py`
在模块顶层 `import logging`，`qq_login.py` 在异常处理里又写了一遍，而它们都在
发布包里，只看 `main.py` 查不出来。

`ainong/auth/` 与 `ainong/camp/` 刻意不 import astrbot（本地 pytest 要能直接跑
它们），所以日志走 `ainong/日志.py` 的出口：`main.py` 在 `__init__` 里
`挂日志(lambda 级别, 一句: getattr(logger, 级别)(f"[ainong] {一句}"))`，
模块里用 `记("warning", "……")`。爱瓦的 `aiva/transport.py` 是同一套做法。

约束由 `test_main_wiring.py` 的 `Test日志出口` 扫全包钉住（改完拿旧文件注入过，
能报出文件名）。

## 有没有数据靠返回值判断，不靠文本长相

`_读战绩` 与 `_读战绩与统计` 返回 `(文本, 统计字典)`，没有可用数据时统计字典是
`None`，调用方靠这个 `None` 决定能不能继续。

**不要改成靠文本前缀判断。** 这个角色没有可查的近期战绩时 `汇总文本` 返回的是
一句「这个角色还没有可查的近期战绩。」，它既不以「还没绑定」也不以「读取战绩
失败」开头。当成数据喂进锐评，提示里要求「全文至少出现 3 个具体数字」，
模型只能编。

## PK：对手靠名字定位，对比由代码算

**QQ 官方平台拿不到被 @ 的人的标识。** 实测日志：

    组件=['qq_official', None]   正文='爱农 PK'

被 @ 的人完全不出现——没有组件，正文里也没有 `<@!id>`。原因在
`qqofficial_platform_adapter`：它只把「@机器人」转成 `At`；引用消息也只构造
`Reply(id=消息ID)`，不带作者。所以定位顺序是 ① `@` 组件 → ② 正文 `<@!id>` →
③ **PK 名字**（`凭据仓库.按昵称找`），`ainong/pk.py` 管前两步。

名字默认取绑定时 `get_sender_name()`，但 QQ 官方给的是 QQ 昵称而不是群昵称
（实测有人是「……」），所以有 `/爱农 昵称` 让用户自己改。记录里额外存 `用户`
字段——文件名是标识的哈希，反推不回去。按名字找到的只有**记录**没有标识，
查对手战绩走 `_读战绩与统计`，别硬凑一个用户标识。

**逐项对比由代码算死，模型只负责解说。** 别把两份数据丢给模型让它自己比：实测
产出 83 对 87 和一段端水点评——「比较」是模糊任务，模型最省事的答案就是两边都
不否定。分工：

- `stats.对比要点` 逐项算出高低（胜率／KDA／平均评分／MVP 次数／场均击杀／
  场均死亡／最近 10 场胜场），返回带 `优` 字段的结构；**场均死亡是越小越好**；
  有一方没有场次时返回空。
- `stats.对比文本` / `占优项数` 折成文字随提示交给模型。**项数只是事实，不推出
  「占优多的一方更强」**——哪几项占优才决定强弱，判断留给模型。
- `prompts.端水词` 是显式禁令词表；列词表比写「不要端水」有效。

锐评同理：称号要带段位或招牌英雄、正文至少 3 个具体数字、「问题」那段必须落到
具体一项。改提示词时同步改 `test_prompts.py`。

## 微信与 QQ 扫码的差别

两条都要走"出码 → 推给用户 → 后台等 → 换凭据 → 登录营地"，但差别很实在：

| | 微信 | QQ |
|---|---|---|
| 出码 | 纯 HTTP | 要浏览器侧车 |
| 码的寿命 | 约五分钟 | 约两分钟 |
| 换码 | 不需要 | 出码那张**用满寿命**才换，每次换都要推给用户 |
| 营地登录参数 | `微信授权码=...` | `平台凭据={...}` |

「用满寿命才换」这条踩过：等待协程原本一进循环就换页取图，而出码 刚给过用户
一张——用户连着收到两张，而且那次换页让第一张当场作废，扫第一张必然失败。

两条路径的客户端版本号不同，营地按参数区分来源，**传错会被服务端拒**。
所以 `_收到授权码` 要按入参类型分流，别图省事统一包成平台凭据。

`playwright` 只在 `qq-verify` 依赖组里，所以 `ainong/auth/browser.py` 的
playwright import 必须留在 `浏览器会话.__aenter__` 里——放模块顶层的话，没装
playwright 的环境一加载插件就崩，微信那条也用不了了。

## 验证

```sh
uv run pytest                    # 测试
uv run ruff check .              # lint
uv run ruff format --check .     # 格式
```

测试只覆盖不需要凭据、不发网络请求的纯逻辑。营地接口需要登录态且有频控，
不做自动化测试；链路验证靠 `ainong/verify/` 下的脚本。

真实响应放 `test/fixtures/` 做快照，不用 mock 编造数据。

改动协议相关代码后，把真实响应重新录一遍快照再改实现——营地接口改版时
参考旧快照容易把错误当成新行为。

## 文档

只写中文。`README.md` 说明安装与配置，术语在 `docs/GLOSSARY.md`。

提交用 Conventional Commit 前缀，一次提交一个类型，推送与分支操作需要明确要求。
发版流程在 `docs/RELEASING.md`；改版本号时 `metadata.yaml` 与 `docs/CHANGELOG.md`
要一起改。