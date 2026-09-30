# 抗体图谱助手 - Edge 浏览器插件

参考 Mendeley 浏览器插件设计，用于在浏览学术文献或网页时一键将文献添加到「抗体图谱」项目数据库并触发 AI 数据提取。

## 功能特性

- **一键提交**：在任意学术文献页面（PubMed、PMC、Nature、Science、Springer、Wiley、Lancet、BMJ、medRxiv/bioRxiv、arXiv、知网、万方、维普等）点击插件图标即可提交
- **元数据自动提取**：通过 `content-script` 自动识别页面的标题、作者、DOI、PMID、期刊、年份、摘要、关键词
- **PDF 智能抓取**：检测到 PDF 文件或页面中的 PDF 链接时，自动抓取二进制并上传到后端
- **URL 导入**：对于无 PDF 的网页，保存为 HTML 走后端的 URL 抓取流程
- **AI 提取联动**：提交后自动触发后端 LLM 提取，弹窗内实时轮询提取状态
- **右键菜单**：在任意页面/链接上右键可"添加到抗体图谱数据库"
- **桌面通知**：上传、提取、错误全程通知
- **配置灵活**：可配置后端地址、默认省份、LLM 模型/API Key/Base URL

## 目录结构

```
browser-extension/
├── manifest.json          # Manifest V3 清单
├── background.js          # Service Worker（API 调用、PDF 抓取、绕过 CORS）
├── content-script.js      # 页面元数据提取（注入到所有页面）
├── popup.html             # 弹窗 UI
├── popup.js               # 弹窗逻辑
├── options.html           # 设置页
├── options.js             # 设置页逻辑
├── styles.css             # 共用样式
├── icons/
│   ├── icon16.png         # 16×16 图标
│   ├── icon48.png         # 48×48 图标
│   └── icon128.png        # 128×128 图标
└── README.md              # 本文档
```

## 安装方法（Edge 浏览器）

### 步骤 1：打开扩展管理页

1. 打开 Edge 浏览器
2. 地址栏输入 `edge://extensions/` 回车
3. 打开右上角的「**开发人员模式**」开关

### 步骤 2：加载插件

1. 点击左下角的「**加载解压缩的扩展**」按钮
2. 选择目录：`e:\linux\trae_project\antibody_map01\browser-extension`
3. 插件将出现在扩展列表中，名称为「**抗体图谱助手 (Antibody Map Helper)**」

### 步骤 3：固定到工具栏（推荐）

1. 点击 Edge 工具栏右侧的「扩展」图标（拼图形状）
2. 找到「抗体图谱助手」，点击右侧的「**在工具栏中显示**」按钮（眼睛图标）
3. 插件图标将固定显示在工具栏，方便随时点击

### 步骤 4：配置后端地址

1. 点击工具栏中的插件图标，弹出操作面板
2. 点击顶部的「**设置**」链接，打开设置页
3. **后端服务地址**：默认 `http://localhost:8000`
   - 若用 `start.sh` 启动后端 → 8000 端口
   - 若用 `start.ps1` 启动后端 → 8080 端口
4. （可选）配置默认省份、LLM 模型、API Key
5. 点击「**保存设置**」，再点「**测试后端连通性**」确认绿色提示

## 使用方法

### 场景 1：在 PubMed/期刊页面添加文献

1. 在 Edge 中打开任意学术文献详情页（如 `https://pubmed.ncbi.nlm.nih.gov/xxxxx/`）
2. 点击工具栏的插件图标
3. 弹窗会自动填充：标题、DOI、作者、年份、期刊
4. 提交方式显示为「PDF 抓取」或「URL 导入」
5. 勾选「提交后自动触发 AI 提取」（默认勾选）
6. 点击「**添加到数据库**」
7. 进度面板显示：① 提交文献 → ② AI 提取 → ③ 完成
8. 提取完成后可点击「查看详情」跳转后端文档

### 场景 2：直接浏览 PDF

1. 在 Edge 中打开任意 PDF 文件 URL（如 `https://xxx.com/article.pdf`）
2. 点击插件图标
3. 弹窗识别为 PDF 文件，直接走上传流程

### 场景 3：右键菜单

1. 在任意页面或链接上右键
2. 选择「**添加到抗体图谱数据库**」
3. 弹出桌面通知，提示点击插件图标完成提交

## 工作流程图

```
用户打开文献页面
      │
      ▼
点击插件图标 ──► popup.js 向 content-script.js 请求元数据
      │                       │
      │                       ▼
      │              提取: 标题/作者/DOI/期刊/年份/摘要/PDF链接
      │                       │
      ▼                       ▼
popup 显示表单 ◄──────── 填充元数据
      │
      │ 用户点击「添加到数据库」
      ▼
popup → background.js (SUBMIT_FROM_METADATA)
      │
      ├─ 有 PDF 链接？──► fetch PDF 二进制 → POST /api/v1/literatures/upload
      │                                       (multipart/form-data)
      │
      └─ 无 PDF ──────► POST /api/v1/literatures/from-url (URL 导入)
                                              │
                                              ▼
                                   上传成功，得到 literature.id
                                              │
                                              ▼
                            (若启用自动提取) POST /api/v1/literatures/{id}/extraction
                                              │
                                              ▼
                            popup 每 3 秒轮询 GET /api/v1/literatures/{id}/extraction/status
                                              │
                                              ▼
                                   status === 'done' → 显示「提取 N 个数据点」
```

## 后端接口对接

插件调用以下后端 API（无需认证）：

| 用途 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 健康检查 | GET | `/api/v1/health` | 连通性测试 |
| 文件上传 | POST | `/api/v1/literatures/upload` | `multipart/form-data`，字段：`file`(必)、`title`、`doi`、`province` |
| URL 导入 | POST | `/api/v1/literatures/from-url` | `multipart/form-data`，字段：`url`(必)、`title`、`province` |
| 触发提取 | POST | `/api/v1/literatures/{id}/extraction` | JSON body 可选：`model`、`api_key`、`base_url` |
| 提取状态 | GET | `/api/v1/literatures/{id}/extraction/status` | 轮询用，返回 `status` 字段 |

## 关于 CORS

后端 CORS 默认仅放行 `http://localhost:3000` 和 `http://localhost:5173`（前端开发地址）。
浏览器扩展通过 `manifest.json` 中的 `host_permissions` 声明后端地址，由 **background service worker** 发起请求可**绕过 CORS 限制**（这是 Manifest V3 扩展的标准能力）。

如需让后端也直接放行扩展源（非必需），可在后端 `.env` 中追加：

```
CORS_ORIGINS=["http://localhost:3000","http://localhost:5173","chrome-extension://*"]
```

## 常见问题

### Q1: 弹窗显示「后端不可达」？

- 检查后端服务是否启动：浏览器访问 `http://localhost:8000/docs`
- 检查端口：`start.sh` 用 8000，`start.ps1` 用 8080
- 在设置页修改后端地址并测试

### Q2: 提交后提示「抓取 PDF 失败」？

- 部分学术站点（知网、Springer 等）有防盗链/登录墙，浏览器扩展无法直接抓取
- 解决：手动下载 PDF 到本地，通过 Web 端上传

### Q3: AI 提取一直「提取中」？

- LLM 提取耗时较长（PDF 越长越慢，通常 30 秒~3 分钟）
- 弹窗最多轮询 60 次（3 分钟），超时后可关闭弹窗，到 Web 端查看结果
- 检查后端 `.env` 中的 `LLM_API_KEY` 是否有效

### Q4: 在 chrome:// 页面无法使用？

- 浏览器安全策略禁止扩展注入 `chrome://` 页面
- 请在普通网页使用

### Q5: 如何更新插件代码？

- 修改 `browser-extension/` 下任意文件后
- 进入 `edge://extensions/`，找到本插件，点击「重新加载」按钮（圆形箭头图标）

## 支持的学术站点

| 站点 | 域名 | 元数据识别 |
|------|------|-----------|
| PubMed | pubmed.ncbi.nlm.nih.gov | ✅ 完整 |
| PMC | pmc.ncbi.nlm.nih.gov | ✅ 完整 |
| Nature | nature.com | ✅ 完整 |
| Science | science.org | ✅ 完整 |
| Cell | cell.com | ✅ 完整 |
| Springer | springer.com, link.springer.com | ✅ 完整 |
| Wiley | wiley.com | ✅ 完整 |
| Lancet | thelancet.com | ✅ 完整 |
| BMJ | bmj.com | ✅ 完整 |
| medRxiv/bioRxiv | medrxiv.org, biorxiv.org | ✅ 完整 |
| arXiv | arxiv.org | ✅ 完整 |
| 知网 | cnki.net, cnki.com.cn | ⚠️ 部分（需登录） |
| 万方 | wanfangdata.com.cn | ⚠️ 部分 |
| 维普 | cqvip.com | ⚠️ 部分 |
| DOI 解析 | doi.org | ✅ 完整 |
| 通用 HTML | 其他 | ✅ 基础（标题/年份/DOI） |

## 技术说明

- **Manifest V3**：使用 service worker 而非 background page
- **CORS 绕过**：通过 `host_permissions` + background fetch 实现
- **文件上传**：使用 `FormData` + `File` API，不手动设置 `Content-Type`（让浏览器自动添加 boundary）
- **存储**：使用 `chrome.storage.local` 持久化配置
- **消息通信**：popup ↔ background ↔ content-script 通过 `chrome.runtime.sendMessage` / `chrome.tabs.sendMessage`
