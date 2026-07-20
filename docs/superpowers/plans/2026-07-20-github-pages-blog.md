# Covivy GitHub Pages 博客实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 创建一篇可直接通过 GitHub Pages 发布的中文 Covivy 推荐博客，同时兼顾使用转化和招聘展示。

**架构：** 使用 GitHub Pages 原生支持的 `docs/index.md` 和 `docs/_config.yml`，避免引入前端构建链。用仓库事实驱动正文内容，并生成一张静态 PNG 架构图辅助理解。

**技术栈：** Markdown、Jekyll/GitHub Pages、PNG、Python/Pillow（仅用于生成流程图）

---

### 任务一：撰写中文博客正文

**文件：**
- 新建：`docs/index.md`

- [ ] 根据已批准设计撰写故事型开场、产品解释、端到端流程、技术亮点、适用人群、快速开始、项目能力信号和边界说明。
- [ ] 对照 `README.md`、`app/coverage.py`、`app/services.py`、`app/main.py` 和 GitHub Action 配置核实所有功能描述。
- [ ] 检查段落长度、标题层级、术语首次解释和幽默表达，删除 README 式功能堆砌。
- [ ] 检查文章中的仓库链接、命令、环境变量和相对图片路径。

### 任务二：生成中文架构流程图

**文件：**
- 新建：`docs/assets/covivy-flow.png`

- [ ] 使用 Pillow 生成横向流程图，展示 CI、API、PostgreSQL/文件存储、Worker、语义覆盖率引擎、GitHub PR 反馈和 Dashboard。
- [ ] 使用稳定尺寸、清晰中文文字和克制的多色节点，确保桌面与移动端缩放后仍可辨认。
- [ ] 检查 PNG 文件格式、像素尺寸和非空内容。
- [ ] 打开图片进行视觉检查，确认无裁切、重叠和乱码。

### 任务三：配置 GitHub Pages

**文件：**
- 新建：`docs/_config.yml`
- 新建：`docs/GITHUB_PAGES.md`

- [ ] 配置页面标题、描述、仓库链接、语言和 GitHub Pages 兼容主题。
- [ ] 编写中文发布步骤：推送分支、选择 Deploy from a branch、选择目标分支和 `/docs`、等待部署并访问站点。
- [ ] 补充常见问题：404、未更新、图片路径、Pages 权限和自定义域名入口。
- [ ] 检查 YAML 能被解析，Markdown 中不包含本机绝对路径。

### 任务四：验证交付物

**文件：**
- 验证：`docs/index.md`
- 验证：`docs/_config.yml`
- 验证：`docs/GITHUB_PAGES.md`
- 验证：`docs/assets/covivy-flow.png`

- [ ] 扫描文章中的功能陈述并与仓库实现逐项比对。
- [ ] 检查 Markdown 标题、代码围栏、链接、图片和中文标点。
- [ ] 运行 YAML 解析、PNG 元数据检查、`git diff --check` 和 Ruff。
- [ ] 若本地具备可用的 Jekyll/浏览器环境，启动并检查页面；否则明确记录未执行的视觉渲染验证。
- [ ] 汇总文件位置、验证结果和 GitHub Pages 发布步骤。

