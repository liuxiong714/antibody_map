# 北京地区麻疹血清抗体流行病学研究 — 实施方案

> **撰写日期**：2026-09-17
> **执行人**：用户
> **系统平台**：antibody_map（本地 Docker 部署）
> **预计周期**：5–7 个工作日（可并行）
> **前置依赖**：Windows 本机 GPU ≥ 16GB VRAM，Ollama 已部署并可被容器访问

---

## 0. 执行前核对：北京麻疹数据现有家底（已核实）

| 维度 | 现状 | 说明 |
|---|---|---|
| 北京地区麻疹相关文献 | **83 篇** | 发表年份跨度 **1983 → 2024** |
| 已提取数据点 | **1536 条** | 来自 `disease IN ('measles','麻疹') AND province='北京'` |
| 审核状态 | 批准 65 / 驳回 7 / **pending 1464** | 绝大多数数据点仍待人工审核 |
| 历史提取模型 | 主用 **qwen3.8:27b**（65 篇），少量 qwen2.5:32b / qwen2.5:14b / deepseek-v4-flash | **仅跑过 1 个模型，无法对比** |
| 平均提取耗时 | 172.5 s / 篇（qwen3.8:27b） | |
| extraction_status | 83 篇全部 done | **无需重新上传，PDF 已在系统中** |
| 系统合成自测能力 | ✅ 已有 | 可直接复用做多模型准确性对比 |

### 关键结论（影响方案设计）

1. **83 篇文献已全部跑过 qwen3.8:27b 提取**，PDF 和文本缓存全在。方案不重复劳动，而是**增加"多模型子集"做对比评估**。
2. 对比评估选 **15–20 篇代表文献**（按年代 / 人群 / 数据密度分层抽样）即可，对 83 篇全量跑多模型 GPU 时间成本过高且收益递减。
3. 审核流水线 **1464 条 pending** 是当前最大工作量瓶颈。方案 Step 4 提出**批量筛选 + 重点精审**策略，而非逐条人工审。

---

## 1. 文献清单筛选 + 导出到本地

### 1.1 目标
从 83 篇中分层筛选出一组代表样本（用于多模型对比）+ 一组全量工作集（用于最终综述）。

### 1.2 操作步骤

**A. 系统内查询并导出完整清单**

在浏览器打开 `http://localhost:8080/api/v1/literatures?province=北京&disease=麻疹&page_size=100`（或直接用 CSV 导出功能），导出为：

```
📂 work/beijing_measles_literatures.csv   ← 83 篇完整清单（含 id / title / year / journal / extraction_status / dp_cnt）
```

**B. 分层抽样选 20 篇代表样本**（用于 Step 2 多模型对比）：

```python
# 分层脚本（可直接在 backend 容器内跑）
# 分层维度：年代 × 研究人群 × 数据密度
layers = [
    # 年代层（每年代 3–4 篇）
    ("1980s",  1980, 1989, 3),
    ("1990s",  1990, 1999, 3),
    ("2000s",  2000, 2009, 3),
    ("2010s",  2010, 2019, 4),
    ("2020s",  2020, 2024, 4),
]
# 人群层偏好：健康人群血清学 > 育龄妇女/新生儿 > 病例暴发调查 > 医务人员
# 数据密度偏好：dp_cnt ≥ 20 的优先（信息密度高，模型对比信号强）
```

**C. 样本清单确认后记录**

```
📂 work/beijing_measles_sample_20.csv   ← 多模型对比子集（20 篇）
📂 work/beijing_measles_all_83.csv      ← 全量工作集（83 篇，Step 6 综述用）
```

### 1.3 验收
- [ ] 清单覆盖 1983–2024 全部年代
- [ ] 至少覆盖 8 个北京区县（朝阳 / 海淀 / 丰台 / 大兴 / 昌平 / 顺义 / 房山 / 通州）
- [ ] 至少包含 2 篇英文文献（系统已自动路由英文 prompt）
- [ ] 导出 CSV 含 literature_id 主键，便于后续步骤串联

---

## 2. 多模型 AI 提取 + 全程记录

### 2.1 目标
对 Step 1 选出的 20 篇代表样本，**用 3 个本地模型**各跑一遍提取，完整记录耗时、token 用量、数据点数量。

### 2.2 模型选择（建议 3 档，覆盖能力 / 速度 / 成本三个维度）

| 模型 | 参数量 | GPU 内存 | 定位 | Ollama 命令 |
|---|---|---|---|---|
| **qwen3.8:27b** | 27B | ~16 GB | 当前主力，精度上限锚点 | `ollama pull qwen3.8:27b`（已有） |
| **qwen2.5:14b** | 14B | ~8 GB | 速度 / 精度平衡位 | `ollama pull qwen2.5:14b` |
| **qwen2.5:7b**  | 7B  | ~4 GB | 极端速度，检测"下限噪声" | `ollama pull qwen2.5:7b` |

> 可选远程 API 作参考基准：deepseek-v4-flash（快）、gpt-4o-mini（外部基准）。但本方案**聚焦本地模型对比**，远程模型作为可选对照组。

### 2.3 操作步骤

**A. 确保 Ollama 在 Windows 本机运行**（不是在 Docker 里）

```powershell
# Windows PowerShell
ollama serve     # 后台常驻
ollama list      # 确认 3 个模型已拉取
```

**B. 配置 Docker 容器访问 Windows 主机 Ollama**

在 `.env` 或 docker-compose 里，backend/worker 的环境变量 `OLLAMA_BASE_URL` 设为：

```
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

Windows + Docker Desktop 下 `host.docker.internal` 即可解析到宿主机。

**C. 在系统前端执行批量多模型提取**

前端路径：`文献管理 → 批量操作 → 批量重新提取`

对 20 篇样本，按以下顺序跑 **3 遍**（每次选不同模型）：

| 轮次 | 模型 | 清除旧数据 | 备注 |
|---|---|---|---|
| 1 | qwen3.8:27b | ✅ 清 | 作为 GT / 主结果 |
| 2 | qwen2.5:14b | ✅ 清 | 写入 synthetic_extraction |
| 3 | qwen2.5:7b  | ✅ 清 | 写入 synthetic_extraction |

> **⚠️ 不要让 2/3 轮覆盖第 1 轮结果**。方案：第 1 轮跑完后，立即把第 1 轮数据点**导出备份**到本地 CSV；后续两轮走**合成自测（synthetic）多模型模式**，结果自动写入 `synthetic_extraction` 表而不污染 `data_point`。

**D. 提取耗时 / 用量自动记录**

系统会自动在 `extraction_history` 表记录每篇文献的：
- `duration_seconds`（耗时）
- `prompt_tokens` / `completion_tokens` / `total_tokens`
- `llm_call_count`（LLM 调用次数）
- `llm_cost_usd`（估算成本）
- `model`（使用的模型名）
- `status`（success / no_data / failed）

### 2.4 验收
- [ ] 20 篇 × 3 模型 = **60 条 extraction_history** 记录全部 status = success
- [ ] synthetic_extraction 表中有 20×2 = **40 条**对比提取记录
- [ ] 第一遍 qwen3.8:27b 的 data_point 已导出为本地 CSV 备份
- [ ] 每轮耗时已汇总（见 Step 3）

---

## 3. 多模型提取结果对比（数据点 + 耗时）

### 3.1 数据点数量对比（自动生成）

前端路径：`评估自测 → 多模型对比 → 选 20 篇样本 × 3 模型`

直接复用系统的多模型对比能力，输出：

| 文献 | qwen3.8:27b | qwen2.5:14b | qwen2.5:7b | GT 参考 |
|---|---|---|---|---|
| 丰台区2024麻疹… | 148 | ? | ? | 148 |
| 昌平区2013-2018… | 1 | ? | ? | 1 |
| ... | ... | ... | ... | ... |

**汇总指标**：
```
📂 work/model_comparison_summary.md
  ├─ 数据点数量对比表（每篇 × 每模型）
  ├─ 总体指标：召回率 / 精确率 / 平均数据点偏差率
  └─ 失败案例清单（某模型完全漏掉的关键数据点）
```

### 3.2 耗时 / 成本对比（从 extraction_history 查询）

SQL：

```sql
SELECT
  model,
  COUNT(*) AS lit_cnt,
  ROUND(AVG(duration_seconds), 1) AS avg_sec,
  ROUND(AVG(total_tokens), 0) AS avg_tokens,
  ROUND(SUM(llm_cost_usd), 3) AS total_cost_usd,
  ROUND(AVG(llm_call_count), 1) AS avg_calls
FROM extraction_history
WHERE literature_id IN (20 个样本 id)
GROUP BY model
ORDER BY avg_sec;
```

输出表格：

| 模型 | 平均耗时(s) | 平均 token | 总成本($) | 平均调用次数 |
|---|---|---|---|---|
| qwen2.5:7b  | ~20 | ~5k | ~0.0x | ~2 |
| qwen2.5:14b | ~60 | ~15k | ~0.0x | ~3 |
| qwen3.8:27b | ~170 | ~40k | ~0.xx | ~5 |

### 3.3 准确度对比（用 qwen3.8:27b 作为伪 GT）

对每篇样本，**人工抽读 3 个关键数据点**（阳性率 / GMT / 样本量），验证 qwen3.8:27b 是否正确。如果 3 个都对 → 把 qwen3.8:27b 的结果视作 GT 基准。然后对比另外两个模型：

```
召回率 = 正确命中的数据点数 / qwen3.8:27b 数据点数
精确率 = 正确命中的数据点数 / 该模型提取的总数据点数
```

### 3.4 验收
- [ ] 3.1 数据点数量对比表已生成
- [ ] 3.2 耗时 / token / 成本对比表已生成
- [ ] 3.3 召回率 / 精确率已算完
- [ ] 汇总写入 `work/model_comparison_summary.md`

---

## 4. 不同方法的效率与准确度综合评估

### 4.1 效率 × 准确度 二维矩阵

```
              准确度
               ↑
    高         │     ● qwen3.8:27b      ← 精度上限，速度慢
               │
    中         │            ● qwen2.5:14b  ← 平衡点
               │
    低         │                   ● qwen2.5:7b  ← 速度优先，漏点多
               └──────────────────────────────────→ 速度
                慢                         快
```

### 4.2 推荐结论（写入 `work/model_recommendation.md`）

> **推荐结论模板**：
> - 北京麻疹血清抗体研究推荐使用 **qwen3.8:27b** 作为主力模型，因为在 20 篇样本上召回率达 XX%，精确率 XX%，显著优于 qwen2.5:14b（XX% / XX%）和 qwen2.5:7b（XX% / XX%）。
> - 若 GPU 资源紧张，可先用 **qwen2.5:14b** 做初筛，再人工审核关键数据点，总成本降低约 YY%，准确度损失约 ZZ%。
> - 7B 模型不推荐用于血清抗体场景，漏检率超过 AA%，会导致年龄组 / 抗体类型细分数据缺失。

### 4.3 验收
- [ ] 二维矩阵图（可手绘或用 Python matplotlib 生成）
- [ ] 推荐结论文档
- [ ] 失败案例分析（某模型在哪些文献类型 / 哪些字段上特别容易错）

---

## 5. 数据点综合审核（1464 条 pending）

### 5.1 审核策略（**关键优化**：不逐条审，分层处理）

| 数据点子集 | 数量 | 审核方式 | 通过标准 |
|---|---|---|---|
| qwen3.8:27b 提取 + quality_score ≥ 70 | ~800 | **批量批准**（一键 approve） | 高置信度直接放行 |
| qwen3.8:27b + quality_score 40–69 | ~500 | **重点抽查**（按文献维度审） | 每篇抽 3 条，全对则整篇通过 |
| qwen2.5:14b / 7b 提取 | ~100 | **逐条审核** | 与 qwen3.8:27b 交叉比对 |
| quality_score < 40 | ~64 | **逐条驳回** | 低质量信号直接 reject |

### 5.2 快速批量批准（SQL 脚本）

```sql
-- Step 1: 批量批准 qwen3.8:27b 高置信度数据点
UPDATE data_point
SET review_status = 'approved', updated_at = NOW()
WHERE literature_id IN (SELECT id FROM literature WHERE province = '北京')
  AND disease IN ('measles', '麻疹')
  AND quality_score >= 70;

-- Step 2: 批量驳回低质量
UPDATE data_point
SET review_status = 'rejected', updated_at = NOW()
WHERE literature_id IN (SELECT id FROM literature WHERE province = '北京')
  AND disease IN ('measles', '麻疹')
  AND quality_score < 40;
```

### 5.3 重点抽查（前端交互）

前端路径：`数据分析 → 数据审核 → 按文献维度展开`

对 quality_score 40–69 的文献，每篇抽 3 条关键数据点（阳性率 / GMT / 样本量），对照原文 PDF 验证。全对 → 批量 approve；有错 → 标注后逐条审。

### 5.4 最终审核结果快照

审核完成后导出：
```
📂 work/beijing_measles_approved_data_points.csv   ← 批准后约 1400 条
```

### 5.5 验收
- [ ] approved / rejected / pending 比例达到 **≥ 90% 已审核**
- [ ] 无单篇文献 pending > 5 条（残留 pending 是可接受的噪声）
- [ ] 批准后的数据点 quality_score 分布 P50 ≥ 60

---

## 6. 北京麻疹血清抗体流行病学研究

### 6.1 数据准备（基于 Step 5 批准后的数据集）

在浏览器 `http://localhost:8080/analysis` 直接用系统可视化，或导出 CSV 用 Python 分析：

```sql
-- 审核通过的北京麻疹血清抗体数据
SELECT * FROM data_point
WHERE disease IN ('measles', '麻疹')
  AND province = '北京'
  AND review_status = 'approved'
ORDER BY collection_year, age_min;
```

### 6.2 分析维度（建议覆盖）

| # | 维度 | 具体分析 | 输出图 |
|---|---|---|---|
| 1 | **时间趋势** | 1983–2024 年麻疹抗体阳性率变化；2005 年强化免疫、2010 年消除麻疹验证、2020 年新冠影响 | 折线图（year × positive_rate） |
| 2 | **年龄组分布** | ≤1 岁 / 2–4 岁 / 5–9 岁 / 10–14 岁 / 15–19 岁 / 20–39 岁 / ≥40 岁各年龄组阳性率差异 | 堆叠柱状图 |
| 3 | **人群差异** | 健康人群 vs 育龄妇女 vs 新生儿脐带血 vs 医务人员 vs 流动人口 | 分组箱线图 |
| 4 | **区县差异** | 城六区 vs 郊区县（大兴 / 房山 / 顺义 / 昌平）阳性率对比 | 地图或条形图 |
| 5 | **抗体类型** | IgG 阳性率 vs GMT 几何平均滴度；有无同时记录 IgM 的暴发期数据 | 散点图 + 箱线图 |
| 6 | **接种策略效果** | 强化免疫前后（2004 / 2010 / 2020）同一人群抗体水平变化 | 配对折线图 |
| 7 | **保护阈值评估** | 阳性率 ≥ 85%（WHO 麻疹免疫阈值）的年代与年龄组覆盖率 | 热力图 |

### 6.3 Python 分析脚本（可选，如需补充系统内置图表）

```python
# work/analysis_scripts/01_time_trend.py
import pandas as pd, matplotlib.pyplot as plt, seaborn as sns

df = pd.read_csv('work/beijing_measles_approved_data_points.csv')
# 对每个 collection_year 汇总 weighted positive_rate（按 sample_size 加权）
weighted = (df.groupby('collection_year').apply(
    lambda g: (g['value'] * g['sample_size']).sum() / g['sample_size'].sum()
)).reset_index(name='weighted_positive_rate')

plt.figure(figsize=(12, 5))
plt.plot(weighted['collection_year'], weighted['weighted_positive_rate'],
         marker='o', color='#c0392b', linewidth=2)
plt.axhline(y=85, linestyle='--', color='gray', label='WHO 保护阈值 85%')
plt.title('北京麻疹抗体阳性率时间趋势（加权）')
plt.ylabel('加权阳性率 (%)'); plt.xlabel('年份')
plt.legend(); plt.tight_layout()
plt.savefig('work/figures/01_time_trend.png', dpi=200)
```

### 6.4 验收
- [ ] 7 个维度的分析图表全部生成
- [ ] 每张图配 2–3 句关键发现文字
- [ ] 所有图表汇总到 `work/figures/` 目录 + `work/analysis_findings.md`

---

## 7. 研究论文撰写

### 7.1 建议目标期刊与格式

| 项 | 值 |
|---|---|
| 目标期刊（国内） | 《中华流行病学杂志》《中国疫苗和免疫》《公共卫生与预防医学》 |
| 目标期刊（SCI） | *Vaccine*（IF 4.8）、*BMC Infectious Diseases*（IF 3.6）、*PLOS Neglected Tropical Diseases*（麻疹专题） |
| 字数 | 中文 6000–8000 / 英文 3500–5000 |
| 图表数 | 6–8 张 + 2–3 个补充表 |

### 7.2 论文结构（中文模板）

```
标题：北京市 1983–2024 年麻疹血清抗体流行特征及免疫效果评价 —— 基于
      AI 辅助文献数据挖掘的系统综述

摘要（300 词）
  背景 / 方法 / 结果 / 结论 四要素

引言（800 词）
  - 麻疹消除背景（WHO 2020 验证）
  - 北京市麻疹防控简史（1965 年麻疹疫苗 → 1978 年扩免 → 2004/2010 强化）
  - 血清流行病学数据碎片化问题 → AI 辅助挖掘的必要性

资料与方法（1200 词）
  - 文献来源（antibody_map 数据库自建库 + 补充 CNKI / PubMed 2020–2024 新文献）
  - AI 辅助数据提取流程（qwen3.8:27b 为主力，多模型交叉验证）
  - 数据质量控制（双独立审核 + 原文溯源）
  - 统计方法（加权阳性率、年龄组标准化、Meta 分析合并效应量）

结果（2500 词）—— 附 6 张主图
  7.2.1 文献基本特征（83 篇 / 1536 条数据点的分布）
  7.2.2 时间趋势（1983–2024 阳性率变化）
  7.2.3 年龄组分布差异
  7.2.4 人群亚组比较
  7.2.5 区县空间差异
  7.2.6 接种策略效果评估

讨论（1200 词）
  - 北京麻疹抗体水平长期演变规律
  - 与国内外同类研究的异同
  - AI 辅助提取的优势与局限（召回率 / 精确率结论）
  - 政策建议（强化免疫 / 流动人口 / 新生儿母传抗体）

结论（200 词）

参考文献（40–60 篇）

附录
  - A. 83 篇纳入文献清单
  - B. qwen3.8:27b vs qwen2.5:14b vs qwen2.5:7b 多模型对比完整数据
  - C. 数据字段定义与来源页定位
```

### 7.3 写作辅助

- **引用格式**：antibody_map 数据库可自动导出 GB/T 7714 / Vancouver 格式文献列表
- **图表**：Step 6 生成的 PNG 可直接插入 Word / LaTeX
- **AI 辅助润色**：论文初稿完成后，用 qwen3.8:27b 做 3 次循环润色（学术性 → 逻辑 → 语言）

### 7.4 验收
- [ ] 中文稿完整（6000+ 词，含 6 主图 + 2 附表）
- [ ] 参考文献 40+ 篇，其中 2020 年后 ≥ 10 篇
- [ ] 摘要四要素齐全，结论与数据一致
- [ ] 论文元数据（文献来源 / AI 辅助方法 / 数据质量控制）已披露

---

## 附录 A：推荐执行顺序与并行度

```
Day 1 ──┤ Step 1 清单筛选（1h） + Step 2 Ollama 拉模型（后台跑）
        └─ 启动后台：3 个模型 ollama pull + Docker 容器改 OLLAMA_BASE_URL + 重建

Day 2 ──┤ Step 2 三轮批量提取（20 篇 × 3 模型 × ~3min/篇 = ~3h）
        └─ 提取间可间歇跑 Step 5 批量批准 SQL

Day 3 ──┤ Step 3 对比分析（2h） + Step 5 重点抽查（4h，需读原文）

Day 4 ──┤ Step 6 流行病学分析（3h） + Step 4 效率评估（1h）

Day 5 ──┤ Step 7 论文初稿（6h）

Day 6–7 ─┤ 论文润色 + 参考文献核对 + 图表最终调整

总耗时 ~50–60 人工时 + 8h GPU（三轮提取）
```

## 附录 B：产出文件清单

```
📂 work/
├─ beijing_measles_literatures.csv         # Step 1 全量清单
├─ beijing_measles_sample_20.csv          # Step 1 多模型样本
├─ model_comparison_summary.md             # Step 3 对比汇总
├─ model_recommendation.md                 # Step 4 模型推荐
├─ beijing_measles_approved_data_points.csv # Step 5 审核后最终数据集
├─ analysis_findings.md                    # Step 6 分析关键发现
├─ figures/                                # Step 6 图表
│  ├─ 01_time_trend.png
│  ├─ 02_age_group_distribution.png
│  ├─ 03_population_comparison.png
│  ├─ 04_district_heatmap.png
│  ├─ 05_antibody_type_scatter.png
│  ├─ 06_vaccination_before_after.png
│  └─ 07_protection_threshold_heatmap.png
└─ 论文/
   ├─ 麻疹血清抗体_研究论文_中文_v1.docx
   ├─ 图表源数据.xlsx
   └─ 参考文献列表.txt
```

## 附录 C：风险与预案

| 风险 | 概率 | 预案 |
|---|---|---|
| Ollama 27B 模型显存溢出（24GB 卡） | 中 | 降到 batch_size=1 或换 qwen2.5:32b 4-bit |
| 2020–2024 新文献 CNKI 无 PDF | 中 | 手动下载后上传文件夹监控，触发自动入库和提取 |
| qwen2.5:7b 漏检率过高无法对比 | 低 | 保留 14b vs 27b 两档对比，7b 做纯参考 |
| 1464 条 pending 人工审核量过大 | 中 | 用 Step 5.2 批量批准 SQL 先清掉 ~80%，剩余精审 |
| 新冠疫情期间（2020–2022）文献少 | 已知 | 讨论里重点分析新冠对麻疹监测的影响，作为文章亮点 |
