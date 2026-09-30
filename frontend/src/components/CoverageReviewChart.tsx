/**
 * CoverageReviewChart：审核状态堆叠柱状图。
 *
 * 横轴 = 疾病，堆叠系列 = approved / pending / rejected（数据点数），
 * 悬浮 tooltip 显示各状态点数与样本量。
 */
import React, { useMemo } from 'react';
import EChart from './EChart';
import { DISEASES } from '../utils/constants';
import type { CoverageReviewDisease } from '../types';

interface Props {
  data: CoverageReviewDisease[];
  style?: React.CSSProperties;
}

const diseaseNameMap: Record<string, string> = Object.fromEntries(
  DISEASES.map((d) => [d.key, d.name_cn]),
);

const STATUS_META = {
  approved: { label: '已审核通过', color: '#52c41a' },
  pending: { label: '待审核', color: '#faad14' },
  rejected: { label: '已拒绝', color: '#f5222d' },
} as const;

const CoverageReviewChart: React.FC<Props> = ({ data, style }) => {
  const option = useMemo(() => {
    const names = data.map((d) => diseaseNameMap[d.disease] || d.disease);
    const series = (['approved', 'pending', 'rejected'] as const).map((key) => ({
      name: STATUS_META[key].label,
      type: 'bar' as const,
      stack: 'total',
      barMaxWidth: 28,
      itemStyle: { color: STATUS_META[key].color },
      data: data.map((d) => d[`${key}_points`]),
    }));

    return {
      title: { text: '各疾病审核状态分布（数据点数）', left: 'center', textStyle: { fontSize: 14 } },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        // 悬浮显示点数与样本量
        formatter: (params: Array<{ seriesName: string; dataIndex: number; value: number; marker?: string }>) => {
          const idx = params?.[0]?.dataIndex ?? 0;
          const row = data[idx];
          if (!row) return '';
          const lines = params
            .map((p) => {
              const key = p.seriesName === STATUS_META.approved.label ? 'approved'
                : p.seriesName === STATUS_META.pending.label ? 'pending' : 'rejected';
              const samples = row[`${key}_samples`];
              return `${p.marker || ''}${p.seriesName}：${p.value} 点 / ${samples} 样本`;
            })
            .join('<br/>');
          return `<b>${diseaseNameMap[row.disease] || row.disease}</b><br/>${lines}<br/>合计：${row.total_points} 点 / ${row.total_samples} 样本`;
        },
      },
      legend: { data: Object.values(STATUS_META).map((s) => s.label), bottom: 0 },
      grid: { left: 45, right: 20, top: 45, bottom: 40 },
      xAxis: {
        type: 'category',
        data: names,
        axisLabel: { rotate: data.length > 8 ? 30 : 0 },
      },
      yAxis: { type: 'value', minInterval: 1 },
      series,
    };
  }, [data]);

  return <EChart option={option} style={style || { height: 320 }} />;
};

export default CoverageReviewChart;