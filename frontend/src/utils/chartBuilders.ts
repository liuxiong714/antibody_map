/**
 * 图表配置工厂：集中生成 ECharts option 对象。
 *
 * 约定：
 * - 返回 ``Record<string, unknown>`` 以兼容 EChart 组件类型。
 * - 配色沿用 antd 5 主题（主色 #1677ff）。
 * - 所有工厂函数首个参数为图表标题（居中显示）。
 */

// ── 颜色常量 ──────────────────────────────────────────────
const PRIMARY_COLOR = '#1677ff';
const BAND_COLOR = 'rgba(22,119,255,0.15)';
const FOI_COLOR = '#722ed1';

/** 把 number|null 序列转为 ECharts 可接受的 (number|undefined)[]。 */
function toSeries(values: (number | null)[]): (number | undefined)[] {
  return values.map((x) => (x != null ? x : undefined));
}

/** 百分比 / 原始值后缀与 y 轴名称。 */
function yAxisMeta(unit: string): { name: string } {
  return { name: unit === '%' ? '阳性率 (%)' : 'GMC' };
}

// ── 1. 折线 + 置信带 ──────────────────────────────────────

/**
 * 折线图 + 阴影置信带。
 *
 * 用两条堆叠 area 系列实现：
 *   下界（transparent，撑起基准）→ 区间带（半透明填充）。
 * tooltip 展示主值及 "95% CI: 下界 – 上界"。
 *
 * @param title  图表标题
 * @param years  x 轴类别（年份等）
 * @param values 主值序列
 * @param lower  CI 下界（与 values 同量纲）
 * @param upper  CI 上界（与 values 同量纲）
 * @param unit   数值单位后缀（'%' 或 ''）
 */
export function lineWithBand(
  title: string,
  years: (number | string)[],
  values: (number | null)[],
  lower: (number | null)[],
  upper: (number | null)[],
  unit = '%',
): Record<string, unknown> {
  const v = toSeries(values);
  const l = toSeries(lower);
  const u = toSeries(upper);

  return {
    title: { text: title, left: 'center' },
    tooltip: {
      trigger: 'axis',
      formatter(params: unknown) {
        const arr = Array.isArray(params) ? params : [params];
        let mainVal: number | undefined;
        let loVal: number | undefined;
        let hiVal: number | undefined;
        let axisValue: string | number = '';
        for (const p of arr) {
          const p2 = p as { seriesName?: string; data?: number; axisValue?: string | number };
          if (p2.seriesName === title) {
            mainVal = p2.data;
            axisValue = p2.axisValue ?? '';
          } else if (p2.seriesName === 'ci_lo') {
            loVal = p2.data;
          } else if (p2.seriesName === 'ci_band') {
            hiVal = p2.data;
          }
        }
        let tip = `<b>${axisValue}</b><br/>${title}: `;
        tip += mainVal != null ? `${mainVal.toFixed(2)}${unit}` : '-';
        if (loVal != null && hiVal != null) {
          tip += `<br/>95% CI: ${loVal.toFixed(2)}${unit} – ${hiVal.toFixed(2)}${unit}`;
        }
        return tip;
      },
    },
    grid: { left: 60, right: 20, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: years, boundaryGap: false },
    yAxis: { type: 'value', ...yAxisMeta(unit) },
    series: [
      {
        type: 'line',
        name: 'ci_lo',
        data: l,
        stack: 'CI',
        smooth: true,
        lineStyle: { width: 0 },
        symbol: 'none',
        areaStyle: { color: 'transparent' },
        tooltip: { show: false },
      },
      {
        type: 'line',
        name: 'ci_band',
        data: u,
        stack: 'CI',
        smooth: true,
        lineStyle: { width: 0 },
        symbol: 'none',
        areaStyle: { color: BAND_COLOR },
        tooltip: { show: false },
      },
      {
        type: 'line',
        name: title,
        data: v,
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { color: PRIMARY_COLOR, width: 2 },
        itemStyle: { color: PRIMARY_COLOR },
      },
    ],
  };
}

// ── 2. 柱状图 + 误差线 ────────────────────────────────────

/**
 * 柱状图 + 误差线（whisker）。
 *
 * 柱状图 + ``type: 'custom'`` 误差线系列：每个数据点渲染一条竖线 + 两端横线。
 * tooltip 展示主值及 "95% CI: 下界 – 上界"。
 *
 * @param title  图表标题
 * @param labels x 轴类别（省份/年龄组）
 * @param values 主值（柱高）
 * @param lower  CI 下界
 * @param upper  CI 上界
 * @param unit   数值单位后缀（'%' 或 ''）
 */
export function barWithError(
  title: string,
  labels: (number | string)[],
  values: (number | null)[],
  lower: (number | null)[],
  upper: (number | null)[],
  unit = '%',
): Record<string, unknown> {
  const v = toSeries(values);
  const l = toSeries(lower);
  const u = toSeries(upper);

  // 误差线数据项：只有上下界齐全才渲染
  const errorData: [number, number, number][] = [];
  for (let i = 0; i < labels.length; i++) {
    if (v[i] != null && l[i] != null && u[i] != null) {
      errorData.push([i, l[i] as number, u[i] as number]);
    }
  }

  return {
    title: { text: title, left: 'center' },
    tooltip: {
      trigger: 'axis',
      formatter(params: unknown) {
        const arr = Array.isArray(params) ? params : [params];
        let mainVal: number | undefined;
        let loVal: number | undefined;
        let hiVal: number | undefined;
        let axisValue: string | number = '';
        let dataIdx = -1;
        for (let i = 0; i < arr.length; i++) {
          const p2 = arr[i] as { seriesName?: string; data?: number; axisValue?: string | number; dataIndex?: number };
          if (p2.seriesName === title) {
            mainVal = p2.data;
            axisValue = p2.axisValue ?? '';
            dataIdx = p2.dataIndex ?? i;
          }
        }
        if (dataIdx >= 0) {
          loVal = l[dataIdx];
          hiVal = u[dataIdx];
        }
        let tip = `<b>${axisValue}</b><br/>${title}: `;
        tip += mainVal != null ? `${mainVal.toFixed(2)}${unit}` : '-';
        if (loVal != null && hiVal != null) {
          tip += `<br/>95% CI: ${loVal.toFixed(2)}${unit} – ${hiVal.toFixed(2)}${unit}`;
        }
        return tip;
      },
    },
    grid: { left: 60, right: 20, top: 40, bottom: 50 },
    xAxis: { type: 'category', data: labels, axisLabel: { rotate: 45 } },
    yAxis: { type: 'value', ...yAxisMeta(unit) },
    series: [
      {
        type: 'bar',
        name: title,
        data: v,
        barMaxWidth: 32,
        itemStyle: { color: PRIMARY_COLOR },
      },
      {
        type: 'custom',
        name: 'error_bar',
        data: errorData,
        renderItem(params: unknown, api: unknown): unknown {
          const p = params as { dataIndex: number };
          const a = api as {
            coord: (d: number[]) => [number, number];
          };
          const item = errorData[p.dataIndex];
          if (!item) return null;
          const [, loVal, hiVal] = item;
          const x = a.coord([p.dataIndex, loVal])[0];
          const y0 = a.coord([p.dataIndex, loVal])[1];
          const y1 = a.coord([p.dataIndex, hiVal])[1];
          const w = 10;
          return {
            type: 'group',
            children: [
              {
                type: 'line',
                shape: { x1: x, y1: y0, x2: x, y2: y1 },
                style: { stroke: '#666', lineWidth: 1.5 },
              },
              {
                type: 'line',
                shape: { x1: x - w / 2, y1: y1, x2: x + w / 2, y2: y1 },
                style: { stroke: '#666', lineWidth: 1.5 },
              },
              {
                type: 'line',
                shape: { x1: x - w / 2, y1: y0, x2: x + w / 2, y2: y0 },
                style: { stroke: '#666', lineWidth: 1.5 },
              },
            ],
            silent: true,
          };
        },
      },
    ],
  };
}

// ── 3. 年龄曲线：散点气泡 + 平滑线 + 置信带（连续 x 轴） ──

export interface AgeCurveCurvePointInput {
  age: number;
  prevalence: number;
  ci_lower: number;
  ci_upper: number;
}

export interface AgeCurvePointInput {
  age: number;
  prevalence: number;
  n: number;
}

/**
 * 血清阳性率-年龄曲线主图。
 *
 * x 轴为连续年龄（0.5 岁步长），y 轴为阳性率（%）：
 * - 观测点：散点气泡，大小 ∝ 样本量 n（sqrt 缩放）
 * - 拟合线：惩罚样条 P(a)
 * - 置信带：两段堆叠 area（下界 + 上界−下界）形成半透明区间
 *
 * @param title  图表标题
 * @param curve  拟合曲线点 [{age, prevalence, ci_lower, ci_upper}]
 * @param points 观测点 [{age, prevalence, n}]
 */
export function ageCurveWithBand(
  title: string,
  curve: AgeCurveCurvePointInput[],
  points: AgeCurvePointInput[],
): Record<string, unknown> {
  const c = curve || [];
  const p = points || [];
  const maxN = Math.max(1, ...p.map((pt) => pt.n || 0));
  const bubbleSize = (n: number) =>
    Math.max(7, Math.min(34, 7 + (Math.sqrt(Math.max(n, 1)) / Math.sqrt(maxN)) * 27));

  const main = c.map((pt) => [pt.age, pt.prevalence]);
  const lo = c.map((pt) => [pt.age, pt.ci_lower]);
  const band = c.map((pt) => [pt.age, pt.ci_upper - pt.ci_lower]);

  return {
    title: { text: title, left: 'center', textStyle: { fontSize: 14 } },
    tooltip: {
      trigger: 'item',
      formatter(params: unknown) {
        const p2 = params as { seriesName?: string; data?: number | number[] | { value: number[]; n?: number } };
        const name = p2.seriesName ?? '';
        let age: number | undefined;
        let val: number | undefined;
        let n: number | undefined;
        const d = p2.data;
        if (Array.isArray(d)) {
          age = d[0];
          val = d[1];
        } else if (d && typeof d === 'object' && Array.isArray((d as { value: number[] }).value)) {
          age = (d as { value: number[] }).value[0];
          val = (d as { value: number[] }).value[1];
          n = (d as { n?: number }).n;
        }
        let tip = `<b>${name}</b><br/>年龄 ${age ?? '-'} 岁<br/>阳性率: ${val != null ? `${val.toFixed(2)}%` : '-'}`;
        if (n != null) tip += `<br/>样本量: ${n.toLocaleString()}`;
        if (name === title) {
          const pt = c.find((cp) => Math.abs(cp.age - (age ?? -1)) < 0.05);
          if (pt) tip += `<br/>95% CI: ${pt.ci_lower.toFixed(2)}% – ${pt.ci_upper.toFixed(2)}%`;
        }
        return tip;
      },
    },
    legend: { top: 8, data: [title, '观测点'] },
    grid: { left: 55, right: 25, top: 45, bottom: 35 },
    xAxis: { type: 'value', name: '年龄 (岁)', min: (v: { min: number }) => Math.max(0, Math.floor(v.min)) },
    yAxis: { type: 'value', name: '阳性率 (%)', scale: true },
    series: [
      {
        type: 'line',
        name: 'ci_lo',
        data: lo,
        stack: 'CI',
        smooth: true,
        lineStyle: { width: 0 },
        symbol: 'none',
        areaStyle: { color: 'transparent' },
        tooltip: { show: false },
        emphasis: { disabled: true },
      },
      {
        type: 'line',
        name: 'ci_band',
        data: band,
        stack: 'CI',
        smooth: true,
        lineStyle: { width: 0 },
        symbol: 'none',
        areaStyle: { color: BAND_COLOR },
        tooltip: { show: false },
        emphasis: { disabled: true },
      },
      {
        type: 'line',
        name: title,
        data: main,
        smooth: true,
        symbol: 'none',
        lineStyle: { color: PRIMARY_COLOR, width: 2.5 },
      },
      {
        type: 'scatter',
        name: '观测点',
        data: p.map((pt) => ({ value: [pt.age, pt.prevalence], n: pt.n, symbolSize: bubbleSize(pt.n) })),
        itemStyle: { color: '#8c8c8c', opacity: 0.65 },
      },
    ],
  };
}

// ── 5. Meta 森林图 ───────────────────────────────────────

export interface ForestStudyInput {
  label: string;        // 研究标签（标题 年份）
  p: number;            // 阳性率 (%)
  ci_lower: number;     // CI 下界 (%)
  ci_upper: number;     // CI 上界 (%)
  weight: number;       // 权重 (%)
}

export interface ForestPooledInput {
  rate: number | null;
  ci_lower: number | null;
  ci_upper: number | null;
  model: string | null;
  tau2: number;
  Q: number;
  Q_p: number | null;
  I2: number;
  k: number;
}

/** 研究标签截短：保留年份，标题超长则省略号。 */
function shortStudyLabel(label: string, maxLen = 14): string {
  const yearMatch = label.match(/\((\d{4})\)\s*$/);
  const year = yearMatch ? ` (${yearMatch[1]})` : '';
  const title = label.replace(/\s*\(\d{4}\)\s*$/, '');
  const short = title.length > maxLen ? `${title.slice(0, maxLen - 1)}…` : title;
  return `${short}${year}`;
}

/** Wilson 二项 CI（用于对每项研究由 x/n 计算 95% CI）。 */
export function wilsonCi(x: number, n: number, z = 1.96): { lower: number; upper: number } {
  if (!n || n <= 0) return { lower: 0, upper: 0 };
  const p = x / n;
  const denom = 1 + (z * z) / n;
  const center = (p + (z * z) / (2 * n)) / denom;
  const half = (z * Math.sqrt((p * (1 - p) + (z * z) / (4 * n)) / n)) / denom;
  return { lower: Math.max(0, center - half), upper: Math.min(1, center + half) };
}

/**
 * Meta 森林图。
 *
 * 布局：
 * - 左侧类目 y 轴：研究标签（截短，最后一行“合并”）
 * - 右侧类目 y 轴（纯文本面板）：每行 “率% (CI) 权重%”
 * - 每研究：custom series 画 CI whisker + scatter 方块（面积∝权重 4–22px）
 * - 底部：custom series 画四点菱形（合并值）+ 中间参考虚线（markLine）
 * - 顶部 title subtext：I² / τ² / Q p / 模型标签
 *
 * @param studies 各研究（阳性率% / CI% / 权重%）
 * @param pooled  合并结果
 */
export function forestPlotOption(
  studies: ForestStudyInput[],
  pooled: ForestPooledInput,
): Record<string, unknown> {
  const k = studies.length;
  const labels = [...studies.map((s) => shortStudyLabel(s.label)), '合并'];
  const modelLabel =
    pooled.model === 'random' ? '随机效应模型'
    : pooled.model === 'fixed' ? '固定效应模型'
    : pooled.model === 'single_study' ? '单研究' : '-';

  const rate = pooled.rate ?? 0;
  const pLo = pooled.ci_lower ?? rate;
  const pHi = pooled.ci_upper ?? rate;

  const maxWeight = Math.max(1, ...studies.map((s) => s.weight));
  const squareSize = (w: number) => 4 + (w / maxWeight) * 18;

  const whiskerData = studies.map((s, i) => [i, s.ci_lower, s.ci_upper]);
  const diamondData = [[k, rate, pLo, pHi]];

  const rightLabels = [
    ...studies.map((s) => {
      const ci = s.ci_lower != null && s.ci_upper != null ? `${s.ci_lower.toFixed(1)}–${s.ci_upper.toFixed(1)}` : '-';
      return `${s.p.toFixed(1)}% (${ci}) ${s.weight.toFixed(1)}%`;
    }),
    `${rate.toFixed(1)}% (${pLo.toFixed(1)}–${pHi.toFixed(1)})`,
  ];

  return {
    title: {
      text: 'Meta 森林图',
      subtext: `I² = ${pooled.I2.toFixed(1)}%   τ² = ${pooled.tau2}   Q p = ${pooled.Q_p != null ? pooled.Q_p.toFixed(4) : '-'}   ${modelLabel}`,
      left: 'center',
      textStyle: { fontSize: 14 },
    },
    tooltip: {
      trigger: 'item',
      formatter(params: unknown) {
        const p = params as { seriesName?: string; data?: unknown };
        const name = p.seriesName ?? '';
        if (name === '研究') {
          const d = p.data as { value: number[]; label: string; weight: number; ci_lower: number; ci_upper: number };
          return `<b>${d.label}</b><br/>阳性率: ${d.value[0].toFixed(2)}%<br/>95% CI: ${d.ci_lower.toFixed(2)}% – ${d.ci_upper.toFixed(2)}%<br/>权重: ${d.weight.toFixed(1)}%`;
        }
        if (name === '合并') {
          const d = p.data as number[];
          return `<b>合并效应（${modelLabel}）</b><br/>率: ${d[1].toFixed(2)}% (${d[2].toFixed(2)}–${d[3].toFixed(2)})`;
        }
        return '';
      },
    },
    grid: { left: 150, right: 170, top: 60, bottom: 30 },
    xAxis: {
      type: 'value',
      name: '阳性率 (%)',
      min: 0,
      max: 100,
      axisLabel: { formatter: '{value}%' },
    },
    yAxis: [
      {
        type: 'category',
        data: labels,
        inverse: true,
        axisTick: { show: false },
        axisLabel: { width: 120, overflow: 'truncate', fontSize: 11 },
      },
      {
        type: 'category',
        data: labels,
        inverse: true,
        position: 'right',
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: {
          align: 'left',
          fontSize: 11,
          formatter: (value: string, index: number) => rightLabels[index] ?? value,
        },
      },
    ],
    series: [
      {
        type: 'custom',
        name: 'CI',
        data: whiskerData,
        renderItem(params: unknown, api: unknown): unknown {
          const a = api as { value: (i: number) => number; coord: (d: number[]) => [number, number] };
          const idx = a.value(0);
          const lo = a.value(1);
          const hi = a.value(2);
          const y = a.coord([0, idx])[1];
          const xLo = a.coord([lo, idx])[0];
          const xHi = a.coord([hi, idx])[0];
          const cap = 5;
          return {
            type: 'group',
            children: [
              { type: 'line', shape: { x1: xLo, y1: y, x2: xHi, y2: y }, style: { stroke: '#333', lineWidth: 1.2 } },
              { type: 'line', shape: { x1: xLo, y1: y - cap, x2: xLo, y2: y + cap }, style: { stroke: '#333', lineWidth: 1.2 } },
              { type: 'line', shape: { x1: xHi, y1: y - cap, x2: xHi, y2: y + cap }, style: { stroke: '#333', lineWidth: 1.2 } },
            ],
            silent: true,
          };
        },
      },
      {
        type: 'scatter',
        name: '研究',
        data: studies.map((s, i) => ({
          value: [s.p, i],
          weight: s.weight,
          label: s.label,
          ci_lower: s.ci_lower,
          ci_upper: s.ci_upper,
          symbolSize: squareSize(s.weight),
        })),
        itemStyle: { color: PRIMARY_COLOR },
        markLine: {
          symbol: 'none',
          label: { show: false },
          lineStyle: { type: 'dashed', color: '#999', width: 1 },
          data: [{ xAxis: rate }],
        },
      },
      {
        type: 'custom',
        name: '合并',
        data: diamondData,
        renderItem(params: unknown, api: unknown): unknown {
          const a = api as { value: (i: number) => number; coord: (d: number[]) => [number, number] };
          const idx = a.value(0);
          const r = a.value(1);
          const lo = a.value(2);
          const hi = a.value(3);
          const y = a.coord([0, idx])[1];
          const cx = a.coord([r, idx])[0];
          const xLo = a.coord([lo, idx])[0];
          const xHi = a.coord([hi, idx])[0];
          const halfH = 12;
          return {
            type: 'polygon',
            shape: {
              points: [
                [xLo, y],
                [cx, y - halfH],
                [xHi, y],
                [cx, y + halfH],
              ],
            },
            style: { fill: '#d4380d', stroke: '#d4380d' },
          };
        },
      },
    ],
  };
}

// ── 6. Meta 漏斗图 ───────────────────────────────────────

export interface FunnelPointInput {
  t: number;      // FT 变换效应量
  sqrt_n: number; // √样本量
}

export interface EggerTestInput {
  intercept: number;
  p_value: number;
  note?: string;
}

/** Freeman-Tukey 双反正弦正变换（与后端一致）：p∈[0,1]，n 为样本量。 */
export function ftTransform(p: number, n: number): number {
  const x = Math.max(0, Math.min(1, p)) * n;
  return Math.asin(Math.sqrt(x / (n + 1))) + Math.asin(Math.sqrt((x + 1) / (n + 1)));
}

/**
 * Meta 漏斗图（发表偏倚）。
 *
 * - x 轴：FT 变换效应量 t；y 轴：√n（精度）
 * - 散点：各研究；两条 ±1.96/√n 参考线 + 中间合并参考线
 * - Egger p<0.05 时标题红色提示可能存在发表偏倚
 *
 * @param funnel  各研究 (t, √n)
 * @param egger   简化 Egger 检验结果（可能为 null）
 * @param tCenter 合并效应量（FT 变换后），用于参考线居中
 */
export function funnelPlotOption(
  funnel: FunnelPointInput[],
  egger: EggerTestInput | null,
  tCenter: number | null,
): Record<string, unknown> {
  const pts = funnel || [];
  const data = pts.map((f) => [f.t, f.sqrt_n]);

  const ys = pts.map((f) => f.sqrt_n);
  const yMin = Math.min(...ys, 0.1);
  const yMax = Math.max(...ys, 1);

  const center = tCenter ?? (pts.length ? pts.reduce((s, f) => s + f.t, 0) / pts.length : 0);

  const N = 50;
  const upper: [number, number][] = [];
  const lower: [number, number][] = [];
  for (let i = 0; i <= N; i++) {
    const y = yMin + ((yMax - yMin) * i) / N;
    const off = 1.96 / y;
    upper.push([center + off, y]);
    lower.push([center - off, y]);
  }

  const eggerWarn = egger != null && egger.p_value < 0.05;

  return {
    title: {
      text: eggerWarn
        ? `漏斗图（提示可能存在发表偏倚，简化 Egger 检验 p=${egger?.p_value.toFixed(3)}）`
        : '漏斗图',
      left: 'center',
      textStyle: { fontSize: 14, color: eggerWarn ? '#cf1322' : '#333' },
    },
    tooltip: {
      trigger: 'item',
      formatter(params: unknown) {
        const p = params as { seriesName?: string; value?: number[] };
        if (p.seriesName === '研究' && Array.isArray(p.value)) {
          return `效应量 t: ${p.value[0].toFixed(4)}<br/>√n: ${p.value[1].toFixed(2)}`;
        }
        return '';
      },
    },
    legend: { show: false },
    grid: { left: 55, right: 25, top: 55, bottom: 40 },
    xAxis: { type: 'value', name: '效应量（FT 变换）', nameLocation: 'middle', nameGap: 26 },
    yAxis: { type: 'value', name: '√n', scale: true, nameLocation: 'middle', nameGap: 36 },
    series: [
      {
        type: 'scatter',
        name: '研究',
        data,
        symbolSize: 8,
        itemStyle: { color: PRIMARY_COLOR, opacity: 0.75 },
      },
      {
        type: 'line',
        name: '上界 (+1.96/√n)',
        data: upper,
        showSymbol: false,
        lineStyle: { color: '#faad14', type: 'dashed', width: 1.5 },
      },
      {
        type: 'line',
        name: '下界 (−1.96/√n)',
        data: lower,
        showSymbol: false,
        lineStyle: { color: '#faad14', type: 'dashed', width: 1.5 },
      },
      {
        type: 'line',
        name: '合并参考',
        data: [
          [center, yMin],
          [center, yMax],
        ],
        showSymbol: false,
        lineStyle: { color: '#8c8c8c', type: 'dashed', width: 1 },
      },
    ],
  };
}

// ── 4. 年龄别 FOI 曲线（连续 x 轴，y 单位 /年） ───────────

export interface AgeCurveFoiPointInput {
  age: number;
  foi: number | null;
}

/**
 * 年龄别 FOI（感染力）曲线。
 *
 * λ(a) = P′(a)/(1−P(a))，y 轴单位为 /年；foi 为 null 的点（P≥0.999 数值不安全）不绘制。
 *
 * @param title 图表标题
 * @param foi   曲线点 [{age, foi}]
 */
export function foiLineChart(
  title: string,
  foi: AgeCurveFoiPointInput[],
): Record<string, unknown> {
  const data = (foi || [])
    .filter((f) => f.foi != null)
    .map((f) => [f.age, f.foi as number]);

  return {
    title: { text: title, left: 'center', textStyle: { fontSize: 14 } },
    tooltip: {
      trigger: 'axis',
      formatter(params: unknown) {
        const arr = Array.isArray(params) ? params : [params];
        const first = arr[0] as { axisValue?: string | number; data?: number | number[] };
        const d = first.data;
        const age = Array.isArray(d) ? d[0] : first.axisValue;
        const val = Array.isArray(d) ? d[1] : d;
        return `<b>年龄 ${age} 岁</b><br/>FOI: ${val != null ? Number(val).toFixed(4) : '-'} /年`;
      },
    },
    grid: { left: 55, right: 25, top: 45, bottom: 35 },
    xAxis: { type: 'value', name: '年龄 (岁)', min: (v: { min: number }) => Math.max(0, Math.floor(v.min)) },
    yAxis: {
      type: 'value',
      name: 'FOI (/年)',
      scale: true,
      axisLabel: { formatter: (v: number) => v.toFixed(3) },
    },
    series: [
      {
        type: 'line',
        name: 'FOI',
        data,
        smooth: true,
        symbol: 'none',
        lineStyle: { color: FOI_COLOR, width: 2 },
        areaStyle: { color: 'rgba(114,46,209,0.10)' },
      },
    ],
  };
}

// ── 9. 出生队列（birth cohort）分析 ─────────────────────────

/**
 * 出生队列热力图：x=调查年, y=出生年代, 值=加权阳性率（%）。
 * 空 cell（<2 数据点，后端返回 null）不渲染；悬停显示 队列·年份 与率。
 */
export function birthCohortHeatmapOption(
  title: string,
  matrix: (number | null)[][],
  xYears: number[],
  yBands: string[],
): Record<string, unknown> {
  const data: [number, number, number][] = [];
  matrix.forEach((row, yi) => {
    row.forEach((v, xi) => {
      if (v != null) data.push([xi, yi, v]);
    });
  });
  const values = data.map((d) => d[2]);
  const min = values.length ? Math.floor(Math.min(...values)) : 0;
  const max = values.length ? Math.ceil(Math.max(...values)) : 100;

  return {
    title: { text: title, left: 'center', textStyle: { fontSize: 14 } },
    tooltip: {
      position: 'top',
      formatter(params: unknown) {
        const p = params as { data?: [number, number, number]; value?: [number, number, number] };
        const d = p.data || (Array.isArray(p.value) ? (p.value as [number, number, number]) : undefined);
        if (!d) return '';
        const band = yBands[d[1]] ?? '-';
        const year = xYears[d[0]] ?? '-';
        return `<b>${band} 队列 · ${year} 年</b><br/>加权阳性率: ${d[2].toFixed(1)}%`;
      },
    },
    grid: { left: 85, right: 20, top: 55, bottom: 60 },
    xAxis: {
      type: 'category',
      name: '调查年',
      data: xYears.map(String),
      splitArea: { show: true },
    },
    yAxis: {
      type: 'category',
      name: '出生年代',
      data: yBands,
      splitArea: { show: true },
    },
    visualMap: {
      min,
      max,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      inRange: { color: ['#e8f4ff', '#91caff', '#1677ff', '#0b1f5f'] },
      text: ['高', '低'],
      formatter: (v: number) => `${Math.round(v)}%`,
    },
    series: [
      {
        type: 'heatmap',
        data,
        label: {
          show: true,
          color: '#333',
          formatter: (p: { value: unknown }) => {
            const v = Array.isArray(p.value) ? (p.value as number[])[2] : undefined;
            return v != null ? `${Math.round(v)}%` : '';
          },
        },
        emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.5)' } },
      },
    ],
  };
}

/**
 * 出生队列轨迹折线图：每条线一个出生年代队列，随调查年变化。
 * 同一颜色斜向带提示队列效应（该代人持续低免疫）。
 */
export function birthCohortLinesOption(
  title: string,
  cohorts: { birth_year_band: string; series: { year: number; rate: number | null }[] }[],
): Record<string, unknown> {
  const years = cohorts[0]?.series.map((s) => s.year) ?? [];
  const series = (cohorts || []).map((c) => ({
    name: c.birth_year_band,
    type: 'line',
    smooth: true,
    connectNulls: false,
    symbolSize: 6,
    data: c.series.map((s) => (s.rate != null ? s.rate : undefined)),
  }));
  return {
    title: { text: title, left: 'center', textStyle: { fontSize: 14 } },
    tooltip: {
      trigger: 'axis',
      formatter(params: unknown) {
        const arr = Array.isArray(params) ? params : [params];
        if (!arr.length) return '';
        const year = (arr[0] as { axisValue?: string | number }).axisValue ?? '';
        const rows = arr
          .map((it) => {
            const p = it as { marker?: string; seriesName?: string; data?: number | undefined };
            const v = p.data;
            return `${p.marker ?? ''}<b>${p.seriesName ?? ''}</b>: ${v != null ? `${v.toFixed(1)}%` : '—'}`;
          })
          .join('<br/>');
        return `<b>${year} 年</b><br/>${rows}`;
      },
    },
    legend: { top: 5, type: 'scroll' },
    grid: { left: 55, right: 20, top: 45, bottom: 35 },
    xAxis: { type: 'category', name: '调查年', data: years.map(String) },
    yAxis: { type: 'value', name: '阳性率 (%)', scale: true },
    series,
  };
}

// ── 11. 抗原图谱散点 ──────────────────────────────────────

const ANTIGEN_COLOR = '#d4380d'; // 抗原 ■ 红
const SERUM_COLOR = '#1677ff';  // 血清 ● 蓝

/**
 * 抗原图谱散点：抗原■红 + 血清●蓝 + 网格（1 网格 = 2 倍滴度差）+ 应力标注。
 *
 * @param points   [{name, type, x, y}]
 * @param stress   归一化应力值（标注在标题下方）
 * @param gridExplanation  网格说明（如 "1 网格 = 2 倍滴度差"）
 * @param showLabels 是否显示点标签
 */
export function antigenicMapOption(
  points: { name: string; type: 'antigen' | 'serum'; x: number; y: number }[],
  stress: number,
  gridExplanation: string,
  showLabels: boolean,
): Record<string, unknown> {
  const antigens = points.filter((p) => p.type === 'antigen');
  const sera = points.filter((p) => p.type === 'serum');

  // 估算坐标范围以自动决定网格步长
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);

  // 网格线：以坐标原点对齐，步长 1（1 网格 = 2 倍滴度差）
  const x0 = Math.floor(minX);
  const x1 = Math.ceil(maxX);
  const y0 = Math.floor(minY);
  const y1 = Math.ceil(maxY);
  const splitNumber = Math.max(x1 - x0, y1 - y0, 1);

  return {
    title: [
      { text: '抗原图谱', left: 'center', textStyle: { fontSize: 14 } },
      { text: `stress = ${stress.toFixed(4)}｜${gridExplanation}`, left: 'center', top: 20, textStyle: { fontSize: 11, color: '#999' } },
    ],
    tooltip: {
      trigger: 'item',
      formatter: (p: unknown) => {
        const it = p as { marker?: string; data?: { name?: string; type?: string } };
        return `${it.marker ?? ''}<b>${it.data?.name ?? ''}</b><br/>类型: ${it.data?.type === 'antigen' ? '抗原' : '血清'}`;
      },
    },
    legend: {
      data: ['抗原', '血清'],
      top: 40,
      itemWidth: 12,
      itemHeight: 12,
      icon: 'circle',
    },
    grid: { left: 60, right: 40, top: 65, bottom: 50 },
    xAxis: {
      type: 'value',
      name: '网格',
      min: x0,
      max: x1,
      splitNumber,
      axisLabel: { show: true },
      // 网格线：实线 + 细线交替（1 单位 = 1 网格）
      splitLine: { lineStyle: { color: '#e5e5e5', type: 'solid' } },
    },
    yAxis: {
      type: 'value',
      name: '网格',
      min: y0,
      max: y1,
      splitNumber,
      splitLine: { lineStyle: { color: '#e5e5e5', type: 'solid' } },
    },
    series: [
      {
        name: '抗原',
        type: 'scatter',
        symbol: 'rect', // ■
        symbolSize: 12,
        itemStyle: { color: ANTIGEN_COLOR },
        label: {
          show: showLabels,
          position: 'top',
          formatter: '{b}',
          fontSize: 10,
          color: '#333',
        },
        data: antigens.map((p) => ({ name: p.name, value: [p.x, p.y], type: 'antigen' })),
      },
      {
        name: '血清',
        type: 'scatter',
        symbol: 'circle', // ●
        symbolSize: 10,
        itemStyle: { color: SERUM_COLOR },
        label: {
          show: showLabels,
          position: 'right',
          formatter: '{b}',
          fontSize: 10,
          color: '#333',
        },
        data: sera.map((p) => ({ name: p.name, value: [p.x, p.y], type: 'serum' })),
      },
    ],
  };
}
