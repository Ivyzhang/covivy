---
layout: default
title: GitHub Pages 发布指南
description: 将 Covivy 中文博客发布到 GitHub Pages 的操作步骤与排错说明。
---

# GitHub Pages 发布指南

博客正文位于 `docs/index.md`，Pages 配置位于 `docs/_config.yml`。不需要额外的前端构建工具。

## 首次发布

### 1. 提交并推送文件

确认以下文件已经进入准备发布的分支：

```text
docs/index.md
docs/_config.yml
docs/GITHUB_PAGES.md
docs/assets/covivy-flow.png
```

然后提交并推送：

```bash
git add docs/index.md docs/_config.yml docs/GITHUB_PAGES.md docs/assets/
git commit -m "docs: add Covivy GitHub Pages blog"
git push origin main
```

如果你通过 Pull Request 合并，请在 PR 合并后继续下面的设置。

### 2. 启用 GitHub Pages

1. 打开 [Covivy 仓库](https://github.com/Ivyzhang/covivy)。
2. 进入 **Settings**。
3. 在左侧 **Code and automation** 区域选择 **Pages**。
4. 在 **Build and deployment** 下，将 **Source** 设为 **Deploy from a branch**。
5. Branch 选择 `main`，目录选择 `/docs`。
6. 点击 **Save**。

GitHub 会开始构建页面。首次部署通常需要等待片刻，完成后 Pages 设置页会显示站点地址：

```text
https://ivyzhang.github.io/covivy/
```

### 3. 检查发布结果

打开首页后检查：

- 中文标题、段落和代码块是否正常显示；
- 架构图是否加载；
- 仓库、Issue、README 和发布指南链接是否可以访问；
- 手机浏览器中表格是否可以横向滚动或正常缩放。

## 后续更新

修改 `docs/index.md` 或 `docs/assets/` 后提交到 Pages 所使用的分支即可。GitHub 会自动重新构建，无需重复启用 Pages。

## 常见问题

### 页面返回 404

先确认 Pages 的发布源是正确分支的 `/docs`，并确认该分支存在 `docs/index.md`。项目站点地址包含仓库名，应使用：

```text
https://ivyzhang.github.io/covivy/
```

而不是 `https://ivyzhang.github.io/`。

### 推送后页面没有更新

在仓库 **Actions** 页面查看 Pages 构建是否完成。浏览器或 CDN 也可能保留短暂缓存，可以等待片刻后强制刷新。

### 架构图没有显示

正文使用相对路径 `assets/covivy-flow.png`。确认文件名大小写完全一致，并且 PNG 已提交到 `docs/assets/`。不要把路径改成本机绝对路径。

### Settings 中没有 Pages 选项

确认当前账号对仓库拥有管理员权限，并检查组织策略是否禁用了 GitHub Pages。私有仓库能否发布 Pages 还取决于当前 GitHub 套餐和组织配置。

### 使用自定义域名

在 **Settings → Pages → Custom domain** 填入域名，并按 GitHub 提示配置 DNS。验证成功后建议启用 **Enforce HTTPS**。GitHub 会在发布源中维护 `CNAME` 文件。

## 可选：本地预览

GitHub Pages 使用 Jekyll 渲染 Markdown。如果本机已经安装兼容的 Ruby 与 Bundler，可以使用 Jekyll 预览；否则直接通过 PR 检查 Markdown，合并后让 GitHub Pages 构建即可。本项目运行 Covivy 本身不依赖 Ruby。

