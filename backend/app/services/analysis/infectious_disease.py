"""Submodule of app.services.analysis (split from analysis_service.py)."""



from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.immunity_dynamics import (
    DEFAULT_BARRIER_THRESHOLD,
    DEFAULT_BIRTH_COHORT_SIZE,
    DEFAULT_PROJECTION_YEARS,
    DEFAULT_WANING_RATE,
    estimate_waning_rate,
    project_barrier,
)
from app.core.stats_engine import (
    fit_catalytic_models,
)
from app.core.term_normalizer import normalize_disease, normalize_province
from app.core.uncertainty_quantification import (
    barrier_probability,
    fusion_hit,
    sample_positivity,
)
from app.models.data_point import DataPoint
from app.services.analysis._common import (
    AGE_GROUPS,
    R0_REFERENCE,
    WHO_THRESHOLDS,
    _barrier_status_from_rate,
    _barrier_status_with_message,
    _build_base_query,
    _build_catalytic_records,
    _build_hit_threshold_families,
    _calc_foi_from_sp,
    _calc_hit_from_r0,
    _calc_r0_from_foi,
    _calc_ve_from_sp,
    _calc_weighted_positivity,
    _catalytic_r0_hit,
    _get_age_group_label,
    _get_reference_coverage,
    _implied_coverage_from_hit,
    _midpoint_age,
    _resolve_hit_target,
    _split_vax_unvax,
    logger,
)
from app.services.goal_threshold_service import get_goal_threshold


async def get_simulation(
    db: AsyncSession,
    disease: str | None = None,
    province: str | None = None,
    assumed_coverage: float = 90.0,
    booster_rate: float = 0.0,
    ve: float = 1.0,
) -> dict:
    """免疫屏障模拟（复用 FOI 催化模型反推）。

    1. 用观测血清阳性率经催化模型反推平均 FOI → 估计 R0 → HIT；
    2. 给定假设接种覆盖（assumed_coverage）、加强针比例（booster_rate）
       与疫苗保护效率（ve，默认 1.0），模拟有效免疫比例：
         protective = cov·ve                          # 疫苗实际贡献的保护比例 (%)
         effective  = protective + (1 − protective/100) × booster  # 加强针作用于未被基础覆盖者
    3. 对比 HIT 判定屏障状态，并反推「需达到的基础覆盖」。
    """
    empty = {
        "disease": disease,
        "province": province,
        "assumed_coverage_percent": assumed_coverage,
        "booster_rate_percent": booster_rate,
        "ve_used": ve,
        "current": None,
        "simulated": None,
        "required_coverage_to_reach_hit": None,
        "notes": ["无已审核通过的血清阳性率数据，无法进行 FOI 反推"],
    }
    query = _build_base_query(disease, province, None, None, None, None,
                              data_type="seroprevalence", review_status="approved",
                              include_subgroups=False)
    result = await db.execute(query)
    rows = result.scalars().all()
    if not rows:
        return empty

    # 观测免疫水平（样本量加权）
    current_sp = _calc_weighted_positivity(rows)["weighted_positivity"]

    # FOI：每点催化模型 → 样本量加权平均 FOI → R0 → HIT
    foi_tuples = []
    for r in rows:
        if r.value is None:
            continue
        mid = _midpoint_age(r.age_min, r.age_max)
        if mid is None:
            continue
        foi = _calc_foi_from_sp(float(r.value), mid)
        if foi is not None:
            foi_tuples.append((foi, float(r.sample_size or 1)))
    foi_avg = None
    if foi_tuples:
        w = sum(wt for _, wt in foi_tuples)
        foi_avg = round(sum(v * wt for v, wt in foi_tuples) / w, 6) if w > 0 else None

    estimated_r0 = _calc_r0_from_foi(foi_avg) if foi_avg is not None else None
    hit_from_foi = _calc_hit_from_r0(estimated_r0) if estimated_r0 is not None else None

    dis_key = normalize_disease(disease or "") or (disease or "")
    r0_ref = R0_REFERENCE.get(dis_key)
    reference_hit = _calc_hit_from_r0(r0_ref[0]) if r0_ref else None
    goal_threshold = await get_goal_threshold(db, dis_key)
    who_threshold = WHO_THRESHOLDS.get(dis_key)

    # 屏障目标：优先 FOI 估计，否则 GOAL/WHO 阈值，再退到文献 R0
    hit_target = hit_from_foi or goal_threshold or who_threshold or reference_hit

    def _status(sp: float | None, target: float | None) -> str:
        if sp is None or target is None:
            return "undetermined"
        if sp >= target:
            return "reached"
        if sp >= target - 10:
            return "near"
        return "not_reached"

    current_status = _status(current_sp, hit_target)
    current = {
        "weighted_positivity_percent": current_sp,
        "weighted_avg_foi_per_year": foi_avg,
        "estimated_r0": estimated_r0,
        "r0_reference": {"typical": r0_ref[0] if r0_ref else None,
                         "range_low": r0_ref[1] if r0_ref else None,
                         "range_high": r0_ref[2] if r0_ref else None},
        "hit_percent": hit_target,
        "status": current_status,
    }

    # 模拟有效免疫比例（基础接种仅 ve 部分真正提供保护；加强针作用于未被保护者）
    cov = max(0.0, min(100.0, float(assumed_coverage)))
    boost = max(0.0, min(100.0, float(booster_rate)))
    v_clamped = max(0.0, min(1.0, float(ve)))         # VE 钳位 [0, 1]
    protective = cov * v_clamped                       # 基础接种贡献的保护比例 (%)
    effective = protective + (1.0 - protective / 100.0) * boost   # 单位 %
    sim_status = _status(effective, hit_target)
    gain = effective - protective                      # 加强针带来的额外保护
    simulated = {
        "effective_coverage_percent": round(effective, 2),
        "protective_coverage_percent": round(protective, 2),
        "ve_used": v_clamped,
        "hit_percent": hit_target,
        "gap_to_hit_percent": round(hit_target - effective, 2) if hit_target is not None else None,
        "gain_from_booster_percent": round(gain, 2),
        "status": sim_status,
    }

    # 反推：给定 booster + ve 下达到 HIT 所需的基础覆盖
    # h = cv + (1−cv)·b  →  c = (h − b) / (v·(1 − b))
    required = None
    if hit_target is not None:
        hit_ratio = hit_target / 100.0
        b_ratio = boost / 100.0
        if v_clamped <= 0:
            required = None  # VE=0，任何覆盖都没用
        elif b_ratio >= 1.0:
            required = 0.0 if hit_ratio <= 1.0 else None
        elif hit_ratio <= b_ratio:
            required = 0.0
        else:
            required = round((hit_ratio - b_ratio) / (v_clamped * (1.0 - b_ratio)) * 100.0, 2)
            if required > 100.0:
                required = None  # 仅靠基础接种无法达标（即使 100% 也不够）

    notes = []
    if hit_target is None:
        notes.append("无法估计 HIT（无 FOI 数据且无 GOAL/WHO/文献阈值），屏障状态为 undetermined")
    if v_clamped >= 0.999:
        notes.append("VE=1.0 为兼容旧行为的默认值；实际各病种疫苗保护效率不同，建议按病种传入更合理的 ve（如 0.7~0.9）")
    if current_status != "reached" and sim_status == "reached":
        notes.append(f"在当前假设（覆盖 {cov}% × VE {v_clamped:.2f} + 加强 {boost}%）下模拟可达群体免疫（≥{hit_target}%）")
    if (
        hit_from_foi is not None and r0_ref and estimated_r0 is not None
        and (estimated_r0 < r0_ref[1] * 0.3 or estimated_r0 > r0_ref[2] * 2)
    ):
        notes.append("基于 FOI 的 R0 估计超出文献参考区间，模拟结果需谨慎解读")

    return {
        "disease": disease,
        "province": province,
        "assumed_coverage_percent": cov,
        "booster_rate_percent": boost,
        "ve_used": v_clamped,
        "current": current,
        "simulated": simulated,
        "required_coverage_to_reach_hit": required,
        "notes": notes,
    }


# 七普 2020 全国总人口（官方，单位：人）——用于补种人数分母粗估
# 注：省级/分年龄总人口不在当前数据集，补种人数为全国平均近似
_POP_2020_NATIONAL = 1_411_780_000.0


async def get_barrier_scenarios(
    db: AsyncSession,
    disease: str | None = None,
    province: str | None = None,
    scenarios: list[dict] | None = None,
) -> dict:
    """多情景免疫屏障模拟：对每个 {coverage, booster, ve} 计算 effective、R_eff、是否达 HIT。

    VE 口径（复用 get_simulation）：
        protective = coverage × ve                (%)
        effective  = protective + (1 − protective/100) × booster
    R_eff 口径（复用 core.effective_immunity.r_eff）：
        构造 NGM 残差矩阵 K = NGM · diag(1 − p)，p 为各年龄组有效保护比例，
        R_eff = r0 × ρ(K) / ρ(NGM)

    补种人数：
        gap = max(0, required_coverage_for_hit − scenario.coverage) (%)
        补种人数 = gap / 100 × POP_2020_NATIONAL
        注：分母为七普全国总人口（省级/年龄分层人口暂无数据），属全国平均粗估。
    """
    empty = {
        "disease": disease,
        "province": province,
        "scenarios": [],
        "hit_target_percent": None,
        "hit_target_source": "none",
        "r0_estimated_from_foi": None,
        "r0_reference": None,
        "population_used": _POP_2020_NATIONAL,
        "population_note": (
            "补种人数分母基于七普 2020 全国总人口 14.12 亿的全国平均粗估；"
            "省级/年龄分层人口暂无数据，结果仅供参考"
        ),
        "notes": [],
    }

    # 默认情景（前端不传时的内置三条：基线 / 高覆盖 / 加强）
    if not scenarios:
        scenarios = [
            {"name": "baseline",  "coverage": 80.0, "booster": 0.0,  "ve": 1.0},
            {"name": "high_cov",  "coverage": 95.0, "booster": 0.0,  "ve": 1.0},
            {"name": "booster",   "coverage": 80.0, "booster": 50.0, "ve": 1.0},
        ]

    # 情景清洗（缺失字段钳位）
    cleaned: list[dict] = []
    for idx, s in enumerate(scenarios):
        name = s.get("name") or f"scenario_{idx + 1}"
        cov = max(0.0, min(100.0, float(s.get("coverage", 0.0))))
        boost = max(0.0, min(100.0, float(s.get("booster", 0.0))))
        ve = max(0.0, min(1.0, float(s.get("ve", 1.0))))
        cleaned.append({"name": name, "coverage": cov, "booster": boost, "ve": ve})

    # --- 查血清流行数据 → FOI 反推 → R0 → HIT（复用 get_simulation 口径）---
    query = _build_base_query(
        disease, province, None, None, None, None,
        data_type="seroprevalence", review_status="approved", include_subgroups=False,
    )
    result = await db.execute(query)
    rows = result.scalars().all()
    dis_key = normalize_disease(disease or "") or (disease or "")

    foi_avg: float | None = None
    estimated_r0: float | None = None
    hit_from_foi: float | None = None
    r0_ref = R0_REFERENCE.get(dis_key)
    reference_hit = _calc_hit_from_r0(r0_ref[0]) if r0_ref else None
    goal_threshold = await get_goal_threshold(db, dis_key)
    who_threshold = WHO_THRESHOLDS.get(dis_key)
    hit_target: float | None
    hit_source: str

    if rows:
        foi_tuples = []
        for r in rows:
            if r.value is None:
                continue
            mid = _midpoint_age(r.age_min, r.age_max)
            if mid is None:
                continue
            foi = _calc_foi_from_sp(float(r.value), mid)
            if foi is not None:
                foi_tuples.append((foi, float(r.sample_size or 1)))
        if foi_tuples:
            w = sum(wt for _, wt in foi_tuples)
            foi_avg = round(sum(v * wt for v, wt in foi_tuples) / w, 6) if w > 0 else None
        estimated_r0 = _calc_r0_from_foi(foi_avg) if foi_avg is not None else None
        hit_from_foi = _calc_hit_from_r0(estimated_r0) if estimated_r0 is not None else None
        hit_target, hit_source = _resolve_hit_target(
            hit_from_foi, who_threshold, reference_hit, dis_key,
        )
    else:
        hit_target = goal_threshold or who_threshold or reference_hit
        # _resolve_hit_target 没拿到 rows 给的 foi_hit → 简化处理
        if hit_target is goal_threshold:
            hit_source = "goal"
        elif hit_target is who_threshold:
            hit_source = "who"
        elif hit_target is reference_hit:
            hit_source = "literature_r0"
        else:
            hit_source = "none"

    # --- 加载接触矩阵（用于 r_eff 计算）---
    C = None
    age_groups_contact: list[str] = []
    try:
        from app.core.effective_immunity import (
            AGE_GROUPS_CONTACT,
            load_contact_matrix,
            r_eff,
        )
        C = load_contact_matrix()
        age_groups_contact = list(AGE_GROUPS_CONTACT)
    except Exception as _exc:  # noqa: BLE001
        logger.info(f"[BarrierScenarios] 未加载接触矩阵: {_exc.__class__.__name__}: {_exc}")

    scenario_results: list[dict] = []
    any_r_eff_computed = False
    for sc in cleaned:
        cov = sc["coverage"]
        boost = sc["booster"]
        ve = sc["ve"]

        # VE 口径（与 get_simulation 完全一致）
        protective = cov * ve                                      # %
        effective_percent = protective + (1.0 - protective / 100.0) * boost  # %
        effective_ratio = effective_percent / 100.0                 # 0-1

        # --- required_coverage 反推（复用 get_simulation 公式）---
        required_cov: float | None = None
        if hit_target is not None:
            h = hit_target / 100.0
            b = boost / 100.0
            if ve <= 0:
                required_cov = None
            elif b >= 1.0:
                required_cov = 0.0 if h <= 1.0 else None
            elif h <= b:
                required_cov = 0.0
            else:
                required_cov = round((h - b) / (ve * (1.0 - b)) * 100.0, 2)
                if required_cov > 100.0:
                    required_cov = None

        # --- 补种人数 ---
        vaccinate_gap = None
        vaccinate_people = None
        if required_cov is not None:
            vaccinate_gap = max(0.0, required_cov - cov)
            vaccinate_people = round(vaccinate_gap / 100.0 * _POP_2020_NATIONAL)

        # --- R_eff（用接触矩阵残差 NGM）---
        r_eff_val: float | None = None
        met: bool | None = None
        r_eff_details: dict = {}
        if C is not None and estimated_r0 is not None and age_groups_contact:
            # 均匀免疫近似：scenario 未指定年龄异质 → 所有年龄组 p = effective_ratio
            # （实际传播中儿童/成人的暴露率、易感人群结构不同，这里做同质性假设）
            pos_dict = {g: effective_ratio * 100.0 for g in age_groups_contact}
            res = r_eff(pos_dict, C, r0=float(estimated_r0))
            r_eff_val = res["r_eff"]
            met = res["herd_immunity_met"]
            r_eff_details = {
                "r_eff": r_eff_val,
                "herd_immunity_met": met,
                "rho_ngm": res.get("rho_ngm"),
                "rho_k": res.get("rho_k"),
                "assumption": (
                    "各年龄组有效免疫比例取均匀值（scenario 未指定年龄异质，"
                    "假设基础接种与加强针在各年龄组等比例覆盖）"
                ),
            }
            any_r_eff_computed = True
        elif rows and estimated_r0 is not None:
            # 没有接触矩阵 → 用均匀免疫解析解 R_eff = r0 × (1 − p)
            r_eff_val = round(float(estimated_r0) * (1.0 - effective_ratio), 4)
            met = r_eff_val < 1.0
            r_eff_details = {
                "r_eff": r_eff_val,
                "herd_immunity_met": met,
                "assumption": (
                    "无接触矩阵 → 用均匀免疫解析解 R_eff = R0 × (1 − p)"
                ),
            }
            any_r_eff_computed = True

        scenario_results.append({
            "name": sc["name"],
            "coverage_percent": cov,
            "booster_percent": boost,
            "ve_used": ve,
            "protective_coverage_percent": round(protective, 2),
            "effective_barrier_percent": round(effective_percent, 2),
            "effective_barrier_ratio": round(effective_ratio, 6),
            "r_eff": r_eff_val,
            "herd_immunity_met": met,
            "hit_target_percent": hit_target,
            "hit_gap_percent": (
                round(hit_target - effective_percent, 2)
                if hit_target is not None else None
            ),
            "status": _scenario_status(effective_percent, hit_target),
            "required_coverage_to_reach_hit": required_cov,
            "vaccinate_gap_percent": round(vaccinate_gap, 2) if vaccinate_gap is not None else None,
            "vaccinate_people": vaccinate_people,
            **r_eff_details,
        })

    # --- 返回结构 ---
    return {
        "disease": dis_key,
        "province": province,
        "hit_target_percent": hit_target,
        "hit_target_source": hit_source,
        "r0_estimated_from_foi": estimated_r0,
        "r0_reference": {
            "typical": r0_ref[0] if r0_ref else None,
            "range_low": r0_ref[1] if r0_ref else None,
            "range_high": r0_ref[2] if r0_ref else None,
        },
        "foi_avg_per_year": foi_avg,
        "population_used": _POP_2020_NATIONAL,
        "population_note": (
            "补种人数分母基于七普 2020 全国总人口 14.12 亿的全国平均粗估；"
            "省级/年龄分层人口暂无数据，结果仅供参考"
        ),
        "r_eff_contact_matrix_used": C is not None,
        "scenarios": scenario_results,
        "notes": _build_scenarios_notes(
            hit_target=hit_target, hit_source=hit_source,
            any_r_eff=any_r_eff_computed, rows_count=len(rows) if rows else 0,
        ),
    }


def _scenario_status(effective_percent: float | None, hit_target: float | None) -> str:
    if effective_percent is None or hit_target is None:
        return "undetermined"
    if effective_percent >= hit_target:
        return "reached"
    if effective_percent >= hit_target - 10:
        return "near"
    return "not_reached"


def _build_scenarios_notes(
    hit_target: float | None,
    hit_source: str,
    any_r_eff: bool,
    rows_count: int,
) -> list[str]:
    notes: list[str] = []
    if rows_count == 0:
        notes.append("无已审核通过的血清阳性率数据，R0 无法从 FOI 反推，补种人数与 r_eff 基于文献 R0")
    if hit_target is None:
        notes.append("无法确定 HIT 阈值（无 FOI 反推结果、无 GOAL/WHO/文献 R0）")
    else:
        src_map = {"mle_foi": "FOI 反推", "who": "WHO 官方阈值",
                   "literature_r0": "文献 R0", "goal": "目标阈值", "none": "无"}
        notes.append(f"HIT 阈值来源：{src_map.get(hit_source, hit_source)}")
    if not any_r_eff:
        notes.append("R_eff 未能计算（缺接触矩阵或 R0 估计），补种人数基于 HIT 反推覆盖率直接换算")
    notes.append(
        "r_eff 按均匀免疫假设计算（scenario 未区分年龄组免疫异质性）；"
        "实际年龄异质免疫下 r_eff 可能不同"
    )
    return notes


async def get_immunity_projection(
    db: AsyncSession,
    disease: str,
    province: str | None = None,
    waning_rate: float | None = None,
    projection_years: int = DEFAULT_PROJECTION_YEARS,
    birth_cohort_size: float = DEFAULT_BIRTH_COHORT_SIZE,
    barrier_threshold: float = DEFAULT_BARRIER_THRESHOLD,
) -> dict:
    """免疫屏障动态预测（抗体衰减 + 新出生队列驱动）。

    流程：
      1. 复用 ``_build_base_query`` 查取该省该病种已审核的 seroprevalence 数据点；
      2. 按年份聚合总体阳性率，调用 ``estimate_waning_rate`` 从多年份数据估计
         年抗体衰减率（waning_rate）；若年份数不足 2 或估计失败，则回退默认值
         0.02 并在 ``waning_rate_source`` 标注为默认；
      3. 取最近一年的年龄-阳性率曲线（按 ``_get_age_group_label`` 聚合、样本量
         加权），连同估计出的衰减率调用 ``project_barrier`` 得到未来屏障轨迹；
      4. 计算屏障首次跌破设定安全阈值（默认 0.92）的年份。

    返回
    ----
    dict
        {
            province, disease, waning_rate, waning_rate_source,
            projection_years, baseline_year, baseline_barrier,
            barrier_trajectory, hit_threshold, below_threshold_year, notes
        }
        ``barrier_trajectory`` 下标 i 对应 ``baseline_year + i``（i=0 为当前基线）。
    """
    notes: list[str] = []

    if waning_rate is not None:
        _waning_rate = float(waning_rate)
        _waning_source = "user"
    else:
        _waning_rate = None
        _waning_source = None

    query = _build_base_query(disease, province, None, None, None, None,
                              data_type="seroprevalence", review_status="approved",
                              include_subgroups=False)
    result = await db.execute(query)
    rows: list[DataPoint] = result.scalars().all()
    logger.info(
        f"[ImmunityProjection] 查询: disease={disease}, province={province}, "
        f"rows={len(rows)}"
    )

    if not rows:
        return {
            "province": province,
            "disease": disease,
            "waning_rate": None,
            "waning_rate_source": "none",
            "projection_years": projection_years,
            "baseline_year": None,
            "baseline_barrier": None,
            "barrier_trajectory": [],
            "hit_threshold": barrier_threshold,
            "below_threshold_year": None,
            "notes": ["无已审核通过的 seroprevalence 数据，无法进行免疫屏障动态预测"],
        }

    # 按年份聚合（用于总体阳性率时序 → 估计衰减率）
    year_groups: dict[int, list[DataPoint]] = {}
    for r in rows:
        if r.collection_year is None or r.value is None:
            continue
        year_groups.setdefault(r.collection_year, []).append(r)

    observed_by_year: dict[int, float] = {}
    for year, group in year_groups.items():
        _wpr = _calc_weighted_positivity(group)
        if _wpr["weighted_positivity"] is not None:
            observed_by_year[year] = _wpr["weighted_positivity"]

    if not observed_by_year:
        return {
            "province": province,
            "disease": disease,
            "waning_rate": None,
            "waning_rate_source": "none",
            "projection_years": projection_years,
            "baseline_year": None,
            "baseline_barrier": None,
            "barrier_trajectory": [],
            "hit_threshold": barrier_threshold,
            "below_threshold_year": None,
            "notes": ["无带年份与阳性率的有效数据，无法进行免疫屏障动态预测"],
        }

    # 估计衰减率（或回退默认）
    if _waning_rate is None:
        _waning_rate = estimate_waning_rate(observed_by_year, default=DEFAULT_WANING_RATE)
        if len(observed_by_year) < 2:
            _waning_source = "default"
            notes.append("有效年份数不足 2 个，无法从实测值拟合衰减率，采用默认衰减率 0.02")
        else:
            _waning_source = "estimated"
    logger.info(
        f"[ImmunityProjection] waning_rate={_waning_rate}, source={_waning_source}, "
        f"observed_years={sorted(observed_by_year.keys())}"
    )

    # 最近一年的年龄-阳性率曲线（样本量加权聚合到标准年龄组）
    baseline_year = max(observed_by_year.keys())
    latest_rows = [r for r in year_groups.get(baseline_year, []) if r.value is not None]
    age_buckets: dict[str, dict] = {}
    for r in latest_rows:
        label = _get_age_group_label(r.age_min, r.age_max) or "其他"
        bucket = age_buckets.setdefault(label, {"sp_sum": 0.0, "sample_sum": 0})
        sp = float(r.value)
        ss = float(r.sample_size or 0)
        if ss > 0:
            bucket["sp_sum"] += sp * ss
            bucket["sample_sum"] += ss
    age_seropositivity: dict[str, float] = {}
    for label, bucket in age_buckets.items():
        if bucket["sample_sum"] > 0:
            age_seropositivity[label] = round(
                bucket["sp_sum"] / bucket["sample_sum"], 4
            )

    if not age_seropositivity:
        return {
            "province": province,
            "disease": disease,
            "waning_rate": _waning_rate,
            "waning_rate_source": _waning_source,
            "projection_years": projection_years,
            "baseline_year": baseline_year,
            "baseline_barrier": None,
            "barrier_trajectory": [],
            "hit_threshold": barrier_threshold,
            "below_threshold_year": None,
            "notes": ["最近年份无有效年龄-阳性率数据，无法投影屏障轨迹"],
        }

    # --- 可选：加载接触矩阵，用 Perron-Frobenius 主导特征向量加权基线 ---
    # 口径与平台"有效免疫屏障"评估保持一致；加载失败或命中组太少则回退简单平均。
    weights_to_pass: dict[str, float] | None = None
    age_seropositivity_for_projection = age_seropositivity
    try:
        from app.core.effective_immunity import (
            AGE_GROUPS_CONTACT,
            load_contact_matrix,
            map_age_to_group,
        )
        _C = load_contact_matrix()
        # 重新按接触矩阵年龄组分箱（样本量加权）
        _cbuckets: dict[str, dict] = {}
        for r in latest_rows:
            _c_label = map_age_to_group(r.age_min, r.age_max)
            if _c_label is None:
                continue
            _b = _cbuckets.setdefault(_c_label, {"sp_sum": 0.0, "ss": 0})
            _ss = float(r.sample_size or 0)
            if _ss > 0:
                _b["sp_sum"] += float(r.value) * _ss
                _b["ss"] += _ss
        _age_sp_contact: dict[str, float] = {}
        for _k, _b in _cbuckets.items():
            if _b["ss"] > 0:
                _age_sp_contact[_k] = round(_b["sp_sum"] / _b["ss"], 4)
        # 至少命中 3/5 个接触矩阵年龄组才靠谱
        if len(_age_sp_contact) >= 3:
            import numpy as _np  # 局部导入避免顶层污染
            _eigvals, _eigvecs = _np.linalg.eig(_C)
            _idx = int(_np.argmax(_np.real(_eigvals)))
            _w_raw = _np.abs(_np.real(_eigvecs[:, _idx]))
            _w_sum = float(_w_raw.sum())
            _w_norm = (
                _np.ones(len(AGE_GROUPS_CONTACT)) / len(AGE_GROUPS_CONTACT)
                if _w_sum <= 0
                else _w_raw / _w_sum
            )
            weights_to_pass = {
                AGE_GROUPS_CONTACT[i]: float(_w_norm[i])
                for i in range(len(AGE_GROUPS_CONTACT))
            }
            age_seropositivity_for_projection = _age_sp_contact
            notes.append("基线屏障使用接触矩阵 Perron-Frobenius 主导特征向量加权"
                         "（口径与平台有效免疫屏障一致）")
        else:
            logger.info(
                f"[ImmunityProjection] 接触矩阵分箱命中不足 3 组"
                f"（{len(_age_sp_contact)}），回退简单平均"
            )
    except Exception as _exc:  # noqa: BLE001 — 故意吞掉加载失败（非关键路径）
        logger.info(
            f"[ImmunityProjection] 未启用接触加权基线"
            f"（{_exc.__class__.__name__}: {_exc}）"
        )

    trajectory = project_barrier(
        age_seropositivity_for_projection,
        waning_rate=_waning_rate,
        years=projection_years,
        birth_cohort_size=birth_cohort_size,
        weights=weights_to_pass,
    )
    baseline_barrier = trajectory[0] if trajectory else None
    threshold = max(0.0, min(1.0, float(barrier_threshold)))
    below_offset: int | None = None
    for i, val in enumerate(trajectory[1:], start=1):
        if val < threshold:
            below_offset = i
            break
    below_threshold_year = (
        baseline_year + below_offset
        if below_offset is not None and baseline_year is not None
        else None
    )

    return {
        "province": province,
        "disease": disease,
        "waning_rate": round(_waning_rate, 4),
        "waning_rate_source": _waning_source,
        "projection_years": projection_years,
        "baseline_year": baseline_year,
        "baseline_barrier": baseline_barrier,
        "barrier_trajectory": trajectory,
        "hit_threshold": threshold,
        "below_threshold_year": below_threshold_year,
        "notes": notes,
    }



async def get_immune_barrier_assessment(
    db: AsyncSession,
    disease: str | None = None,
    province: str | None = None,
    year_start: int | None = None,
    year_end: int | None = None,
    age_min: int | None = None,
    age_max: int | None = None,
    life_expectancy: float = 75.0,
    seroreversion_mu: float | None = None,
    hit_source_override: str | None = None,
    review_status: str = "approved",
    skip_catalytic: bool = False,
) -> dict:
    """免疫屏障评估（复用 FOI 模块的 R0/HIT 计算）。

    优化点（参考 serotracker）：
      1. 复用 FOI 催化模型 λ = -ln(1-SP)/age 估算 FOI；
      2. 反推 R0 ≈ λ·L，计算 HIT = 1 - 1/R0；
      3. HIT 阈值优先级：FOI 估计 > WHO 硬编码 > 文献 R0；
      4. 新增年龄分层分析（age_groups）；
      5. 新增省份对比矩阵（province_matrix）。
      6. 支持多疾病（逗号分隔）+ 多省份横向对比；多疾病场景自动跳过催化模型
         并额外返回 comparison_blocks（每个疾病独立的简化评估块）。
      7. review_status: approved 仅已审核；all 含待审核。
    """
    logger.info(
        f"[ImmuneBarrier] 开始评估: disease={disease}, province={province}, "
        f"year_start={year_start}, year_end={year_end}, age_min={age_min}, age_max={age_max}, "
        f"review_status={review_status}, skip_catalytic={skip_catalytic}"
    )

    # --- 多疾病检测 ---
    diseases = [d.strip() for d in (disease or "").split(",") if d.strip()] if disease else []
    is_multi_disease = len(diseases) > 1
    # 多疾病自动跳过催化模型（性能），除非显式要求
    if is_multi_disease and not skip_catalytic:
        skip_catalytic = True
        logger.info("[ImmuneBarrier] 多疾病场景 → 自动启用 skip_catalytic=True")

    # 收集本次评估使用的显式参数假设（用于响应透明展示）
    assumptions = {}
    if life_expectancy != 75.0:
        assumptions["life_expectancy"] = life_expectancy
    if seroreversion_mu:
        assumptions["seroreversion_mu"] = seroreversion_mu
    if hit_source_override:
        assumptions["hit_source_override"] = hit_source_override
    if review_status != "approved":
        assumptions["review_status"] = review_status

    query = _build_base_query(disease, province, year_start, year_end, age_min, age_max,
                              review_status=review_status)
    result = await db.execute(query)
    rows = result.scalars().all()

    # 标准化疾病 key，用于查 R0_REFERENCE / WHO_THRESHOLDS
    dis_key = normalize_disease(disease) if disease else None
    r0_ref = R0_REFERENCE.get(dis_key) if dis_key else None  # (typical, low, high)
    who_threshold = WHO_THRESHOLDS.get(dis_key) if dis_key else None
    reference_hit = _calc_hit_from_r0(r0_ref[0]) if r0_ref else None

    r0_reference_block = {
        "typical": r0_ref[0] if r0_ref else None,
        "range_low": r0_ref[1] if r0_ref else None,
        "range_high": r0_ref[2] if r0_ref else None,
    }

    if not rows:
        logger.warning(f"[ImmuneBarrier] 无审核通过数据: disease={disease}")
        return {
            "disease": dis_key or disease,
            "who_threshold": who_threshold,
            "r0_reference": r0_reference_block,
            "summary": {
                "total_data_points": 0,
                "total_literatures": 0,
                "total_samples": 0,
                "weighted_positivity_rate": None,
                "weighted_avg_foi_per_year": None,
                "estimated_r0_from_foi": None,
                "hit_from_foi_percent": None,
                "hit_from_reference_r0_percent": reference_hit,
                "hit_target_used_percent": None,
                "hit_target_source": "none",
                "models": [],
                "recommended_model": None,
                "recommended_params": None,
                "fitted_curve": [],
                "modeling_notes": [],
                "r0_assumption_note": None,
                "n_catalytic_records": 0,
                "catalytic_age_range": [None, None],
            },
            "yearly_trend": [],
            "age_groups": [],
            "province_matrix": [],
            "status": "no_data",
            "assessment": "暂无审核通过的数据可供评估。",
            "life_expectancy_used": life_expectancy,
            "assumptions": assumptions or None,
            "comparison_blocks": None,
            "is_multi_disease": is_multi_disease,
            "skip_catalytic": skip_catalytic,
        }

    # --- 1) 总体加权阳性率 ---
    sp_rows = [r for r in rows if r.data_type == "seroprevalence" and r.sample_size]
    _wpr = _calc_weighted_positivity(rows)
    weighted_rate = _wpr["weighted_positivity"]
    total_sample = _wpr["total_sample"]
    weighted_rate_ci_lower = _wpr["ci_lower"]
    weighted_rate_ci_upper = _wpr["ci_upper"]

    lit_ids = {str(r.literature_id) for r in rows if r.literature_id}

    # --- 2) FOI 估算（复用催化模型族 MLE 新引擎）---
    # 旧口径：单点 λ=-ln(1-SP)/age 再样本量加权（仅作催化模型失败时的回退）
    foi_tuples: list[tuple[float, int]] = []
    for r in sp_rows:
        if r.value is None:
            continue
        age_mid = _midpoint_age(r.age_min, r.age_max)
        if age_mid is None:
            continue
        foi = _calc_foi_from_sp(float(r.value), age_mid)
        if foi is not None:
            foi_tuples.append((foi, float(r.sample_size or 1)))
    if foi_tuples:
        w_total_foi = sum(w for _, w in foi_tuples)
        legacy_foi = round(
            sum(v * w for v, w in foi_tuples) / w_total_foi, 6
        ) if w_total_foi > 0 else None
    else:
        legacy_foi = None

    # 新引擎：M1/M2/M3 催化模型族 MLE 拟合 + 模型比较 + 理论修正
    models_out: list = []
    recommended_model: str | None = None
    recommended_params: dict = {}
    fitted_curve: list = []
    catalytic_notes: list = []
    rec_foi: float | None = None
    r0_to_hit: float | None = None
    literature_hit: float | None = None
    r0_assumption_note: str | None = None
    catalytic_result: dict = {}  # 默认空，避免 skip_catalytic=True 时未定义

    if not skip_catalytic:
        catalytic_records = _build_catalytic_records(sp_rows)
        catalytic_result = fit_catalytic_models(catalytic_records, mu_fixed=seroreversion_mu)
        models_out = catalytic_result.get("models") or []
        recommended_model = catalytic_result.get("recommended_model")
        recommended_params = catalytic_result.get("recommended_params") or {}
        fitted_curve = catalytic_result.get("fitted_curve") or []
        catalytic_notes = catalytic_result.get("modeling_notes") or []

        r0_hit_info = _catalytic_r0_hit(catalytic_result, dis_key, life_exp=life_expectancy,
                                        mu_fixed=seroreversion_mu)
        rec_foi = r0_hit_info["foi_avg"]
        r0_to_hit = r0_hit_info["r0_to_hit"]
        literature_hit = r0_hit_info["literature_hit"]
        r0_assumption_note = r0_hit_info["r0_assumption_note"]
    else:
        # 跳过催化模型：用旧口径 legacy_foi 估算 R0/HIT
        if legacy_foi is not None:
            r0_to_hit = _calc_r0_from_foi(legacy_foi, life_expectancy)
            rec_foi = legacy_foi
        literature_hit = reference_hit  # 已在上方从 r0_ref 算好
        if literature_hit or r0_to_hit:
            catalytic_notes.append("已跳过催化模型拟合（多疾病聚合模式），使用 legacy 口径 FOI/R0")

    # 兼容旧字段：foi/r0 取 recommended_model 参数重算；无催化结果时回退旧加权平均
    weighted_avg_foi = rec_foi if rec_foi is not None else legacy_foi
    estimated_r0 = r0_to_hit
    foi_hit_percent = _calc_hit_from_r0(estimated_r0) if estimated_r0 is not None else None

    # HIT 阈值优先级链不变：FOI 估算 > WHO 硬编码 > 文献 R0（hit_source 扩展 mle_foi）
    hit_target, hit_source = _resolve_hit_target(
        foi_hit_percent, who_threshold, literature_hit, dis_key,
        hit_source_override=hit_source_override,
    )

    logger.info(
        f"[ImmuneBarrier] FOI/R0/HIT: weighted_avg_foi={weighted_avg_foi}, "
        f"estimated_r0={estimated_r0}, recommended_model={recommended_model}, "
        f"foi_hit={foi_hit_percent}%, reference_hit={literature_hit}%, "
        f"who_threshold={who_threshold}%, hit_target={hit_target}% (source={hit_source})"
    )

    # --- 3) 逐年趋势 ---
    year_groups: dict[int, list[DataPoint]] = {}
    for r in rows:
        if r.collection_year is None:
            continue
        y = r.collection_year
        if y not in year_groups:
            year_groups[y] = []
        year_groups[y].append(r)

    yearly_trend = []
    for year in sorted(year_groups.keys()):
        group = year_groups[year]
        _wpr_g = _calc_weighted_positivity(group)
        y_rate = _wpr_g["weighted_positivity"]
        ys = _wpr_g["total_sample"]
        yearly_trend.append({
            "year": year,
            "weighted_positivity": y_rate,
            "sample_size": ys,
            "ci_lower": _wpr_g["ci_lower"],
            "ci_upper": _wpr_g["ci_upper"],
            "point_count": len(group),
        })

    # --- 4) 年龄分层分析 ---
    age_map: dict[str, dict] = {
        g[0]: {"sp_sum": 0.0, "sample_sum": 0, "dp_count": 0, "foi_values": []}
        for g in AGE_GROUPS
    }
    age_map["其他"] = {"sp_sum": 0.0, "sample_sum": 0, "dp_count": 0, "foi_values": []}

    for r in sp_rows:
        if r.value is None:
            continue
        label = _get_age_group_label(r.age_min, r.age_max) or "其他"
        if label not in age_map:
            age_map[label] = {"sp_sum": 0.0, "sample_sum": 0, "dp_count": 0, "foi_values": []}
        bucket = age_map[label]
        sp = float(r.value)
        ss = float(r.sample_size or 0)
        if ss > 0:
            bucket["sp_sum"] += sp * ss
            bucket["sample_sum"] += ss
        bucket["dp_count"] += 1
        age_mid = _midpoint_age(r.age_min, r.age_max)
        foi = _calc_foi_from_sp(sp, age_mid) if age_mid is not None else None
        if foi is not None:
            bucket["foi_values"].append((foi, ss or 1))

    age_groups_out: list[dict] = []
    for age_label, lo, hi in AGE_GROUPS:
        bucket = age_map[age_label]
        if bucket["dp_count"] == 0:
            continue
        w_sp = round(bucket["sp_sum"] / bucket["sample_sum"], 2) if bucket["sample_sum"] > 0 else None
        if bucket["foi_values"]:
            fw = sum(w for _, w in bucket["foi_values"])
            w_foi = round(sum(v * w for v, w in bucket["foi_values"]) / fw, 6) if fw > 0 else None
        else:
            w_foi = None
        age_status = _barrier_status_from_rate(w_sp, hit_target)
        age_groups_out.append({
            "age_group": age_label,
            "age_range": [lo, hi],
            "data_point_count": bucket["dp_count"],
            "total_samples": bucket["sample_sum"],
            "weighted_positivity_rate": w_sp,
            "weighted_avg_foi_per_year": w_foi,
            "status": age_status,
        })

    # --- 5) 省份对比矩阵 ---
    prov_map: dict[str, dict] = {}
    for r in sp_rows:
        if r.value is None:
            continue
        prov_raw = r.province or "未知"
        for p in prov_raw.split(";"):
            p = p.strip()
            if not p:
                p = "未知"
            if p not in prov_map:
                prov_map[p] = {"sp_sum": 0.0, "sample_sum": 0, "dp_count": 0, "foi_values": []}
            pm = prov_map[p]
            sp = float(r.value)
            ss = float(r.sample_size or 0)
            if ss > 0:
                pm["sp_sum"] += sp * ss
                pm["sample_sum"] += ss
            pm["dp_count"] += 1
            age_mid = _midpoint_age(r.age_min, r.age_max)
            foi = _calc_foi_from_sp(sp, age_mid) if age_mid is not None else None
            if foi is not None:
                pm["foi_values"].append((foi, ss or 1))

    province_matrix: list[dict] = []
    for prov_name, pm in prov_map.items():
        if pm["dp_count"] == 0:
            continue
        w_sp = round(pm["sp_sum"] / pm["sample_sum"], 2) if pm["sample_sum"] > 0 else None
        if pm["foi_values"]:
            fw = sum(w for _, w in pm["foi_values"])
            prov_foi = round(sum(v * w for v, w in pm["foi_values"]) / fw, 6) if fw > 0 else None
        else:
            prov_foi = None
        prov_r0 = _calc_r0_from_foi(prov_foi, life_expectancy) if prov_foi is not None else None
        prov_status = _barrier_status_from_rate(w_sp, hit_target)
        province_matrix.append({
            "province": prov_name,
            "data_point_count": pm["dp_count"],
            "total_samples": pm["sample_sum"],
            "weighted_positivity_rate": w_sp,
            "weighted_avg_foi_per_year": prov_foi,
            "estimated_r0_from_foi": prov_r0,
            "hit_target_percent": hit_target,
            "status": prov_status,
        })
    province_matrix.sort(key=lambda x: x["province"])

    # --- 6) 总体状态判定 ---
    status, assessment = _barrier_status_with_message(weighted_rate, hit_target, hit_source)

    # --- 7) 多疾病 comparison_blocks（每个疾病独立简化评估，跳过催化模型） ---
    comparison_blocks: dict[str, dict] | None = None
    if is_multi_disease and rows:
        # 按 disease 分组
        disease_groups: dict[str, list[DataPoint]] = {}
        for r in rows:
            d = r.disease or "未知"
            if d not in disease_groups:
                disease_groups[d] = []
            disease_groups[d].append(r)

        comparison_blocks = {}
        for d_key, d_rows in sorted(disease_groups.items()):
            # 基础汇总
            _wpr_d = _calc_weighted_positivity(d_rows)
            d_rate = _wpr_d["weighted_positivity"]
            d_samples = _wpr_d["total_sample"]
            d_lit_ids = {str(r.literature_id) for r in d_rows if r.literature_id}

            # FOI 旧口径（多疾病跳过催化模型）
            foi_tuples_d: list[tuple[float, float]] = []
            for r in d_rows:
                if r.data_type != "seroprevalence" or r.value is None:
                    continue
                age_mid = _midpoint_age(r.age_min, r.age_max)
                if age_mid is None:
                    continue
                foi = _calc_foi_from_sp(float(r.value), age_mid)
                if foi is not None:
                    foi_tuples_d.append((foi, float(r.sample_size or 1)))
            if foi_tuples_d:
                w_d = sum(w for _, w in foi_tuples_d)
                d_foi = round(sum(v * w for v, w in foi_tuples_d) / w_d, 6) if w_d > 0 else None
            else:
                d_foi = None

            d_r0 = _calc_r0_from_foi(d_foi, life_expectancy) if d_foi is not None else None
            dis_d = normalize_disease(d_key) or d_key
            r0_ref_d = R0_REFERENCE.get(dis_d)
            lit_hit_d = _calc_hit_from_r0(r0_ref_d[0]) if r0_ref_d else None
            who_d = WHO_THRESHOLDS.get(dis_d)
            foi_hit_d = _calc_hit_from_r0(d_r0) if d_r0 is not None else None
            d_hit, d_hit_src = _resolve_hit_target(
                foi_hit_d, who_d, lit_hit_d, dis_d,
                hit_source_override=hit_source_override,
            )

            # 省份矩阵
            prov_map_d: dict[str, dict] = {}
            for r in d_rows:
                if r.data_type != "seroprevalence" or r.value is None:
                    continue
                prov_raw = r.province or "未知"
                for p in prov_raw.split(";"):
                    p = p.strip() or "未知"
                    if p not in prov_map_d:
                        prov_map_d[p] = {"sp_sum": 0.0, "sample_sum": 0, "dp_count": 0, "foi_values": []}
                    pm = prov_map_d[p]
                    sp = float(r.value)
                    ss = float(r.sample_size or 0)
                    if ss > 0:
                        pm["sp_sum"] += sp * ss
                        pm["sample_sum"] += ss
                    pm["dp_count"] += 1
                    age_mid = _midpoint_age(r.age_min, r.age_max)
                    foi = _calc_foi_from_sp(sp, age_mid) if age_mid is not None else None
                    if foi is not None:
                        pm["foi_values"].append((foi, ss or 1))
            pm_list: list[dict] = []
            for prov_name, pm in prov_map_d.items():
                if pm["dp_count"] == 0:
                    continue
                w_sp_p = round(pm["sp_sum"] / pm["sample_sum"], 2) if pm["sample_sum"] > 0 else None
                if pm["foi_values"]:
                    fw_p = sum(w for _, w in pm["foi_values"])
                    prov_foi_p = round(sum(v * w for v, w in pm["foi_values"]) / fw_p, 6) if fw_p > 0 else None
                else:
                    prov_foi_p = None
                prov_r0_p = _calc_r0_from_foi(prov_foi_p, life_expectancy) if prov_foi_p is not None else None
                prov_status_p = _barrier_status_from_rate(w_sp_p, d_hit)
                pm_list.append({
                    "province": prov_name,
                    "data_point_count": pm["dp_count"],
                    "total_samples": pm["sample_sum"],
                    "weighted_positivity_rate": w_sp_p,
                    "weighted_avg_foi_per_year": prov_foi_p,
                    "estimated_r0_from_foi": prov_r0_p,
                    "hit_target_percent": d_hit,
                    "status": prov_status_p,
                })
            pm_list.sort(key=lambda x: x["province"])

            d_status, d_assessment = _barrier_status_with_message(d_rate, d_hit, d_hit_src)

            comparison_blocks[d_key] = {
                "summary": {
                    "total_data_points": len(d_rows),
                    "total_literatures": len(d_lit_ids),
                    "total_samples": d_samples,
                    "weighted_positivity_rate": d_rate,
                    "weighted_avg_foi_per_year": d_foi,
                    "estimated_r0_from_foi": d_r0,
                    "hit_target_used_percent": d_hit,
                    "hit_target_source": d_hit_src,
                },
                "province_matrix": pm_list,
                "status": d_status,
                "assessment": d_assessment,
            }

    logger.info(
        f"[ImmuneBarrier] 评估完成: status={status}, weighted_rate={weighted_rate}%, "
        f"hit_target={hit_target}%, age_groups={len(age_groups_out)}, "
        f"provinces={len(province_matrix)}, comparison_blocks={len(comparison_blocks) if comparison_blocks else 0}"
    )

    hit_families = _build_hit_threshold_families(
        dis_key, foi_hit_percent, literature_hit, who_threshold,
        province=province,
    )

    return {
        "disease": dis_key or disease,
        "who_threshold": who_threshold,
        "r0_reference": r0_reference_block,
        "summary": {
            "total_data_points": len(rows),
            "total_literatures": len(lit_ids),
            "total_samples": total_sample,
            "weighted_positivity_rate": weighted_rate,
            "weighted_positivity_ci_lower": weighted_rate_ci_lower,
            "weighted_positivity_ci_upper": weighted_rate_ci_upper,
            "weighted_avg_foi_per_year": weighted_avg_foi,
            "estimated_r0_from_foi": estimated_r0,
            "hit_from_foi_percent": foi_hit_percent,
            "hit_from_reference_r0_percent": literature_hit,
            "hit_target_used_percent": hit_target,
            "hit_target_source": hit_source,
            # 三族阈值（theoretical / coverage_target / administrative）
            # 每条含 citation / year / source，缺省回退 None，整族始终存在
            "hit_thresholds_by_family": hit_families,
            # 新增：催化模型族 MLE 拟合 + 模型比较
            "models": models_out,
            "recommended_model": recommended_model,
            "recommended_params": recommended_params,
            "fitted_curve": fitted_curve,
            "modeling_notes": catalytic_notes,
            "r0_assumption_note": r0_assumption_note,
            "n_catalytic_records": catalytic_result.get("n_records"),
            "catalytic_age_range": catalytic_result.get("age_range"),
        },
        "yearly_trend": yearly_trend,
        "age_groups": age_groups_out,
        "province_matrix": province_matrix,
        "status": status,
        "assessment": assessment,
        "life_expectancy_used": life_expectancy,
        "assumptions": assumptions or None,
        # 多疾病对比块（每个疾病独立的简化评估，跳过催化模型）
        "comparison_blocks": comparison_blocks,
        "is_multi_disease": is_multi_disease,
        "skip_catalytic": skip_catalytic,
    }




async def get_barrier_probability(
    db: AsyncSession,
    disease: str | None = None,
    province: str | None = None,
    n_samples: int | None = None,
) -> dict:
    """免疫屏障评估的不确定性量化：输出达标概率替代二元结论。

    1. 查该省该病种已审核的 seroprevalence 数据点（含 sample_size、value、ci）；
    2. 用每个数据点的样本量与阳性率构造 Beta 分布，Monte Carlo 采样 n_samples 次；
    3. 每次采样按样本量加权汇成"加权总阳性率"，与各 HIT 候选阈值
       （FOI 估计 / WHO 硬编码 / 文献 R0，优先级 FOI > WHO > 文献 R0）比较，
       统计超过阈值的采样占比 → 达标概率 pass_probability；
    4. 依据 pass_probability 给出建议：<0.5 补种，0.5~0.8 监测，>0.8 达标。
    """
    empty = {
        "province": province,
        "disease": disease,
        "n_data_points": 0,
        "total_samples": 0,
        "pass_probability": None,
        "primary_threshold_source": None,
        "recommended_action": "证据不足",
        "hit_thresholds": {"foi": None, "who": None, "r0_lit": None},
        "weighted_mean": None,
        "weighted_ci": None,
        "fusion_hit": None,
        "sampling": {"n_samples": n_samples or settings.IMMUNITY_MC_SAMPLES, "n_groups": 0},
        "notes": ["无已审核通过的血清阳性率数据，无法进行不确定性量化"],
    }

    dis_key = normalize_disease(disease) if disease else (disease or None)
    query = _build_base_query(disease, province, None, None, None, None,
                              data_type="seroprevalence", review_status="approved",
                              include_subgroups=False)
    rows = (await db.execute(query)).scalars().all()
    sp_rows = [r for r in rows if r.value is not None and (r.sample_size or 0) > 0]
    if not sp_rows:
        logger.warning(f"[BarrierProb] 无有效数据: disease={disease}, province={province}")
        return empty

    # ---- 1) HIT 多来源候选值（proportion 0-1）----
    catalytic_records = _build_catalytic_records(rows)
    catalytic_result = fit_catalytic_models(catalytic_records)
    r0_hit_info = _catalytic_r0_hit(catalytic_result, dis_key)
    foi_hit = (
        _calc_hit_from_r0(r0_hit_info["r0_to_hit"])
        if r0_hit_info["r0_to_hit"] is not None
        else None
    )
    who_threshold = WHO_THRESHOLDS.get(dis_key) if dis_key else None
    literature_hit = r0_hit_info["literature_hit"]
    hit_prop = {
        "foi": foi_hit / 100.0 if foi_hit is not None else None,
        "who": who_threshold / 100.0 if who_threshold is not None else None,
        "r0_lit": literature_hit / 100.0 if literature_hit is not None else None,
    }
    thresholds = {k: v for k, v in hit_prop.items() if v is not None}
    if not thresholds:
        return {
            **empty,
            "notes": ["无法估计任何 HIT 候选阈值（无 FOI 数据且无 WHO/文献阈值）"],
        }

    # ---- 2) Monte Carlo 采样 ----
    n_samples = n_samples or settings.IMMUNITY_MC_SAMPLES
    sampled = sample_positivity(sp_rows, n_samples=n_samples)
    weights = [float(r.sample_size) for r in sp_rows]

    result = barrier_probability(sampled, thresholds, weights=weights)
    primary = result["primary_threshold"]

    # ---- 3) 建议动作：<0.5 补种，0.5~0.8 监测，>0.8 达标 ----
    pp = result["pass_probability"]
    if pp is None:
        recommended_action = "证据不足"
    elif pp < 0.5:
        recommended_action = "补种"
    elif pp < 0.8:  # 0.5 <= pp < 0.8
        recommended_action = "监测"
    else:
        recommended_action = "达标"

    fusion = fusion_hit(thresholds)

    total_samples = sum(r.sample_size or 0 for r in sp_rows)
    return {
        "province": normalize_province(province) if province else None,
        "disease": dis_key,
        "n_data_points": len(sp_rows),
        "total_samples": total_samples,
        "pass_probability": pp,
        "primary_threshold_source": primary,
        "per_threshold": result.get("thresholds_used", {}),
        "recommended_action": recommended_action,
        "hit_thresholds": {
            "foi": (hit_prop["foi"] * 100.0) if hit_prop["foi"] is not None else None,
            "who": (hit_prop["who"] * 100.0) if hit_prop["who"] is not None else None,
            "r0_lit": (hit_prop["r0_lit"] * 100.0) if hit_prop["r0_lit"] is not None else None,
        },
        "weighted_mean": (result["weighted_mean"] * 100.0) if result["weighted_mean"] is not None else None,
        "weighted_ci": (
            [result["weighted_ci"][0] * 100.0, result["weighted_ci"][1] * 100.0]
            if result.get("weighted_ci") else None
        ),
        "fusion_hit": {
            "mean": fusion[0] * 100.0 if fusion[0] is not None else None,
            "ci_low": fusion[1] * 100.0 if fusion[1] is not None else None,
            "ci_high": fusion[2] * 100.0 if fusion[2] is not None else None,
        },
        "sampling": {"n_samples": n_samples, "n_groups": len(sp_rows)},
        "action_rule": "pass_probability < 0.5 → 补种；0.5~0.8 → 监测；>0.8 → 达标",
        "notes": [],
    }


async def get_foi_analysis(
    db: AsyncSession,
    disease: str | None = None,
    province: str | None = None,
    year_start: int | None = None,
    year_end: int | None = None,
    life_expectancy: float = 75.0,
    seroreversion_mu: float | None = None,
    hit_source_override: str | None = None,
) -> dict:
    """P0-1: FOI（感染力）+ 群体免疫阈值综合分析。

    纯分析逻辑（无 DB 变更），输入：已审核通过的 seroprevalence 数据点。
    步骤：
      1. 按疾病聚合（如 disease=None 则按疾病逐一计算）
      2. 对每个年龄组，用催化模型 λ = -ln(1-SP)/age 估算 FOI
      3. 计算加权平均 FOI（按 sample_size 加权）
      4. 反推 R0 估计值：R0 ≈ λ × L
      5. 计算 HIT：HIT = 1 - 1/R0，并与 WHO 阈值对比
      6. 按省份 × 疾病输出 FOI 热力矩阵
    """
    # 仅取已审核通过的 seroprevalence 主估计数据点（含 sample_size + 可计算年龄中点）
    query = _build_base_query(
        disease, province, year_start, year_end,
        age_min=None, age_max=None,
        data_type="seroprevalence",
        review_status="approved",
        include_subgroups=False,
    )
    result = await db.execute(query)
    rows: list[DataPoint] = result.scalars().all()

    logger.info(
        f"[FOI] get_foi_analysis 开始: disease={disease}, province={province}, "
        f"year_start={year_start}, year_end={year_end}, "
        f"查询到 {len(rows)} 条已审核 seroprevalence 数据点"
    )

    # 收集本次分析使用的显式参数假设（用于响应透明展示）
    assumptions = {}
    if life_expectancy != 75.0:
        assumptions["life_expectancy"] = life_expectancy
    if seroreversion_mu:
        assumptions["seroreversion_mu"] = seroreversion_mu
    if hit_source_override:
        assumptions["hit_source_override"] = hit_source_override

    if not rows:
        return {
            "disease": disease,
            "total_data_points": 0,
            "per_disease_results": [],
            "summary": {
                "disease": disease,
                "total_data_points": 0,
                "overall_weighted_positivity_rate": None,
                "weighted_avg_foi_per_year": None,
                "estimated_r0_from_foi": None,
                "r0_reference": {"typical": None, "range_low": None, "range_high": None},
                "hit_from_foi_percent": None,
                "hit_from_reference_r0_percent": None,
                "who_threshold_percent": None,
                "hit_target_used_percent": None,
                "hit_target_source": "none",
                "herd_immunity_status": "no_data",
                "life_expectancy_used": life_expectancy,
                "models": [],
                "recommended_model": None,
                "recommended_params": None,
                "fitted_curve": [],
                "modeling_notes": [],
                "r0_assumption_note": None,
                "n_catalytic_records": 0,
                "catalytic_age_range": [None, None],
            },
            "province_foi_matrix": [],
            "notes": ["无已审核通过的 seroprevalence 数据，无法进行 FOI 分析"],
            "assumptions": assumptions or None,
        }

    # 按疾病分组（若传了 disease 则只有一个组）
    disease_rows: dict[str, list[DataPoint]] = {}
    for r in rows:
        dis = r.disease or "未知"
        normalized = normalize_disease(dis)
        dis_key = normalized or dis
        if dis_key not in disease_rows:
            disease_rows[dis_key] = []
        disease_rows[dis_key].append(r)

    logger.info(f"[FOI] 按疾病分组: {len(disease_rows)} 种疾病 → {list(disease_rows.keys())}")
    for dk, drs in disease_rows.items():
        sp_count = sum(1 for r in drs if r.value is not None)
        age_count = sum(1 for r in drs if _midpoint_age(r.age_min, r.age_max) is not None)
        logger.info(f"[FOI]   疾病={dk}: 总数据点={len(drs)}, 有value={sp_count}, 可算年龄中点={age_count}")

    per_disease_results: list[dict] = []
    province_foi_matrix: list[dict] = []
    notes: list[str] = []

    for dis_key, dis_rows in disease_rows.items():
        # --- 1) FOI 按年龄组汇总 ---
        # 聚合到 AGE_GROUPS 的 5 个标准桶
        age_buckets: dict[str, dict] = {g[0]: {"sp_sum": 0.0, "sample_sum": 0, "dp_count": 0, "foi_values": []} for g in AGE_GROUPS}
        age_buckets["其他"] = {"sp_sum": 0.0, "sample_sum": 0, "dp_count": 0, "foi_values": []}

        for r in dis_rows:
            if r.value is None:
                continue
            sp = float(r.value)
            ss = float(r.sample_size or 0)
            label = _get_age_group_label(r.age_min, r.age_max)
            if label is None:
                label = "其他"
            if label not in age_buckets:
                age_buckets[label] = {"sp_sum": 0.0, "sample_sum": 0, "dp_count": 0, "foi_values": []}

            age_mid = _midpoint_age(r.age_min, r.age_max)
            foi = _calc_foi_from_sp(sp, age_mid) if age_mid is not None else None

            bucket = age_buckets[label]
            if ss and ss > 0:
                bucket["sp_sum"] += sp * ss
                bucket["sample_sum"] += ss
            bucket["dp_count"] += 1
            if foi is not None:
                bucket["foi_values"].append((foi, ss or 1))  # (值, 权重)

        foi_by_age: list[dict] = []
        # 标准 5 个年龄组
        for age_label, lo, hi in AGE_GROUPS:
            bucket = age_buckets[age_label]
            if bucket["dp_count"] == 0:
                continue
            w_sp = round(bucket["sp_sum"] / bucket["sample_sum"], 2) if bucket["sample_sum"] > 0 else None
            if bucket["foi_values"]:
                fv_total_w = sum(w for _, w in bucket["foi_values"])
                w_foi = round(sum(v * w for v, w in bucket["foi_values"]) / fv_total_w, 6) if fv_total_w > 0 else None
            else:
                w_foi = None
            logger.info(
                f"[FOI] [{dis_key}] 年龄组={age_label}: dp_count={bucket['dp_count']}, "
                f"samples={bucket['sample_sum']}, w_sp={w_sp}%, w_foi={w_foi}/年, "
                f"foi_values_count={len(bucket['foi_values'])}"
            )
            foi_by_age.append({
                "age_group": age_label,
                "age_mid_approx": (lo + hi) / 2.0,
                "data_point_count": bucket["dp_count"],
                "total_samples": bucket["sample_sum"],
                "weighted_positivity_rate": w_sp,
                "weighted_avg_foi_per_year": w_foi,
            })
        # 追加"其他"桶（标准年龄组之外的数据），避免数据被丢弃
        other_bucket = age_buckets.get("其他")
        if other_bucket and other_bucket["dp_count"] > 0:
            w_sp = round(other_bucket["sp_sum"] / other_bucket["sample_sum"], 2) if other_bucket["sample_sum"] > 0 else None
            if other_bucket["foi_values"]:
                fv_total_w = sum(w for _, w in other_bucket["foi_values"])
                w_foi = round(sum(v * w for v, w in other_bucket["foi_values"]) / fv_total_w, 6) if fv_total_w > 0 else None
            else:
                w_foi = None
            foi_by_age.append({
                "age_group": "其他",
                "age_mid_approx": 30.0,  # 经验中位年龄
                "data_point_count": other_bucket["dp_count"],
                "total_samples": other_bucket["sample_sum"],
                "weighted_positivity_rate": w_sp,
                "weighted_avg_foi_per_year": w_foi,
            })

        # --- 2) 全年龄段加权平均 FOI（旧口径，仅作催化模型失败时的回退）---
        # 取每个年龄组的 foi 汇总到整体
        all_foi_tuples: list[tuple[float, int]] = []
        for f in foi_by_age:
            if f["weighted_avg_foi_per_year"] is not None and f["total_samples"] > 0:
                all_foi_tuples.append((f["weighted_avg_foi_per_year"], f["total_samples"]))
        if all_foi_tuples:
            w_total = sum(w for _, w in all_foi_tuples)
            legacy_foi = round(
                sum(v * w for v, w in all_foi_tuples) / w_total, 6
            ) if w_total > 0 else None
        else:
            legacy_foi = None

        # --- 2.5) 催化模型族 MLE 拟合（新引擎）---
        # 用 (age_mid, x, n) 拟合 M1/M2/M3，输出模型比较 + 推荐模型 + 拟合曲线
        catalytic_records = _build_catalytic_records(dis_rows)
        catalytic_result = fit_catalytic_models(catalytic_records, mu_fixed=seroreversion_mu)
        models_out = catalytic_result.get("models") or []
        recommended_model = catalytic_result.get("recommended_model")
        recommended_params = catalytic_result.get("recommended_params") or {}
        fitted_curve = catalytic_result.get("fitted_curve") or []
        catalytic_notes = catalytic_result.get("modeling_notes") or []

        # 理论修正：R0/HIT 来源解析（仅 M1 + 地方性/终生免疫 才用 R0=λ·L；显式 μ 强制重算）
        r0_hit_info = _catalytic_r0_hit(catalytic_result, dis_key, life_exp=life_expectancy,
                                        mu_fixed=seroreversion_mu)
        rec_foi = r0_hit_info["foi_avg"]
        r0_to_hit = r0_hit_info["r0_to_hit"]
        literature_hit = r0_hit_info["literature_hit"]
        r0_assumption_note = r0_hit_info["r0_assumption_note"]

        # 兼容旧字段：foi/r0 取 recommended_model 参数重算；无催化结果时回退旧加权平均
        weighted_avg_foi = rec_foi if rec_foi is not None else legacy_foi
        estimated_r0 = r0_to_hit

        logger.info(
            f"[FOI] [{dis_key}] 催化模型: records={len(catalytic_records)}, "
            f"recommended={recommended_model}, foi_avg={weighted_avg_foi}/年, "
            f"r0_to_hit={r0_to_hit}, legacy_foi={legacy_foi}"
        )

        # --- 3) R0 估计（催化模型推荐参数）+ 文献参考 ---
        r0_ref = R0_REFERENCE.get(dis_key)  # (typical, low, high)

        logger.info(
            f"[FOI] [{dis_key}] R0估算: estimated_r0_from_foi={estimated_r0}, "
            f"r0_reference={r0_ref}"
        )

        # 如果 FOI 推出来的 R0 严重超出文献范围，给出 note
        if r0_ref and estimated_r0 is not None:
            _typical, rlow, rhigh = r0_ref
            if estimated_r0 < rlow * 0.3:
                notes.append(f"[{dis_key}] 基于 FOI 的 R0 估计（{estimated_r0}）显著低于文献参考区间 [{rlow}, {rhigh}]，可能是 SP 偏低或年龄覆盖不全。")
                logger.warning(f"[FOI] [{dis_key}] R0估计({estimated_r0})显著低于文献参考[{rlow},{rhigh}]")
            elif estimated_r0 > rhigh * 2:
                notes.append(f"[{dis_key}] 基于 FOI 的 R0 估计（{estimated_r0}）显著高于文献参考区间 [{rlow}, {rhigh}]，可能受年龄分组偏差影响。")
                logger.warning(f"[FOI] [{dis_key}] R0估计({estimated_r0})显著高于文献参考[{rlow},{rhigh}]")

        # --- 4) HIT（群体免疫阈值）两种估计 ---
        # 方案 A：FOI → R0 → HIT（仅 M1 + 地方性/终生免疫 有值，理论修正）
        foi_hit_percent = _calc_hit_from_r0(estimated_r0) if estimated_r0 is not None else None
        # 方案 B：文献 R0（typical）→ HIT
        who_threshold = WHO_THRESHOLDS.get(dis_key)

        logger.info(
            f"[FOI] [{dis_key}] HIT计算: hit_from_foi={foi_hit_percent}%, "
            f"hit_from_reference_r0={literature_hit}%, who_threshold={who_threshold}%"
        )

        # --- 5) 群体免疫状态判定 ---
        # HIT 阈值优先级链不变：FOI 估算 > WHO > 文献 R0（hit_source 扩展 mle_foi 标签）
        hit_target, hit_source = _resolve_hit_target(
            foi_hit_percent, who_threshold, literature_hit, dis_key,
            hit_source_override=hit_source_override,
        )

        # 用加权平均 SP 与 HIT 对比
        overall_sp = None
        sp_valid = [(float(r.value), float(r.sample_size or 1)) for r in dis_rows if r.value is not None]
        if sp_valid:
            w_sum = sum(w for _, w in sp_valid)
            overall_sp = round(sum(v * w for v, w in sp_valid) / w_sum, 2) if w_sum > 0 else None

        if overall_sp is not None and hit_target is not None:
            if overall_sp >= hit_target:
                herd_status = "reached"        # 已达群体免疫
            elif overall_sp >= hit_target - 10:
                herd_status = "near"           # 接近
            else:
                herd_status = "not_reached"    # 未达到
        else:
            herd_status = "undetermined"

        logger.info(
            f"[FOI] [{dis_key}] 群体免疫判定: overall_sp={overall_sp}%, "
            f"hit_target={hit_target}% (来源={hit_source}), "
            f"herd_status={herd_status}"
        )

        # --- 6) 省份 × 疾病 FOI 矩阵 ---
        prov_map: dict[str, dict] = {}
        for r in dis_rows:
            if r.value is None:
                continue
            prov_raw = r.province or "未知"
            for p in prov_raw.split(";"):
                p = p.strip()
                if not p:
                    p = "未知"
                if p not in prov_map:
                    prov_map[p] = {"sp_sum": 0.0, "sample_sum": 0, "dp_count": 0, "foi_values": []}
                pm = prov_map[p]
                sp = float(r.value)
                ss = float(r.sample_size or 0)
                if ss and ss > 0:
                    pm["sp_sum"] += sp * ss
                    pm["sample_sum"] += ss
                pm["dp_count"] += 1
                age_mid = _midpoint_age(r.age_min, r.age_max)
                foi = _calc_foi_from_sp(sp, age_mid) if age_mid is not None else None
                if foi is not None:
                    pm["foi_values"].append((foi, ss or 1))

        for prov_name, pm in prov_map.items():
            if pm["dp_count"] == 0:
                continue
            w_sp = round(pm["sp_sum"] / pm["sample_sum"], 2) if pm["sample_sum"] > 0 else None
            if pm["foi_values"]:
                fw = sum(w for _, w in pm["foi_values"])
                prov_foi = round(sum(v * w for v, w in pm["foi_values"]) / fw, 6) if fw > 0 else None
            else:
                prov_foi = None
            # 省域 HIT 达标判定
            p_hit = "undetermined"
            if w_sp is not None and hit_target is not None:
                if w_sp >= hit_target:
                    p_hit = "reached"
                elif w_sp >= hit_target - 10:
                    p_hit = "near"
                else:
                    p_hit = "not_reached"
            province_foi_matrix.append({
                "disease": dis_key,
                "province": prov_name,
                "data_point_count": pm["dp_count"],
                "total_samples": pm["sample_sum"],
                "weighted_positivity_rate": w_sp,
                "weighted_avg_foi_per_year": prov_foi,
                "herd_immunity_status": p_hit,
                "hit_target_percent": hit_target,
            })
            logger.info(
                f"[FOI] [{dis_key}] 省份={prov_name}: dp={pm['dp_count']}, "
                f"samples={pm['sample_sum']}, w_sp={w_sp}%, foi={prov_foi}/年, "
                f"herd_status={p_hit}"
            )

        logger.info(f"[FOI] [{dis_key}] 疾病分析完成: 年龄组数={len(foi_by_age)}, 省份数={len(prov_map)}")

        # 三族阈值（与 get_immune_barrier_assessment 口径一致）
        hit_families = _build_hit_threshold_families(
            dis_key, foi_hit_percent, literature_hit, who_threshold,
            province=province,
        )

        summary_block = {
            "disease": dis_key,
            "total_data_points": len(dis_rows),
            "overall_weighted_positivity_rate": overall_sp,
            "weighted_avg_foi_per_year": weighted_avg_foi,
            "estimated_r0_from_foi": estimated_r0,
            "r0_reference": {
                "typical": r0_ref[0] if r0_ref else None,
                "range_low": r0_ref[1] if r0_ref else None,
                "range_high": r0_ref[2] if r0_ref else None,
            },
            "hit_from_foi_percent": foi_hit_percent,
            "hit_from_reference_r0_percent": literature_hit,
            "who_threshold_percent": who_threshold,
            "hit_target_used_percent": hit_target,
            "hit_target_source": hit_source,
            # 三族阈值（theoretical / coverage_target / administrative）
            # 每条含 citation / year / source，缺省回退 None，整族始终存在
            "hit_thresholds_by_family": hit_families,
            "herd_immunity_status": herd_status,
            "life_expectancy_used": life_expectancy,
            "assumptions": assumptions or None,
            # 新增：催化模型族 MLE 拟合 + 模型比较 + 理论修正
            "models": models_out,
            "recommended_model": recommended_model,
            "recommended_params": recommended_params,
            "fitted_curve": fitted_curve,
            "modeling_notes": catalytic_notes,
            "r0_assumption_note": r0_assumption_note,
            "n_catalytic_records": catalytic_result.get("n_records"),
            "catalytic_age_range": catalytic_result.get("age_range"),
        }

        per_disease_results.append({
            "disease": dis_key,
            "summary": summary_block,
            "foi_by_age_group": foi_by_age,
            "models": models_out,
            "recommended_model": recommended_model,
            "fitted_curve": fitted_curve,
            "modeling_notes": catalytic_notes,
            "r0_assumption_note": r0_assumption_note,
        })

    # 如果只传了一个疾病，把 summary 提升到顶层
    top_disease_summary = per_disease_results[0]["summary"] if len(per_disease_results) == 1 else None

    return {
        "disease": disease,
        "total_data_points": len(rows),
        "per_disease_results": per_disease_results,
        "summary": top_disease_summary or {
            "num_diseases_analyzed": len(per_disease_results),
            "diseases": sorted(disease_rows.keys()),
        },
        "province_foi_matrix": province_foi_matrix,
        "notes": notes if notes else [],
        "assumptions": assumptions or None,
    }


# ============================================================
# P1: 疫苗效果 (VE / Vaccine Effectiveness) + 接种率 (Coverage) 分析
# 策略：
#   1. 不新增 DB 字段，数据来自已有的 seroprevalence 数据点（人群标签）
#   2. 若 population 字段包含"已接种"/"未接种"/"接种过"/"无免疫史"等关键字，
#      则按接种状态拆分，计算 VE = 1 - (SP_vax / SP_unvax)
#   3. 若没有分亚组数据，提供接种率推算（screening method）需要的组件
#      以及参考接种率（按疾病-省份，默认查 NIP 覆盖预设表）
# ============================================================

# ---- 国家免疫规划 (NIP) 典型接种率（按疾病，参考 2020-2024 年 CDC/WHO 报告）
# 单位：%，值为全国估计平均值


async def get_vaccine_analysis(
    db: AsyncSession,
    disease: str | None = None,
    province: str | None = None,
    year_start: int | None = None,
    year_end: int | None = None,
) -> dict:
    """P1: 疫苗效果 (VE) + 接种率综合分析。

    计算逻辑：
      1. 按疾病-省份聚合所有已审核的 seroprevalence 数据点
      2. 将数据点按接种状态拆分（已接种/未接种），如果两个亚组都有 SP，则计算 VE
      3. 计算「整体 SP」，并结合 FOI 模块的 HIT 反推隐含接种率
      4. 叠加 NIP 参考接种率表，输出省-疾病覆盖矩阵

    不新增 DB 字段；若拆分不出接种亚组，VE 字段返回 null 并在 notes 中说明。
    """
    query = _build_base_query(
        disease, province, year_start, year_end,
        age_min=None, age_max=None,
        data_type="seroprevalence",
        review_status="approved",
        include_subgroups=True,   # VE 计算可能依赖子估计的细分人群
    )
    result = await db.execute(query)
    rows: list = result.scalars().all()

    logger.info(
        f"[VE] get_vaccine_analysis 开始: disease={disease}, province={province}, "
        f"year_start={year_start}, year_end={year_end}, "
        f"查询到 {len(rows)} 条已审核 seroprevalence 数据点 (含子估计)"
    )

    notes: list[str] = []
    if not rows:
        return {
            "disease": disease,
            "province": province,
            "total_data_points": 0,
            "per_disease_results": [],
            "summary": {
                "num_diseases_analyzed": 0,
                "diseases": [],
            },
            "province_coverage_matrix": [],
            "notes": ["无已审核通过的数据点，无法进行疫苗分析"],
        }

    # ---- 先复用 FOI 模块计算 HIT（轻量：只取 summary 部分，用已实现的 helper 直接计算）----
    # 为了避免循环和重复计算，这里用「独立版本」计算每个疾病的 HIT：
    # 用文献 R0 估计计算（若没有则用 WHO 阈值替代），避免再跑 FOI 全流程

    # 按疾病分组
    disease_rows: dict[str, list] = {}
    for r in rows:
        dis = getattr(r, "disease", None) or "未知"
        norm = normalize_disease(dis)
        key = norm or dis
        if key not in disease_rows:
            disease_rows[key] = []
        disease_rows[key].append(r)

    logger.info(f"[VE] 按疾病分组: {len(disease_rows)} 种疾病 → {list(disease_rows.keys())}")

    per_disease_results: list[dict] = []
    province_coverage_matrix: list[dict] = []

    for dis_key, dis_rows in disease_rows.items():
        # 整体 SP（加权）
        sp_list = [(float(r.value), float(r.sample_size or 1)) for r in dis_rows if r.value is not None]
        if sp_list:
            wsum = sum(w for _, w in sp_list)
            overall_sp = round(sum(v * w for v, w in sp_list) / wsum, 2) if wsum > 0 else None
        else:
            overall_sp = None

        logger.info(f"[VE] [{dis_key}] 整体SP计算: 有效数据点={len(sp_list)}/{len(dis_rows)}, overall_sp={overall_sp}%")

        # ---- VE 计算（接种 vs 未接种拆分）----
        vaxxed, unvaxxed = _split_vax_unvax(dis_rows)
        ve_result: dict | None = None
        if vaxxed and unvaxxed:
            def _wsp(group):
                lst = [(float(r.value), float(r.sample_size or 1)) for r in group if r.value is not None]
                if not lst:
                    return None
                sw = sum(w for _, w in lst)
                return round(sum(v * w for v, w in lst) / sw, 2) if sw > 0 else None
            sp_v = _wsp(vaxxed)
            sp_u = _wsp(unvaxxed)
            logger.info(
                f"[VE] [{dis_key}] 亚组SP: 已接种组 sp_v={sp_v}% (n={sum(r.sample_size or 0 for r in vaxxed)}), "
                f"未接种组 sp_u={sp_u}% (n={sum(r.sample_size or 0 for r in unvaxxed)})"
            )
            ve_percent = _calc_ve_from_sp(sp_v, sp_u)
            total_n = sum(r.sample_size or 0 for r in vaxxed) + sum(r.sample_size or 0 for r in unvaxxed)
            ve_result = {
                "vaxxed_points": len(vaxxed),
                "unvaxxed_points": len(unvaxxed),
                "vaxxed_total_samples": sum(r.sample_size or 0 for r in vaxxed),
                "unvaxxed_total_samples": sum(r.sample_size or 0 for r in unvaxxed),
                "vaxxed_weighted_sp": sp_v,
                "unvaxxed_weighted_sp": sp_u,
                "ve_infection_percent": ve_percent,  # 保护性 VE（可能为 None）
                "interpretation": (
                    f"接种组阳性率 {sp_v}% vs 未接种组 {sp_u}%；"
                    + (f"VE(against infection)≈{ve_percent}%" if ve_percent is not None
                       else "接种组阳性率≥未接种组，属疫苗诱导抗体（非保护性维度），无法用该公式算 VE")
                ) if sp_v is not None and sp_u is not None else None,
            }
            logger.info(f"[VE] [{dis_key}] VE结果: ve_percent={ve_percent}%, total_n={total_n}")
        else:
            if len(vaxxed) == 0 and len(unvaxxed) == 0:
                notes.append(
                    f"[{dis_key}] 没有找到明确标注「已接种/未接种」亚组的数据点，无法直接计算 VE。"
                    "建议在文献审核时补充人群标签，或通过子估计（estimate_type='subgroup'）拆分接种状态。"
                )
                logger.info(f"[VE] [{dis_key}] 未找到接种/未接种亚组数据点，VE无法计算")
            elif len(vaxxed) == 0:
                logger.info(f"[VE] [{dis_key}] 仅有未接种组({len(unvaxxed)}条)，缺少已接种组，VE无法计算")
            elif len(unvaxxed) == 0:
                logger.info(f"[VE] [{dis_key}] 仅有已接种组({len(vaxxed)}条)，缺少未接种组，VE无法计算")

        # ---- 接种率推算 ----
        r0_ref = R0_REFERENCE.get(dis_key)
        hit_percent = _calc_hit_from_r0(r0_ref[0]) if r0_ref else WHO_THRESHOLDS.get(dis_key)
        implied_cov = _implied_coverage_from_hit(overall_sp, hit_percent)

        ref_cov = _get_reference_coverage(dis_key, None)  # 国家级先

        logger.info(
            f"[VE] [{dis_key}] 接种率推算: hit_percent={hit_percent}% "
            f"(来源={'r0_ref' if r0_ref else 'who'}), "
            f"implied_cov={implied_cov}%, nip_ref_national={ref_cov}%"
        )

        per_disease_results.append({
            "disease": dis_key,
            "total_data_points": len(dis_rows),
            "overall_weighted_sp": overall_sp,
            "herd_immunity_target_percent": hit_percent,
            "reference_r0_typical": r0_ref[0] if r0_ref else None,
            "ve_result": ve_result,
            "coverage": {
                "nip_reference_national_percent": ref_cov,
                "implied_from_seroprevalence_percent": implied_cov,
            },
        })

        # ---- 省 × 疾病覆盖率矩阵 ----
        # 先按省聚合
        prov_map: dict[str, list] = {}
        for r in dis_rows:
            p_raw = getattr(r, "province", None) or "未知"
            for p in p_raw.split(";"):
                p = p.strip() or "未知"
                if p not in prov_map:
                    prov_map[p] = []
                prov_map[p].append(r)

        for prov_name, prov_rows in prov_map.items():
            sp_l = [(float(r.value), float(r.sample_size or 1)) for r in prov_rows if r.value is not None]
            if sp_l:
                sw = sum(w for _, w in sp_l)
                psp = round(sum(v * w for v, w in sp_l) / sw, 2) if sw > 0 else None
            else:
                psp = None
            # 省级别 VE（同样尝试拆分）
            pv, pu = _split_vax_unvax(prov_rows)
            prov_ve = None
            if pv and pu:
                def _wsp2(group):
                    lst = [(float(r.value), float(r.sample_size or 1)) for r in group if r.value is not None]
                    if not lst:
                        return None
                    sw2 = sum(w for _, w in lst)
                    return round(sum(v * w for v, w in lst) / sw2, 2) if sw2 > 0 else None
                prov_ve = _calc_ve_from_sp(_wsp2(pv), _wsp2(pu))
            prov_nip = _get_reference_coverage(dis_key, prov_name) or ref_cov
            p_impl = _implied_coverage_from_hit(psp, hit_percent)
            # 达标判定：implied_cov >= NIP 参考 → on_track
            status = "undetermined"
            if p_impl is not None and prov_nip is not None:
                if p_impl >= prov_nip:
                    status = "on_track"
                elif p_impl >= prov_nip - 10:
                    status = "near"
                else:
                    status = "below"
            province_coverage_matrix.append({
                "disease": dis_key,
                "province": prov_name,
                "data_point_count": len(prov_rows),
                "weighted_sp_percent": psp,
                "ve_infection_percent": prov_ve,
                "nip_reference_coverage_percent": prov_nip,
                "implied_coverage_from_sp_percent": p_impl,
                "coverage_status": status,
            })

    top_summary = per_disease_results[0] if len(per_disease_results) == 1 else None

    return {
        "disease": disease,
        "province": province,
        "total_data_points": len(rows),
        "summary": top_summary or {
            "num_diseases_analyzed": len(per_disease_results),
            "diseases": sorted(disease_rows.keys()),
        },
        "per_disease_results": per_disease_results,
        "province_coverage_matrix": province_coverage_matrix,
        "notes": notes,
    }


async def get_effective_barrier(
    db: AsyncSession,
    disease: str | None = None,
    province: str | None = None,
) -> dict:
    """有效免疫屏障：用年龄接触矩阵对人群阳性率加权。

    查该省该病种「最近一年」的已审核 seroprevalence 数据点，按接触矩阵
    年龄组（effective_immunity.map_age_to_group）聚合成各年龄组阳性率
    （复用现有样本量加权聚合口径），再调用 effective_barrier 计算传播权重
    加权的有效免疫屏障、各组权重/缺口，并定位最薄弱年龄组。
    """
    from app.core.effective_immunity import (
        AGE_GROUPS_CONTACT,
        effective_barrier,
        load_contact_matrix,
        map_age_to_group,
    )

    empty = {
        "disease": disease,
        "province": province,
        "effective_barrier": None,
        "group_weights": {},
        "group_gaps": [],
        "weakest_groups": [],
        "age_group_positivity": {},
        "note": "无已审核通过的血清阳性率数据，无法计算有效免疫屏障",
    }

    query = _build_base_query(
        disease, province, None, None, None, None,
        data_type="seroprevalence", review_status="approved",
        include_subgroups=False,
    )
    result = await db.execute(query)
    rows = result.scalars().all()
    if not rows:
        return empty

    # 锁定「最近一年」：取全部数据点的最大调查年份
    years = [r.collection_year for r in rows if r.collection_year is not None]
    if not years:
        return {**empty, "note": "数据点缺少调查年份，无法锁定最近一年"}
    latest_year = max(years)
    latest_rows = [r for r in rows if r.collection_year == latest_year]

    # 按接触矩阵年龄组聚合各年龄组阳性率（样本量加权，复用现有聚合口径）
    buckets: dict[str, dict] = {
        g: {"sp_sum": 0.0, "sample_sum": 0, "dp_count": 0} for g in AGE_GROUPS_CONTACT
    }
    for r in latest_rows:
        if r.value is None:
            continue
        label = map_age_to_group(r.age_min, r.age_max)
        if label is None:
            continue
        sp = float(r.value)
        ss = float(r.sample_size or 0)
        if ss > 0:
            buckets[label]["sp_sum"] += sp * ss
            buckets[label]["sample_sum"] += ss
        buckets[label]["dp_count"] += 1

    age_group_positivity = {
        label: round(b["sp_sum"] / b["sample_sum"], 2)
        for label, b in buckets.items() if b["sample_sum"] > 0
    }

    result_data = effective_barrier(age_group_positivity, load_contact_matrix())
    result_data["disease"] = disease
    result_data["province"] = province
    result_data["latest_year"] = latest_year
    result_data["age_group_positivity"] = age_group_positivity
    result_data["note"] = "接触矩阵数值为占位，需替换为中国社会接触调查实测值"
    return result_data


