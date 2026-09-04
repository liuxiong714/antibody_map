"""P1-2: 交互式溯源 HTML 导出（自包含 HTML 高亮）

生成一个独立的 HTML 文件，将文献全文与提取的数据点溯源区间可视化：
- 文本中高亮每个数据点的 source_char_start..source_char_end 区间
- 侧边栏列出所有数据点，点击可定位到原文高亮位置
- 高亮颜色按 confidence 分级（high=绿/medium=黄/low=红）
- 未 grounded 的数据点以虚线边框标识
- 全部 CSS/JS 内联，无外部依赖，可离线打开

安全：所有用户文本均通过 html.escape 转义，避免 XSS。
"""
from __future__ import annotations

import html
import logging
from collections.abc import Iterable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TracePoint:
    """溯源数据点的最小表示（从 DataPoint ORM/字典转换而来）"""
    dp_id: str
    disease: str | None
    province: str | None
    city: str | None
    data_type: str | None
    value: float | None
    unit: str | None
    sample_size: int | None
    age_min: int | None
    age_max: int | None
    collection_year: int | None
    confidence: str | None
    review_status: str | None
    source_page: int | None
    source_context: str | None
    source_char_start: int | None
    source_char_end: int | None
    is_grounded: bool
    estimate_type: str | None


def _confidence_color(confidence: str | None) -> str:
    """置信度 → 边框/底色"""
    c = (confidence or "medium").lower()
    if c == "high":
        return "#16a34a"  # 绿
    if c == "low":
        return "#dc2626"  # 红
    return "#ca8a04"  # 中：黄


def _review_badge(status: str | None) -> str:
    """审核状态徽章"""
    s = (status or "pending").lower()
    colors = {
        "approved": ("#16a34a", "#dcfce7"),
        "rejected": ("#dc2626", "#fee2e2"),
        "pending": ("#ca8a04", "#fef9c3"),
    }
    fg, bg = colors.get(s, colors["pending"])
    label = {"approved": "已通过", "rejected": "已驳回", "pending": "待审核"}.get(s, s)
    return f'<span class="badge" style="color:{fg};background:{bg}">{html.escape(label)}</span>'


def _estimate_badge(estimate_type: str | None) -> str:
    """主估计/子估计徽章"""
    t = (estimate_type or "primary").lower()
    if t == "subgroup":
        return '<span class="badge" style="color:#7c3aed;background:#ede9fe">子估计</span>'
    return '<span class="badge" style="color:#2563eb;background:#dbeafe">主估计</span>'


def _build_highlighted_text(full_text: str, points: list[TracePoint]) -> str:
    """将全文按数据点区间插入 <mark> 标签。

    处理重叠区间：按 start 升序排序，遇重叠时截断到前一个 end。
    每个 mark 携带 data-dp-id 和 data-confidence 属性，供前端交互。
    """
    # 仅保留有效区间
    intervals: list[tuple[int, int, TracePoint]] = []
    for p in points:
        if p.source_char_start is None or p.source_char_end is None:
            continue
        s, e = p.source_char_start, p.source_char_end
        if s < 0 or e <= s or s >= len(full_text):
            continue
        e = min(e, len(full_text))
        intervals.append((s, e, p))

    if not intervals:
        return html.escape(full_text)

    # 按 start 升序，end 降序（长区间优先），稳定
    intervals.sort(key=lambda x: (x[0], -x[1]))

    parts: list[str] = []
    cursor = 0
    for s, e, p in intervals:
        # 跳过被前一个区间完全覆盖的
        if s < cursor:
            s = cursor
            if e <= s:
                continue
        # 输出未高亮的中间文本
        if s > cursor:
            parts.append(html.escape(full_text[cursor:s]))
        color = _confidence_color(p.confidence)
        border_style = "border:1px dashed" if not p.is_grounded else "border:1px solid"
        snippet = html.escape(full_text[s:e])
        parts.append(
            f'<mark id="hl-{html.escape(p.dp_id)}" '
            f'class="hl" '
            f'data-dp-id="{html.escape(p.dp_id)}" '
            f'data-confidence="{html.escape((p.confidence or "medium").lower())}" '
            f'style="background:{color}33;{border_style}:{color};'
            f'padding:0 2px;border-radius:3px;cursor:pointer"'
            f' title="{html.escape(_point_title(p))}">{snippet}</mark>'
        )
        cursor = e

    # 尾部文本
    if cursor < len(full_text):
        parts.append(html.escape(full_text[cursor:]))
    return "".join(parts)


def _point_title(p: TracePoint) -> str:
    parts = []
    if p.disease:
        parts.append(p.disease)
    if p.province:
        parts.append(p.province)
    if p.data_type:
        parts.append({"seroprevalence": "阳性率", "gmc": "GMC"}.get(p.data_type, p.data_type))
    if p.value is not None:
        parts.append(f"{p.value}{p.unit or ''}")
    if not p.is_grounded:
        parts.append("(未匹配原文)")
    return " ".join(parts) if parts else p.dp_id


def _point_summary(p: TracePoint) -> str:
    """侧边栏单条数据点摘要 HTML"""
    disease = html.escape(p.disease or "—")
    province = html.escape(p.province or "—")
    value_str = f"{p.value}{p.unit or ''}" if p.value is not None else "—"
    sample = str(p.sample_size) if p.sample_size else "—"
    year = str(p.collection_year) if p.collection_year else "—"
    ctx = html.escape((p.source_context or "")[:200])
    grounded = "已匹配" if p.is_grounded else "未匹配"
    grounded_cls = "grounded" if p.is_grounded else "ungrounded"

    return f"""
    <div class="dp-card" id="card-{html.escape(p.dp_id)}"
         data-dp-id="{html.escape(p.dp_id)}"
         onclick="focusHl('{html.escape(p.dp_id)}')">
      <div class="dp-card-head">
        <span class="dp-disease">{disease}</span>
        {_estimate_badge(p.estimate_type)}
        {_review_badge(p.review_status)}
      </div>
      <div class="dp-card-body">
        <div><span class="lbl">地区:</span> {province}</div>
        <div><span class="lbl">数值:</span> <b>{html.escape(value_str)}</b></div>
        <div><span class="lbl">样本:</span> {sample}　<span class="lbl">年份:</span> {year}</div>
        <div class="{grounded_cls}">● {grounded}
          {f'　<span class="lbl">页码:</span> {p.source_page}' if p.source_page else ''}
        </div>
        {f'<div class="dp-ctx" title="原文片段">{ctx}</div>' if ctx else ''}
      </div>
    </div>
    """


def _build_sidebar(points: list[TracePoint]) -> str:
    cards = "\n".join(_point_summary(p) for p in points)
    grounded_count = sum(1 for p in points if p.is_grounded)
    total = len(points)
    return f"""
    <div class="sidebar">
      <div class="sidebar-head">
        <h2>数据点溯源 ({total})</h2>
        <div class="stat">已匹配原文: <b>{grounded_count}</b> / {total}</div>
        <div class="legend">
          <span class="lg" style="background:#16a34a33;border:1px solid #16a34a">高置信</span>
          <span class="lg" style="background:#ca8a0433;border:1px solid #ca8a04">中置信</span>
          <span class="lg" style="background:#dc262633;border:1px solid #dc2626">低置信</span>
          <span class="lg" style="background:#fff;border:1px dashed #999">未匹配</span>
        </div>
      </div>
      <div class="dp-list">
        {cards if cards.strip() else '<div class="empty">暂无数据点</div>'}
      </div>
    </div>
    """


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} - 溯源报告</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
        background: #f8fafc; color: #1e293b; }}
.header {{ background: #1e293b; color: #fff; padding: 16px 24px;
           position: sticky; top: 0; z-index: 10; }}
.header h1 {{ font-size: 18px; margin-bottom: 4px; }}
.header .meta {{ font-size: 12px; color: #94a3b8; }}
.container {{ display: flex; min-height: calc(100vh - 60px); }}
.sidebar {{ width: 360px; background: #fff; border-right: 1px solid #e2e8f0;
            overflow-y: auto; position: sticky; top: 60px;
            height: calc(100vh - 60px); }}
.sidebar-head {{ padding: 16px; border-bottom: 1px solid #e2e8f0;
                 background: #f1f5f9; position: sticky; top: 0; z-index: 2; }}
.sidebar-head h2 {{ font-size: 15px; margin-bottom: 8px; }}
.stat {{ font-size: 12px; color: #475569; margin-bottom: 8px; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 4px; }}
.lg {{ font-size: 11px; padding: 2px 6px; border-radius: 3px; }}
.dp-list {{ padding: 8px; }}
.dp-card {{ border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px;
            margin-bottom: 8px; cursor: pointer; transition: all .15s;
            background: #fff; }}
.dp-card:hover {{ border-color: #3b82f6; box-shadow: 0 2px 8px rgba(59,130,246,.15); }}
.dp-card.active {{ border-color: #3b82f6; background: #eff6ff;
                   box-shadow: 0 2px 12px rgba(59,130,246,.25); }}
.dp-card-head {{ display: flex; align-items: center; gap: 6px; margin-bottom: 6px;
                 flex-wrap: wrap; }}
.dp-disease {{ font-weight: 600; font-size: 13px; color: #1e40af; }}
.badge {{ font-size: 10px; padding: 1px 6px; border-radius: 10px; }}
.dp-card-body {{ font-size: 12px; color: #475569; line-height: 1.6; }}
.dp-card-body .lbl {{ color: #94a3b8; }}
.grounded {{ color: #16a34a; font-size: 11px; }}
.ungrounded {{ color: #dc2626; font-size: 11px; }}
.dp-ctx {{ margin-top: 6px; padding: 6px; background: #f8fafc;
           border-left: 2px solid #cbd5e1; font-size: 11px; color: #64748b;
           white-space: pre-wrap; word-break: break-all; max-height: 60px;
           overflow: hidden; text-overflow: ellipsis; }}
.empty {{ text-align: center; padding: 40px 16px; color: #94a3b8; font-size: 13px; }}
.content {{ flex: 1; padding: 24px 32px; overflow-y: auto; }}
.text-box {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px;
             padding: 24px 32px; line-height: 1.8; font-size: 14px;
             white-space: pre-wrap; word-break: break-word; max-width: 900px; }}
.hl.active {{ outline: 2px solid #3b82f6; outline-offset: 2px; }}
.footer {{ padding: 12px 24px; text-align: center; color: #94a3b8; font-size: 11px; }}
</style>
</head>
<body>
<div class="header">
  <h1>📑 {title_html} - 溯源报告</h1>
  <div class="meta">生成时间: {generated_at} · 数据点: {dp_count} · 已匹配: {grounded_count}</div>
</div>
<div class="container">
  {sidebar}
  <div class="content">
    <div class="text-box">{highlighted_text}</div>
  </div>
</div>
<div class="footer">由 antibody_map01 P1-2 溯源导出模块生成 · 自包含 HTML，可离线打开</div>
<script>
function focusHl(dpId) {{
  // 切换侧边栏激活态
  document.querySelectorAll('.dp-card').forEach(c => c.classList.remove('active'));
  const card = document.getElementById('card-' + dpId);
  if (card) card.classList.add('active');
  // 切换高亮激活态
  document.querySelectorAll('.hl').forEach(h => h.classList.remove('active'));
  const hl = document.getElementById('hl-' + dpId);
  if (hl) {{
    hl.classList.add('active');
    hl.scrollIntoView({{behavior: 'smooth', block: 'center'}});
  }}
}}
function focusCard(dpId) {{
  const card = document.getElementById('card-' + dpId);
  if (card) {{
    card.scrollIntoView({{behavior: 'smooth', block: 'center'}});
    card.classList.add('active');
    setTimeout(() => card.classList.remove('active'), 1500);
  }}
}}
// 点击高亮 → 滚动到侧边栏对应卡片
document.addEventListener('click', function(ev) {{
  const mark = ev.target.closest('.hl');
  if (mark && mark.dataset.dpId) {{
    focusCard(mark.dataset.dpId);
  }}
}});
</script>
</body>
</html>
"""


def generate_traceability_html(
    title: str,
    full_text: str,
    data_points: Iterable[TracePoint],
    generated_at: str = "",
) -> str:
    """生成自包含的溯源 HTML 字符串。

    Args:
        title: 文献标题
        full_text: 文献全文（clean_text）
        data_points: 数据点列表
        generated_at: 生成时间字符串（空则取当前时间）

    Returns:
        完整的 HTML 字符串
    """
    import datetime as _dt

    points = list(data_points)
    if not generated_at:
        generated_at = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    highlighted = _build_highlighted_text(full_text, points)
    sidebar = _build_sidebar(points)
    grounded_count = sum(1 for p in points if p.is_grounded)

    logger.info(
        f"[P1-2] 生成溯源 HTML: title={title!r}, text_len={len(full_text)}, "
        f"dp_count={len(points)}, grounded={grounded_count}"
    )

    return _HTML_TEMPLATE.format(
        title=html.escape(title),
        title_html=html.escape(title),
        generated_at=html.escape(generated_at),
        dp_count=len(points),
        grounded_count=grounded_count,
        sidebar=sidebar,
        highlighted_text=highlighted,
    )


def datapoint_dict_to_trace(dpo: dict) -> TracePoint:
    """从字典形式的数据点（API 返回）转换为 TracePoint。"""
    return TracePoint(
        dp_id=str(dpo.get("id") or ""),
        disease=dpo.get("disease"),
        province=dpo.get("province"),
        city=dpo.get("city"),
        data_type=dpo.get("data_type"),
        value=dpo.get("value"),
        unit=dpo.get("unit"),
        sample_size=dpo.get("sample_size"),
        age_min=dpo.get("age_min"),
        age_max=dpo.get("age_max"),
        collection_year=dpo.get("collection_year"),
        confidence=dpo.get("confidence"),
        review_status=dpo.get("review_status"),
        source_page=dpo.get("source_page"),
        source_context=dpo.get("source_context"),
        source_char_start=dpo.get("source_char_start"),
        source_char_end=dpo.get("source_char_end"),
        is_grounded=bool(dpo.get("is_grounded", False)),
        estimate_type=dpo.get("estimate_type"),
    )


def datapoint_orm_to_trace(dp) -> TracePoint:
    """从 DataPoint ORM 对象转换为 TracePoint。"""
    return TracePoint(
        dp_id=str(dp.id),
        disease=dp.disease,
        province=dp.province,
        city=dp.city,
        data_type=dp.data_type,
        value=float(dp.value) if dp.value is not None else None,
        unit=dp.unit,
        sample_size=dp.sample_size,
        age_min=dp.age_min,
        age_max=dp.age_max,
        collection_year=dp.collection_year,
        confidence=dp.confidence,
        review_status=dp.review_status,
        source_page=dp.source_page,
        source_context=dp.source_context,
        source_char_start=dp.source_char_start,
        source_char_end=dp.source_char_end,
        is_grounded=bool(dp.is_grounded),
        estimate_type=dp.estimate_type,
    )
