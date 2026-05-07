# AGENTS.md

在此仓库中工作的 Agent 指南。

## 核心规则

本仓库主要通过编辑导航配置来维护，而不是修改应用代码。

<IMPORTANT>
除非用户明确要求修复代码或添加功能，否则只编辑：

- `src/mock/mock_data.js`
- `download_ico.py`

对于常规的站点/分类更新，不要修改 Vue 组件、样式、路由、部署文件或后端文件。
永远不要运行 `npm run xxx`/`pnpm run xxx`
</IMPORTANT>

如果需要编辑其他文件，先征得许可。

## 主文件

`src/mock/mock_data.js` 是导航数据的唯一数据源。

当用户要求：

- 添加网站
- 移除网站
- 移动网站
- 重命名分类
- 创建或合并分类
- 更新描述

时，编辑 `src/mock/mock_data.js`。

## 数据规则

保持现有结构：

```js
export const mockData = {
  categories: [
    {
      id: "category-id",
      name: "分类名",
      icon: "💥",
      order: 0,
      sites: [
        {
          id: "site-id",
          name: "Site Name",
          url: "https://example.com",
          description: "short description",
          icon: "/sitelogo/example.com.ico"
        }
      ]
    }
  ]
}
```

编辑时遵循以下规则：

- 优先使用现有分类。
- 仅当用户要求或当前分类明显太杂时，才创建新分类。
- 分类名称保持简短清晰。
- 站点描述保持简短。
- 在可行的情况下使用小写 kebab-case 格式的 `id` 值。
- 保持 `order` 值稳定合理。
- 保留当前文件风格和格式。

## 图标规则

- 图标路径通常应为 `/sitelogo/<域名>.ico`。
- 无需担心图标文件是否已存在。
- 缺失的图标稍后可通过 `download_ico.py` 获取。
- 下载缺失图标运行：`./download_ico.py`。
- 不要因为图标尚未下载而阻塞配置变更。
- 添加新网站后，务必运行 `./download_ico.py` 尝试下载图标。

## 范围控制

对于常规导航维护，不要"清理"不相关的条目。

禁止：

- 重构文件结构
- 重命名无关的 id
- 未经要求重新排序大段内容
- 仅仅因为看起来可以改进就编辑源码

如果某需求确实需要修改应用代码，在修改 `src/mock/mock_data.js` 之外的文件之前，先停下来询问。
