# 发版

一次发版是升一个版本号、合并到 `main`、在合并后的提交上打 `vX.Y.Z` 标签。
分支推送不发布任何东西。示例用 `dev`，换别的开发分支同理。

## 一次发版会影响什么

- **GitHub Release** —— 手动触发，不自动。
- **AstrBot 插件市场** —— **不由标签驱动**，要另外向
  [`AstrBot_Plugins_Collection`](https://github.com/AstrBotDevs/AstrBot_Plugins_Collection)
  提 PR，把本仓库加进 `plugin_cache_original.json`。市场读的是仓库里的
  `metadata.yaml`，还有一张单独的图片 URL。

  市场里的 `logo` 字段长这样：

  ```
  https://raw.githubusercontent.com/<账号>/<仓库>/<分支>/logo.png
  ```

  两个后果：**文件名必须是 `logo.png`**（文件名由 AstrBot 硬编码），并且
  **该分支上必须真的有这个文件**——仓库里常见的 `master` / `main` /
  `default` 都可能，默认分支换了图就 404。这也是发版必须合到 `main` 的原因：
  留在 `dev` 上市场拿不到图。

## 清单

1. 在开发分支上定 `X.Y.Z`，更新带版本的地方：

   - `metadata.yaml` 的 `version`（带 `v` 前缀，如 `v0.1.0`）
   - `docs/CHANGELOG.md` 的首个小节，标题写成 `## [X.Y.Z] - YYYY-MM-DD`

2. 跑本仓库的检查（命令见 `AGENTS.md` 的验证一节）：

   ```sh
   uv run pytest
   uv run ruff check .
   uv run ruff format --check .
   ```

3. 提交并推开发分支：

   ```sh
   git commit -am "chore: release X.Y.Z"
   git push origin dev
   ```

4. 等这个分支的 CI 变绿。此时**什么都没发布**——标签不存在，CI 只验证。

5. 合并到 `main` 并推送：

   ```sh
   git switch main
   git pull
   git merge --no-ff dev -m "merge: dev -> main"
   git push origin main
   ```

6. 在 `main` 上打标签并推送：

   ```sh
   git tag vX.Y.Z main
   git push origin vX.Y.Z
   ```

   **在 `tag` 命令里写 `main`，不要给 `HEAD` 所在的位置打标签。** 这是
   squash 或 rebase 合并会踩的坑：分支上的提交会被替换成 `main` 上的一个新提交，
   在分支提交上打的标签从 `main` 不可达，市场和 GitHub 拿到的就不是同一份代码。
   如果已经打错了，本地删掉这个标签，合并完再打 `main`。

7. 在 GitHub 上写 Release。说明取 `docs/CHANGELOG.md` 对应小节的内容。

8. 要进 AstrBot 插件市场，另开一份 PR 到 `AstrBot_Plugins_Collection`，
   照现有条目的字段写。一条最少要有：

   ```json
   "astrbot_plugin_ainong": {
     "display_name": "爱农",
     "desc": "查王者营地战绩，让模型替你锐评。",
     "author": "xswt442-cmd",
     "repo": "https://github.com/xswt442-cmd/astrbot_plugin_ainong",
     "tags": ["王者荣耀", "战绩", "锐评"],
     "version": "v0.1.0",
     "astrbot_version": ">=4.16",
     "support_platforms": ["aiocqhttp", "weixin_oc"],
     "logo": "https://raw.githubusercontent.com/xswt442-cmd/astrbot_plugin_ainong/main/logo.png"
   }
   ```

   `version`、`display_name`、`astrbot_version`、`support_platforms` 要和
   `metadata.yaml` 一致——市场不会替你校对，不一致时用户装到的是和页面描述
   不同的东西。`astrbot_version` 的写法比 `metadata.yaml` 宽一点没关系，市场
   只做展示。

## 标签发布后能改吗

不能。同一个标签指向的提交是既定的。想修正就发一个新版本，旧版本留着。

如果某个版本有问题而内容本身没错，改 `metadata.yaml` 里的版本号是不够的——
已经装出去的插件不会因为版本号变化而更新。要让用户拿到修正，发新的补丁版本。

## 发版前值得确认的两件事

这两个问题在发版前发现代价很小，发出去之后再改就要发新版本：

- **`logo.png` 在 `main` 上真的能访问。** 直接开
  `https://raw.githubusercontent.com/<账号>/<仓库>/main/logo.png` 看一眼。
  返回 404 说明分支名或文件名不对，市场里就是一张裂图。
- **`requirements.txt` 和 `pyproject.toml` 同步。** CI 有这道检查，但值得
  自己再确认一次：装插件时用的是这个文件，不同步会让用户装到缺包的版本，
  而开发环境一切正常。
