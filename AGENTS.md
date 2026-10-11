# Agent guide

`ainong` 是 AstrBot 插件，通过王者营地接口读取玩家战绩，交给对话模型做锐评。

## 仓库结构

```
metadata.yaml           插件元信息，框架靠它识别插件
main.py                 插件入口，类继承 Star
_conf_schema.json       面板配置项
ainong/
  crypto/               XXTEA、PKCS#1 块解析、凭据字段提取
  auth/                 YSDK 签名
  camp/                 营地接口：传输层、设备指纹、分块 RSA、encodeRes
  verify/               可行性验证脚本，不参与插件运行
test/                   pytest 用例与测试向量
deploy/                 浏览器服务的 compose 片段与 seccomp 配置
docs/                   CHANGELOG 与术语表
```

包内一律用相对导入。插件目录被 AstrBot 当成包加载，顶层包名在容器里
import 不到。

`verify/` 不是运行时的一部分，它验证协议链路是否可用。跑通了就不再需要它，
但保留下来作为协议变更后的回归手段。

## 工程约定

- `requirements.txt` 由 `uv export` 生成，不要手工编辑。它是交给 AstrBot装进容器的依赖清单。
- 依赖分两类：运行时依赖写在 `dependencies`，只有验证脚本需要的写进
  `[dependency-groups]qq-verify`。缺少后者时插件仍能正常加载，只是提供不了 QQ 扫码。
- 网络请求只用 `aiohttp`，不用 `requests`。
- 插件的持久化数据放 AstrBot 的 `data/plugin_data/ainong/`，不放插件目录——
  更新插件会覆盖插件目录。
- 新增依赖后必须跑 `uv export --format requirements.txt --output-file requirements.txt --frozen`
  同步依赖清单，否则装插件时会缺包。

## 凭据处理

- 凭据（令牌、对称密钥）不写进日志、不进异常消息、不进提交。
- 解绑时立即删除凭据文件，不保留。
- 验证脚本会把凭据写到临时目录，跑完自行清理。临时目录里的凭据文件不要提交。

## 测试

-测试只覆盖不需要凭据、不发网络请求的纯逻辑：加密解密、编解码、签名构造、字段映射。
- 营地接口需要凭据且有频控，不做自动化测试。链路验证靠 `ainong/verify/` 下的脚本，
  配合 `deploy/` 里的浏览器服务。
- 不用 mock 替代营地响应。需要真实响应时用录制快照，放在 `test/fixtures/`。

## 文档

只写中文，不维护英文版。`README.md` 说明这是什么、怎么装、怎么配、怎么开发。
术语定义在 `docs/GLOSSARY.md`，改动术语时同步更新。

## 提交

按 Conventional Commit 前缀提交，一次提交只属于一个类型，推送、创建分支、
改写历史都需要明确要求。