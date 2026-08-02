# Daily Paper Pages

一个 GitHub Pages 式的每日论文推送模板，参考 `hermes-arxiv-agent` 的“抓取 arXiv -> 生成静态阅读站 -> GitHub Pages 发布”链路，但把日常运行放进 GitHub Actions，不依赖本地 cron。

## 功能

- 每天按 `config/keywords.txt` 检索 arXiv
- 自动合并历史论文到 `data/papers.json`
- 维护 `data/notified_ids.json`，已成功推送过的 arXiv ID 不会再次推送
- 生成 `site/papers_data.json`、每日增量 JSON 和 RSS
- 部署 `site/` 到 GitHub Pages
- 可选：配置 `FEISHU_WEBHOOK` 后向飞书/Lark 机器人推送当天新增论文
- 可选：配置 OpenAI-compatible LLM API 后，为新增论文生成中文简介

## 部署

1. 新建一个 GitHub 仓库，把本目录内容推到仓库默认分支。
2. 在仓库 `Settings -> Pages` 中将 `Source` 设置为 `GitHub Actions`。
3. 编辑 `config/keywords.txt`，每行一个 arXiv API 查询表达式。
4. 打开 `Actions -> Daily Papers -> Run workflow` 手动跑一次。

默认定时是 UTC `23:10`，对应北京时间每天 `07:10` 左右。要调整时间，编辑 `.github/workflows/daily-papers.yml` 里的 cron。

## 关键词示例

```text
all:retrieval+AND+all:augmented+AND+all:generation
cat:cs.CL+AND+all:large+AND+all:language+AND+all:model
cat:cs.AI+AND+all:agent
```

当前默认关键词覆盖三维重建、三维编辑、三维生成、Gaussian Splatting、前馈高斯、室内布局生成、物理约束、VLM 驱动三维生成/编辑、全景图和 omnidirectional vision。要扩展方向，继续往 `config/keywords.txt` 增加 arXiv 查询即可。

## 可选飞书推送

在仓库 `Settings -> Secrets and variables -> Actions` 中配置：

- Secret: `FEISHU_WEBHOOK`，飞书/Lark 自定义机器人 webhook
- Secret: `FEISHU_SECRET`，可选；如果你给机器人开启了签名校验，就填机器人安全设置里的签名密钥
- Variable: `SITE_URL`，你的 GitHub Pages 地址
- Secret: `LLM_API_KEY`，可选；用于生成中文简介
- Variable: `LLM_BASE_URL`，可选；默认 `https://api.openai.com/v1`，也可以填 OpenAI-compatible 服务地址
- Variable: `LLM_MODEL`，可选；默认 `gpt-4o-mini`
- Variable: `LLM_MAX_PAPERS`，可选；默认每天最多给 30 篇新论文生成中文简介
- Variable: `FEISHU_MAX_PAPERS`，可选；默认飞书卡片最多展示 30 篇，超过后提示到阅读页查看

不配置 `FEISHU_WEBHOOK` 时，workflow 会跳过通知，只更新 GitHub Pages。
不配置 `LLM_API_KEY` 时，workflow 会跳过中文简介生成。

## 去重说明

飞书推送只发送 `new_papers` 中尚未出现在 `data/notified_ids.json` 的论文。只有飞书 webhook 返回成功后，脚本才会把这些 arXiv ID 写入 `data/notified_ids.json` 并提交到仓库。这样同一篇论文即使后续 workflow 手动重跑、定时重跑，或被多个关键词命中，也不会重复推送。

## 本地预览

```bash
python3 scripts/fetch_papers.py --max-results 5 --days-lookback 7
python3 -m http.server 8765 -d site
```

然后访问 `http://localhost:8765`。
