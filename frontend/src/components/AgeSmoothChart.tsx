/**
 * AgeSmoothChart：年龄-抗体曲线（LOWESS 平滑 + 拐点标注）。
 *
 * 散点 = 各年龄组中点原始值；平滑曲线 = LOWESS；
 * 拐点 = 平滑曲线二阶差分符号变化处（增速由快转慢）。
 */
import React, { useMemo } from 'react';
import { Alert, Card, Empty, Select, Space, Spin, Tag } from 'antd';
import EChart from './EChart';
import type { AgeCurveResponse } from '../types';

interface Props {
  data: AgeCurveResponse | null;
  loading?: boolean;
  metric: 'seroprevalence' | 'gmc';
  onMetricChange?: (m: 'seroprevalence' | 'gmc') => void;
  title?: string;
  height?: number;
}

const AgeSmoothChart: React.FC<Props> = ({
  data,
  loading,
  metric,
  onMetricChange,
  title = '年龄-抗体曲线（LOWESS 平滑 + 拐点）',
  height = 360,
}) => {
  const option = useMemo(() => {
    if (!data) return null;
    const yLabel = metric === 'gmc' ? 'GMC' : '阳性率 (%)';
    const raw = data.raw_points || [];
    const smooth = data.smoothed || [];
    const inflections = data.inflection_points || [];

    return {
      title: { text: title, left: 'center', textStyle: { fontSize: 14 } },
      tooltip: {
        trigger: 'item',
        formatter: (p: { seriesName: string; name: string; value: number | number[] }) => {
          const isScatter = Array.isArray(p.value);
          const age = isScatter ? (p.value as number[])[0] : p.name;
          const val = isScatter ? (p.value as number[])[1] : (p.value as number);
          const pt = raw.find((r) => Math.abs(r.age_mid - Number(age)) < 0.05);
          const extra = pt ? `<br/>研究数: ${pt.n_studies} · 样本量: ${pt.total_samples}` : '';
          return `<b>${p.seriesName}</b><br/>年龄 ${age} 岁<br/>${yLabel}: ${typeof val === 'number' ? val.toFixed(2) : val}${extra}`;
        },
      },
      legend: { top: 30, data: ['原始值', 'LOWESS 平滑', '拐点'] },
      grid: { left: 55, right: 25, top: 60, bottom: 35 },
      xAxis: {
        type: 'value',
        name: '年龄 (岁)',
        min: (v: { min: number }) => Math.max(0, Math.floor(v.min)),
      },
      yAxis: { type: 'value', name: yLabel, scale: true },
      series: [
        {
          name: '原始值',
          type: 'scatter',
          data: raw.map((p) => [p.age_mid, p.value]),
          symbolSize: 8,
          itemStyle: { color: '#8c8c8c', opacity: 0.6 },
        },
        {
          name: 'LOWESS 平滑',
          type: 'line',
          data: smooth.map((p) => [p.age_mid, p.value]),
          smooth: true,
          symbol: 'none',
          lineStyle: { width: 2.5, color: '#1890ff' },
        },
        {
          name: '拐点',
          type: 'scatter',
          data: inflections.map((p) => [p.age_mid, p.value]),
          symbol: 'pin',
          symbolSize: 30,
          itemStyle: { color: '#f5222d' },
          label: {
            show: true,
            formatter: (p: { value: number[] }) => `${p.value[0]}岁`,
            position: 'top',
            fontSize: 10,
          },
        },
      ],
    };
  }, [data, metric, title]);

  return (
    <Card
      size="small"
      title={<Tag color="blue">年龄曲线</Tag>}
      extra={
        <Select
          size="small"
          style={{ width: 130 }}
          value={metric}
          onChange={onMetricChange}
          options={[
            { value: 'seroprevalence', label: '血清阳性率' },
            { value: 'gmc', label: 'GMC 几何均数' },
          ]}
        />
      }
    >
      <Spin spinning={!!loading}>
        {option ? (
          <EChart option={option} style={{ height }} />
        ) : (
          <Empty description="暂无年龄曲线数据（需含可计算年龄中点的已审核主估计）" style={{ padding: '30px 0' }} />
        )}
        {data?.notes?.length ? (
          <Alert type="info" showIcon style={{ marginTop: 8 }} message={data.notes.join('；')} />
        ) : data ? (
          <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>
            年龄区间 {data.age_mid_range?.[0] ?? '-'} ~ {data.age_mid_range?.[1] ?? '-'} 岁 · 数据点 {data.n_points} · 拐点 {data.inflection_points?.length || 0} 个
          </div>
        ) : null}
      </Spin>
    </Card>
  );
};

export default AgeSmoothChart;
