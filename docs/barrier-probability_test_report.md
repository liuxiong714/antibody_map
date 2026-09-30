# 免疫屏障达标概率端点测试报告

> 目标：验证新增端点 `GET /api/v1/analysis/barrier-probability`，确认 Monte Carlo 不确定性量化能正确输出「达标概率」替代「达标/不达标」二元结论。
>
> 特征：**正面率贴近 HIT 阈值 + 样本量差异**，用于验证不确定性被正确反映。

---

## 1. 测试环境

| 项目 | 值 |
| --- | --- |
| 后端镜像 | `antibody_map-backend`（最新重建） |
| 容器状态 | `antibody-backend` Up (healthy) |
| 采样次数配置 | `IMMUNITY_MC_SAMPLES = 1000` |
| 采样实现 | `backend/app/core/uncertainty_quantification.py`（Beta 分布，仅 numpy） |
| 请求认证 | JWT Bearer Token（容器内用 `create_access_token` 签发） |

---

## 2. 测试数据

向数据库中临时插入 8 条「已审核」的 `seroprevalence`（血清阳性率）数据点，`disease = measles`（麻疹），阳性率统一取 `value = 94.0%`（贴近麻疹 HIT）。

麻疹 HIT 参考：WHO = 95%，文献 R0（typical=15）→ 1 − 1/15 ≈ 93.3%。

### 2.1 测试省 A：小样本（提示不确定）

| 数据点 | disease | province | data_type | value (%) | sample_size | age_min | age_max | review_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | measles | 测试省_uncq_small | seroprevalence | 94.0 | 25 | 0 | 4 | approved |
| 2 | measles | 测试省_uncq_small | seroprevalence | 94.0 | 25 | 5 | 14 | approved |
| 3 | measles | 测试省_uncq_small | seroprevalence | 94.0 | 25 | 15 | 39 | approved |
| 4 | measles | 测试省_uncq_small | seroprevalence | 94.0 | 25 | 40 | 59 | approved |

- 总样本量：**100**

### 2.2 测试省 B：大样本（更确定）

| 数据点 | disease | province | data_type | value (%) | sample_size | age_min | age_max | review_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | measles | 测试省_uncq_big | seroprevalence | 94.0 | 2500 | 0 | 4 | approved |
| 2 | measles | 测试省_uncq_big | seroprevalence | 94.0 | 2500 | 5 | 14 | approved |
| 3 | measles | 测试省_uncq_big | seroprevalence | 94.0 | 2500 | 15 | 39 | approved |
| 4 | measles | 测试省_uncq_big | seroprevalence | 94.0 | 2500 | 40 | 59 | approved |

- 总样本量：**10000**

> 说明：以上数据为一次性临时插入，验证完成后已从数据库删除（`DELETE 8`），不影响既有数据。

---

## 3. 请求参数

`GET /api/v1/analysis/barrier-probability`

| 参数 | 类型 | 必填 | 值 |
| --- | --- | --- | --- |
| `disease` | string | 是 | `measles` |
| `province` | string | 是 | `测试省_uncq_small` / `测试省_uncq_big` |

请求头：

```
Authorization: Bearer <JWT Token>
Accept: application/json
```

示例：

```
GET http://localhost:8000/api/v1/analysis/barrier-probability?disease=measles&province=%E6%B5%8B%E8%AF%95%E7%9C%81_uncq_small
```

---

## 4. 返回结果

### 4.1 测试省 A：小样本（n=100）

**HTTP 200**

```json
{
  "province": "测试省_uncq_small",
  "disease": "measles",
  "n_data_points": 4,
  "total_samples": 100,
  "pass_probability": 0.157,
  "primary_threshold_source": "who",
  "per_threshold": {
    "who": {
      "threshold": 0.95,
      "pass_probability": 0.157
    },
    "r0_lit": {
      "threshold": 0.9333,
      "pass_probability": 0.424
    }
  },
  "recommended_action": "补种",
  "hit_thresholds": {
    "foi": null,
    "who": 95.0,
    "r0_lit": 93.33
  },
  "weighted_mean": 92.57,
  "weighted_ci": [
    86.94,
    96.77
  ],
  "fusion_hit": {
    "mean": 94.16,
    "ci_low": 93.33,
    "ci_high": 95.0
  },
  "sampling": {
    "n_samples": 1000,
    "n_groups": 4
  },
  "action_rule": "pass_probability < 0.5 → 补种；0.5~0.8 → 监测；>0.8 → 达标",
  "notes": [],
  "meta": {
    "methodology_note": "基于已审核血清学估计进行barrier_probability（疾病=measles、省份=测试省_uncq_small）；2026-08-27 数据快照。"
  }
}
```

### 4.2 测试省 B：大样本（n=10000）

**HTTP 200**

```json
{
  "province": "测试省_uncq_big",
  "disease": "measles",
  "n_data_points": 4,
  "total_samples": 10000,
  "pass_probability": 0.0,
  "primary_threshold_source": "who",
  "per_threshold": {
    "who": {
      "threshold": 0.95,
      "pass_probability": 0.0
    },
    "r0_lit": {
      "threshold": 0.9333,
      "pass_probability": 0.998
    }
  },
  "recommended_action": "补种",
  "hit_thresholds": {
    "foi": null,
    "who": 95.0,
    "r0_lit": 93.33
  },
  "weighted_mean": 93.98,
  "weighted_ci": [
    93.55,
    94.42
  ],
  "fusion_hit": {
    "mean": 94.16,
    "ci_low": 93.33,
    "ci_high": 95.0
  },
  "sampling": {
    "n_samples": 1000,
    "n_groups": 4
  },
  "action_rule": "pass_probability < 0.5 → 补种；0.5~0.8 → 监测；>0.8 → 达标",
  "notes": [],
  "meta": {
    "methodology_note": "基于已审核血清学估计进行barrier_probability（疾病=measles、省份=测试省_uncq_big）；2026-08-27 数据快照。"
  }
}
```

---

## 5. 结果对比分析

| 指标 | 小样本 (n=100) | 大样本 (n=10000) | 说明 |
| --- | --- | --- | --- |
| `pass_probability` | **0.157** | **0.0** | 同一 94% 阳性率：小样本给出歧义居中的概率；大样本收敛到更明确的结论 |
| `weighted_mean` | 92.57% | 93.98% | 大样本均值更接近真实值 94% |
| `weighted_ci`（95%） | [86.94, 96.77] | [93.55, 94.42] | 小样本区间宽 ≈10 点（不确定）；大样本区间窄 ≈0.9 点（确定） |
| `recommended_action` | 补种 | 补种 | 主阈值 WHO=95% 下均未达标（0.157 / 0.0 < 0.5） |

### 输出解读

- 主阈值为 `who = 95%`；`foi` 为 `null`（该数据未产出 FOI 估计，符合 FOI > WHO > 文献 R0 优先级，自动回退）。
- 小样本因置信区间较宽（约 ±5%），`pass_probability = 0.157`，**处于 (0,1) 非极端值**，正确反映了不确定性。
- 大样本区间显著收窄，`pass_probability = 0.0`，输出更「确定」。

---

## 6. 验收结论

| 验收标准 | 结果 | 是否通过 |
| --- | --- | --- |
| 1. 阳性率贴近阈值、样本量较小 → `pass_probability` 在 0~1 且非极端（非 0/1） | `0.157`，区间 `[86.9, 96.8]` | ✅ |
| 2. 同数据下，样本量大 → 更「确定」（更接近 0 或 1） | `0.157 → 0.0`，区间收窄到 `[93.6, 94.4]` | ✅ |
| 3. API 返回 200，JSON 含 `pass_probability` 与 `recommended_action` | 两个请求均 HTTP 200，字段齐全 | ✅ |

**结论：免疫屏障评估的不确定性量化端点工作正常，达标概率正确反映数据不确定性。**

---

## 7. 清理说明

- 临时插入的 8 条测试数据点已删除（`DELETE 8`）。
- 临时脚本（seed / verify / cleanup）已删除。
- 未改动任何既有业务数据。