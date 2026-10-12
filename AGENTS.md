# Agent guide

`ainong` 是 AstrBot 插件，通过王者营地接口读取玩家战绩，交给模型。

## 约定

- 包内一律用相对导入。插件目录被 AstrBot 当成包加载，顶层包名在容器里
  import 不到。
- 指令全在 `爱农` 指令组下（`/爱农 战绩`），不占用通用名字。改动指令时
  提示文本里的示例要一起改。
- `requirements.txt` 由 `uv export --format requirements.txt --no-hashes --no-dev
  --no-emit-project --frozen --output-file requirements.txt` 生成，不要手工编辑。
  加了依赖要重新导出，否则装插件时缺包。
- 只有验证脚本需要的依赖放进 `[dependency-groups] qq-verify`。缺它插件仍能加载，
  只是提供不了 QQ 扫码。
- 网络请求只用 `aiohttp`。
- 持久化数据放 AstrBot 的 `data/plugin_data/ainong/`，不放插件目录。
- 凭据不写日志、不进异常消息、不进提交。解绑时删文件，不保留。
- 插件图标必须是根目录的 `logo.png`，文件名与位置都是 AstrBot 硬编码的
  （`star_manager.py` 里的 `logo_fname`）。WebUI 通过一个 300 秒有效的文件
  token 拉图，所以体积要小——超过几百 KB 每次刷新都会重传。改图标时改
  `logo.png`，不要另建目录。

## 结构

```
main.py             插件入口，指令组与指令
ainong/crypto/       XXTEA、PKCS#1 块解析
ainong/auth/         YSDK 签名、微信与 QQ 扫码、浏览器会话
ainong/camp/         营地接口：传输层、频控、战绩
ainong/stats.py      战绩统计与文本汇总
ainong/storage.py    凭据与绑定关系
ainong/verify/       可行性验证脚本，不参与运行
test/                pytest 用例与真实响应快照
deploy/              浏览器服务的 compose 片段、Dockerfile 与 seccomp 配置
docs/                更新日志与术语表
```

## 两条容易踩的顺序约束

`main.py` 跑不了单测（顶层 import astrbot，本地没这个包），所以下面两条靠
`test/test_main_wiring.py` 做源码检查，改动时别把顺序写反。

- **`_通知` 必须在 `_清理会话` 之前。** 通知依赖 `_事件` 与 `_会话标识`，
  清理会把两者 pop 掉。
- **扫码回调只能是单参协程。** `等授权码` 按 `完成(授权码)` 调用，回调要写成
  协程，用户标识用闭包绑掉。

## 微信与 QQ 扫码的差别

两条都要走"出码 → 推给用户 → 后台等 → 换凭据 → 登录营地"，但差别很实在：

| | 微信 | QQ |
|---|---|---|
| 出码 | 纯 HTTP | 要浏览器侧车 |
| 码的寿命 | 约五分钟 | 约两分钟 |
| 换码 | 不需要 | 每 25 秒换一张，**每次都要推给用户** |
| 营地登录参数 | `微信授权码=...` | `平台凭据={...}` |

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