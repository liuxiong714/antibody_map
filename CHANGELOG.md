# 变更日志

## v1.22.0 (2026-08-31)

### 知识图谱（新功能）

- 新增 13 种实体类型（病原体/地区/人群/检测方法/疫苗/调查/时间/指标/实施单位/作者/样本/数据质量/出版物）和 18 种关系类型的本体定义
- **计算式推导**：从已审核数据点自动生成基础实体与关系边，支持省份→大区层级（BELONGS_TO）、统计对比（HIGHER_THAN）、异常高值影响因子分析（INFLUENCES）
- **LLM 抽取**：从文献全文自动抽取三元组持久化存储，复用现有 LLM 基础设施，特性开关 `ENABLE_KG_EXTRACTION` 控制，失败不影响主提取流程
- 新增 `kg_entity` / `kg_triple` 数据库表（Alembic 迁移）
- 新增知识图谱专用 API 端点：概览 `/kg/overview`、筛选选项 `/kg/options`、图谱数据 `/kg/graph`、实体搜索 `/kg/entities/search`、路径推理 `/kg/query/path`、统计 `/kg/stats`、批量抽取 `/kg/batch`
- 新增知识图谱前端页面（ECharts 力导向图交互式可视化，筛选条件联动，侧边栏实体详情，实体搜索与路径推理标签页）
- 导航栏新增"知识图谱"入口，支持中英文 i18n

### 连接池修复（F14）

- **心跳超时保护**：`_stop_heartbeat()` 改为有限等待（10s 超时），避免心跳循环与主写库事务竞争同一文献行锁形成自锁，防止连接被服务端断开
- **写库前停止心跳**：心跳循环提前到写库事务开始前停止，消除行锁竞争窗口
- **恢复 pool_pre_ping**：启用连接池存活校验，避免 LLM/网络长调用后复用池中陈旧连接导致 `"connection is closed"` 错误
- **连接断开错误分类**：将 asyncpg 连接断开类错误（connection is closed、InterfaceError、broken pipe 等）归入 `connection_error` 类别，走快速重试逻辑而非判为永久失败

### 其他优化

- worker 并发数调整为 `concurrency=1`，避免同一进程内多个提取任务并发抢用 asyncpg 连接池引发连接竞态
- 新增 `EXTRACTION_STALE_MINUTES` 环境变量，统一 backend 与 worker 的提取状态"卡死"回收阈值
- 修复 `pdf_parser.py` 中 `asyncio.run(_run)` 缺少括号的调用错误
- 前端 ECharts 注册 `GraphChart` 系列，支持知识图谱力导向图渲染

---

## v1.21.0 (2026-08-28)

- AI 提取耗时记录：记录每次 LLM 提取的 wall-clock 耗时，存入提取历史表
- 文献详情页内联展示历次 AI 提取历史（含耗时/模型/Token/费用，支持一键重新提取）
- 存量历史回填：为已有提取历史的文献回填 llm_call_count 和 llm_usage_detail

## v1.20.0 (2026-08-27)

- 免疫屏障达标概率（Monte Carlo 不确定性量化）端点
- 基于 Monte Carlo 仿真的免疫屏障达标概率计算

## v1.19.2 (2026-08-26)

- 提取状态口径统一：区分「已完成/完成（无数据）/失败」三终局
- 退出登录自动备份对话框
- 数据库写入保险

## v1.19.1 (2026-08-25)

- PDF 预览内联 Worker 与流式加载修复
- 文献列表虚拟滚动回退

## v1.19.0 (2026-08-22)

- LLM 提取管线加固：API Key 加密存储、提示注入防护、token 预算/日配额/并发上限、幂等写库、状态超时自动回收
- 安全增强与深色主题

## v1.18.0 (2026-08-15)

- 免疫屏障评估报告
- pdf-inspector PDF 解析（Rust 实现）
- 备份还原与导入历史进度条

## v1.17.1 (2026-08-10)

- 文档迁移 ReadTheDocs
- 标题修正增强与回收站括号修复

## v1.17.0 (2026-08-05)

- AnyDoc 文档解析增强（Rust 实现，毫秒级转 GFM Markdown）
- 提取队列状态与疫苗接种策略模型选择

## v1.16.0 (2026-07-28)

- 文献回收站（软删除）

## 更早版本

详见 [ReadTheDocs 变更日志](https://antibody-map.readthedocs.io/zh-cn/latest/changelog/)。