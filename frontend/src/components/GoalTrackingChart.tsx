/**
 * GoalTrackingChart：目标达成追踪图。
 *
 * - 主图：各年全国加权阳性率折线（含 95% CI 误差带）+ GOAL_THRESHOLDS 目标阈值 markLine
 * - 副图：达标省份比例柱状图
 */
import React, { useMemo } from 'react';
import { Alert, Card, Empty, Spin, Tag } from 'antd';
import EChart from './EChart';
import type { GoalTrackingResponse } from '../types';

interface Props {
  data: GoalTrackingResponse | null;
  loading?: boolean;
}

const GoalTrackingChart: React.FC<Props> = ({ data, loading }) => {
  const option = useMemo(() => {
    if (!data || !data.years || data.years.length === 0) return null;
    const years = data.years;
    const threshold = data.goal_threshold_percent;

    return {
      tooltip: {
        trigger: 'axis',
        formatter: (params: Array<{ seriesName: string; axisValue: string; data: number | null }>) => {
          const year = Number(params[0].axisValue);
          const row = years.find((y) => y.year === year);
          if (!row) return `${year}年`;
          return [
            `<b>${year}年</b>`,
            `全国加权阳性率: ${row.national_positivity != null ? row.national_positivity.toFixed(2) + '%' : '-'}`,
            `95%CI: ${row.national_ci_lower != null ? row.national_ci_lower.toFixed(1) : '-'} ~ ${row.national_ci_upper != null ? row.national_ci_upper.toFixed(1) : '-'}`,
            `达标省: ${row.meeting_provinces}/${row.n_provinces}`,
            `与目标差距: ${row.gap_to_hit != null ? row.gap_to_hit.toFixed(1) + ' 百分点' : '-'}`,
          ].join('<br/>');
        },
      },
      legend: { top: 10, data: ['全国加权阳性率', '目标阈值'] },
      grid: [
        { left: 60, right: 25, top: 50, height: '48%' },
        { left: 60, right: 25, top: '62%', height: '26%' },
      ],
      xAxis: [
        {
          type: 'category',
          data: years.map((y) => String(y.year)),
          gridIndex: 0,
        },
        {
          type: 'category',
          data: years.map((y) => String(y.year)),
          gridIndex: 1,
        },
      ],
      yAxis: [
        {
          type: 'value',
          name: '阳性率 (%)',
          gridIndex: 0,
          scale: true,
        },
        {
          type: 'value',
          name: '达标比例',
          gridIndex: 1,
          max: 1,
          axisLabel: { formatter: (v: number) => `${Math.round(v * 100)}%` },
        },
      ],
      series: [
        {
          name: '全国加权阳性率',
          type: 'line',
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: years.map((y) => y.national_positivity),
          smooth: true,
          symbol: 'circle',
          symbolSize: 7,
          lineStyle: { width: 2.5, color: '#1890ff' },
          itemStyle: { color: '#1890ff' },
          markLine: threshold != null
            ? {
                symbol: 'none',
                label: { formatter: `目标 ${threshold}%` },
                lineStyle: { color: '#f5222d', type: 'dashed', width: 2 },
                data: [{ yAxis: threshold }],
              }
            : undefined,
        },
        {
          name: '达标省比例',
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: years.map((y) => y.meeting_ratio),
          itemStyle: {
            color: (p: { dataIndex: number }) =>
              (years[p.dataIndex].meeting_ratio || 0) >= 0.8 ? '#52c41a' : '#faad14',
          },
          label: { show: true, position: 'top', formatter: (p: { data: number }) => `${Math.round(p.data * 100)}%`, fontSize: 10 },
        },
      ],
    };
  }, [data]);

  if (loading) {
    return (
      <Card size="small">
        <Spin />
      </Card>
    );
  }

  if (!data) return <Empty description="暂无目标达成追踪数据" />;

  return (
    <Card
      size="small"
      title={
        <span>
          目标达成追踪
          {data.goal_threshold_percent != null && (
            <Tag color="red" style={{ marginLeft: 8 }}>
              达标阈值 {data.goal_threshold_percent}%
            </Tag>
          )}
        </span>
      }
    >
      {option ? (
        <EChart option={option} style={{ height: 420 }} />
      ) : (
        <Empty description="暂无逐年达标进度数据" />
      )}
      {data.latest_year != null && data.latest_gap_to_hit != null && (
        <div style={{ marginTop: 8, fontSize: 13 }}>
          最新年份 <b>{data.latest_year}</b> 距达标阈值：
          {data.latest_gap_to_hit > 0 ? (
            <span style={{ color: '#f5222d', fontWeight: 600 }}> 尚差 {data.latest_gap_to_hit.toFixed(1)} 百分点</span>
          ) : (
            <span style={{ color: '#52c41a', fontWeight: 600 }}> 已超过阈值 {Math.abs(data.latest_gap_to_hit).toFixed(1)} 百分点</span>
          )}
        </div>
      )}
      {data.notes?.length > 0 && (
        <Alert type="info" showIcon style={{ marginTop: 8 }} message={data.notes.join('；')} />
      )}
    </Card>
  );
};

export default GoalTrackingChart;
