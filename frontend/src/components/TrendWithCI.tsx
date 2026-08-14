/**
 * TrendWithCI：带 95% 置信区间误差带的趋势折线图。
 *
 * 输入逐年 { year, value, ci_lower, ci_upper } 序列，
 * 用「下界 + 上界差」堆叠面积生成半透明误差带，中间叠加均值折线。
 */
import React from 'react';
import { Empty } from 'antd';
import EChart from './EChart';

export interface CiTrendPoint {
  year: number;
  value: number | null;
  ci_lower: number | null;
  ci_upper: number | null;
}

interface Props {
  data: CiTrendPoint[];
  title?: string;
  yLabel?: string;
  height?: number;
  loading?: boolean;
}

const TrendWithCI: React.FC<Props> = ({ data, title, yLabel = '阳性率 (%)', height = 300, loading }) => {
  if (loading) {
    return <div style={{ height }}>加载中...</div>;
  }
  const valid = data.filter((d) => d.value != null || d.ci_lower != null);
  if (valid.length === 0) {
    return <Empty description="暂无趋势数据" />;
  }

  const years = data.map((d) => d.year);
  const lower = data.map((d) => (d.ci_lower ?? d.value) as number | null);
  const upper = data.map((d) => (d.ci_upper ?? d.value) as number | null);
  // 上界与下界之差，用于堆叠面积生成误差带
  const band = data.map((d, i) => {
    if (upper[i] == null || lower[i] == null) return null;
    return Number((upper[i]! - lower[i]!).toFixed(4));
  });

  const option = {
    title: title ? { text: title, left: 'center', textStyle: { fontSize: 14 } } : undefined,
    tooltip: {
      trigger: 'axis',
      formatter: (params: Array<{ seriesName: string; axisValue: string; data: number | null }>) => {
        const first = params[0];
        const idx = years.indexOf(Number(first.axisValue));
        const p = idx >= 0 ? data[idx] : null;
        if (!p) return `${first.axisValue}`;
        return [
          `<b>${first.axisValue}年</b>`,
          `${yLabel}: ${p.value != null ? p.value.toFixed(2) : '-'}`,
          `95%CI: ${p.ci_lower != null ? p.ci_lower.toFixed(2) : '-'} ~ ${p.ci_upper != null ? p.ci_upper.toFixed(2) : '-'}`,
        ].join('<br/>');
      },
    },
    grid: { left: 55, right: 20, top: 45, bottom: 30 },
    legend: { top: 8, data: ['均值', '95% CI 误差带'] },
    xAxis: { type: 'category', data: years.map(String) },
    yAxis: { type: 'value', name: yLabel, scale: true },
    series: [
      {
        name: '95% CI 误差带',
        type: 'line',
        stack: 'ci',
        data: lower,
        lineStyle: { opacity: 0 },
        itemStyle: { opacity: 0 },
        emphasis: { disabled: true },
        tooltip: { show: false },
      },
      {
        name: '95% CI 误差带',
        type: 'line',
        stack: 'ci',
        data: band,
        lineStyle: { opacity: 0 },
        itemStyle: { opacity: 0 },
        areaStyle: { color: 'rgba(24,144,255,0.18)' },
        emphasis: { disabled: true },
        tooltip: { show: false },
      },
      {
        name: '均值',
        type: 'line',
        data: data.map((d) => d.value),
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { width: 2, color: '#1890ff' },
        itemStyle: { color: '#1890ff' },
      },
    ],
  };

  return <EChart option={option} style={{ height }} />;
};

export default TrendWithCI;
