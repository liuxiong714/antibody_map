/**
 * ForestPlot：Meta 分析森林图组件（数据驱动，内部构建 ECharts option）。
 *
 * 实现要点：
 * - 复用本地按需加载的 echarts（../lib/echarts，含 CustomChart）与
 *   echarts-for-react/lib/core，配色沿用 chartBuilders.ts（主色 #1677ff）。
 * - 布局（与后端 meta 分析数据对齐）：
 *   左类目轴：研究名 + 样本量；中区：效应量方块（面积 ∝ weight）+ 95% CI 横线；
 *   底部：合并效应三点菱形；垂直虚线在 pooled.estimate；
 *   右类目轴：效应量 + 95% CI 数值。
 * - estimate / ci_lower / ci_upper / pooled 均以 0-1 比例传入，x 轴自动按百分比缩放。
 * - tooltip 展示研究详情；I² 显示在标题旁；随容器宽度响应式自适应；
 *   无数据时渲染 antd Empty。
 */
import React, { useMemo } from 'react';
import { Empty } from 'antd';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from '../lib/echarts';

// ── 配色（沿用 chartBuilders.ts 主题）────────────────────────────────
const PRIMARY_COLOR = '#1677ff';   // 效应量方块（蓝）
const DIAMOND_COLOR = '#d4380d';   // 合并菱形（红）
const LINE_COLOR = '#333';         // CI 线 / 刻度

export interface ForestStudy {
  id: string;
  name: string;
  /** 效应量（0-1 比例） */
  estimate: number;
  /** 95% CI 下界（0-1 比例） */
  ci_lower: number;
  /** 95% CI 上界（0-1 比例） */
  ci_upper: number;
  /** 权重（%） */
  weight: number;
  /** 样本量（可选） */
  sample_size?: number;
}

export interface ForestPooled {
  /** 合并效应量（0-1 比例） */
  estimate: number;
  ci_lower: number;
  ci_upper: number;
}

interface ForestPlotProps {
  studies: ForestStudy[];
  pooled: ForestPooled;
  /** 异质性 I²（%），显示在标题旁 */
  i_squared?: number;
  title?: string;
  /** 图表高度（px），默认 400 */
  height?: number;
}

/** 研究名截短：保留年份，标题超长用省略号。 */
function truncateName(name: string, maxLen = 16): string {
  const yearMatch = name.match(/\((\d{4})\)\s*$/);
  const year = yearMatch ? ` (${yearMatch[1]})` : '';
  const title = name.replace(/\s*\(\d{4}\)\s*$/, '');
  const short = title.length > maxLen ? `${title.slice(0, maxLen - 1)}…` : title;
  return `${short}${year}`;
}

/** 百分比格式化：0-1 比例 → 百分比字符串 */
function fmtPercent(v: number, digits = 1): string {
  return `${(v * 100).toFixed(digits)}%`;
}

const ForestPlot: React.FC<ForestPlotProps> = ({
  studies,
  pooled,
  i_squared,
  title = 'Meta 森林图',
  height = 400,
}) => {
  const option = useMemo<Record<string, unknown>>(() => {
    const k = studies.length;

    // x 轴范围：以数据极值 + 边距缩放，但锁定在 [0,1]
    const bounds = studies.flatMap((s) => [s.estimate, s.ci_lower, s.ci_upper]).concat([
      pooled.estimate,
      pooled.ci_lower,
      pooled.ci_upper,
    ]);
    const dataMin = Math.min(...bounds);
    const dataMax = Math.max(...bounds);
    const pad = Math.max(0.02, (dataMax - dataMin) * 0.1);
    const xMin = Math.max(0, dataMin - pad);
    const xMax = Math.min(1, dataMax + pad);

    // 行序：各研究在前，最后一行“合并”
    const rows = [...studies.map((s) => s.name), '合并'];

    // 左侧标签：研究名 + 样本量
    const leftLabels = [
      ...studies.map((s) => {
        const sample = s.sample_size != null ? ` (n=${s.sample_size})` : '';
        return `${truncateName(s.name)}${sample}`;
      }),
      '合并',
    ];

    // 右侧标签：效应量% + 95%CI
    const rightLabels = [
      ...studies.map((s) => {
        const ci =
          s.ci_lower != null && s.ci_upper != null
            ? `${fmtPercent(s.ci_lower)}–${fmtPercent(s.ci_upper)}`
            : '-';
        return `${fmtPercent(s.estimate)} (${ci})`;
      }),
      `${fmtPercent(pooled.estimate)} (${fmtPercent(pooled.ci_lower)}–${fmtPercent(pooled.ci_upper)})`,
    ];

    const maxWeight = Math.max(1, ...studies.map((s) => s.weight));
    const squareSize = (w: number) => 4 + (w / maxWeight) * 18;

    return {
      title: {
        text: title,
        subtext: i_squared != null ? `I² = ${i_squared.toFixed(1)}%` : '',
        left: 'center',
        textStyle: { fontSize: 14 },
      },
      tooltip: {
        trigger: 'item',
        formatter(params: unknown) {
          const p = params as { seriesName?: string; data?: unknown; value?: unknown };
          if (p.seriesName === '研究') {
            const d = p.data as Record<string, unknown> & {
              value: number[];
              name: string;
              ci_lower: number;
              ci_upper: number;
              weight: number;
              sample_size?: number;
            };
            let tip = `<b>${d.name}</b>`;
            if (d.sample_size != null) tip += `<br/>样本量: ${d.sample_size}`;
            tip += `<br/>效应量: ${fmtPercent(d.value[0], 2)}`;
            tip += `<br/>95% CI: ${fmtPercent(d.ci_lower, 2)} – ${fmtPercent(d.ci_upper, 2)}`;
            tip += `<br/>权重: ${d.weight.toFixed(1)}%`;
            return tip;
          }
          if (p.seriesName === '合并') {
            const d = (p.data ?? p.value) as number[];
            return (
              `<b>合并效应</b><br/>效应量: ${fmtPercent(d[1], 2)}` +
              `<br/>95% CI: ${fmtPercent(d[2], 2)} – ${fmtPercent(d[3], 2)}`
            );
          }
          return '';
        },
      },
      grid: { left: 160, right: 160, top: 60, bottom: 30 },
      xAxis: {
        type: 'value',
        min: xMin,
        max: xMax,
        axisLabel: { formatter: (v: number) => `${Math.round(v * 100)}%` },
      },
      yAxis: [
        {
          type: 'category',
          data: rows,
          inverse: true,
          axisTick: { show: false },
          axisLabel: { width: 140, overflow: 'truncate', fontSize: 11 },
        },
        {
          type: 'category',
          data: rows,
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
        // CI 横线 + 端点刻度（custom）
        {
          type: 'custom',
          name: 'CI',
          data: studies.map((s, i) => [i, s.ci_lower, s.ci_upper]),
          renderItem(params: unknown, api: unknown) {
            const p = params as { dataIndex: number };
            const a = api as { value: (i: number) => number; coord: (d: number[]) => [number, number] };
            const idx = a.value(0);
            const lo = a.value(1);
            const hi = a.value(2);
            const y = a.coord([0, idx])[1];
            const xLo = a.coord([lo, idx])[0];
            const xHi = a.coord([hi, idx])[0];
            const cap = 4;
            return {
              type: 'group',
              children: [
                {
                  type: 'line',
                  shape: { x1: xLo, y1: y, x2: xHi, y2: y },
                  style: { stroke: LINE_COLOR, lineWidth: 1.2 },
                },
                {
                  type: 'line',
                  shape: { x1: xLo, y1: y - cap, x2: xLo, y2: y + cap },
                  style: { stroke: LINE_COLOR, lineWidth: 1.2 },
                },
                {
                  type: 'line',
                  shape: { x1: xHi, y1: y - cap, x2: xHi, y2: y + cap },
                  style: { stroke: LINE_COLOR, lineWidth: 1.2 },
                },
              ],
              silent: true,
            };
          },
        },
        // 效应量方块（scatter，面积 ∝ 权重）+ 垂直参考线
        {
          type: 'scatter',
          name: '研究',
          data: studies.map((s, i) => ({
            value: [s.estimate, i],
            name: s.name,
            ci_lower: s.ci_lower,
            ci_upper: s.ci_upper,
            weight: s.weight,
            sample_size: s.sample_size,
            symbolSize: squareSize(s.weight),
          })),
          itemStyle: { color: PRIMARY_COLOR },
          markLine: {
            symbol: 'none',
            label: { show: false },
            lineStyle: { type: 'dashed', color: '#999', width: 1 },
            data: [{ xAxis: pooled.estimate }],
          },
        },
        // 合并菱形（custom）
        {
          type: 'custom',
          name: '合并',
          data: [[k, pooled.estimate, pooled.ci_lower, pooled.ci_upper]],
          renderItem(params: unknown, api: unknown) {
            const a = api as { value: (i: number) => number; coord: (d: number[]) => [number, number] };
            const idx = a.value(0);
            const r = a.value(1);
            const lo = a.value(2);
            const hi = a.value(3);
            const y = a.coord([0, idx])[1];
            const cx = a.coord([r, idx])[0];
            const xLo = a.coord([lo, idx])[0];
            const xHi = a.coord([hi, idx])[0];
            const halfH = 10;
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
              style: { fill: DIAMOND_COLOR, stroke: DIAMOND_COLOR },
            };
          },
        },
      ],
    };
  }, [studies, pooled, i_squared, title]);

  if (!studies || studies.length === 0 || pooled == null) {
    return <Empty description="暂无森林图数据" style={{ padding: '40px 0' }} />;
  }

  return (
    <ReactEChartsCore
      echarts={echarts}
      option={option}
      style={{ width: '100%', height }}
      notMerge
      lazyUpdate
    />
  );
};

export default ForestPlot;