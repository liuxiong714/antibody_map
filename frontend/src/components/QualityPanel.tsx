/**
 * QualityPanel：数据质量评估面板。
 *
 * 展示已审核主估计的质量情况：
 * - KPI：总量 / 高质量(A+B)占比 / 带CI占比 / 原文溯源(grounded)占比
 * - 等级分布柱状图（A/B/C/D）
 * - 省级质量汇总表（含单点估计预警）
 */
import React, { useMemo } from 'react';
import { Alert, Card, Empty, Progress, Spin, Table, Tag, Typography } from 'antd';
import EChart from './EChart';
import type { QualityAssessmentResponse, QualityProvinceRow } from '../types';

interface Props {
  data: QualityAssessmentResponse | null;
  loading?: boolean;
  /** 为 true 时仅展示摘要与等级分布（钻取面板的精简模式） */
  compact?: boolean;
}

const GRADE_COLORS: Record<string, string> = { A: 'green', B: 'blue', C: 'gold', D: 'red' };

const QualityPanel: React.FC<Props> = ({ data, loading, compact = false }) => {
  const gradeOption = useMemo(() => {
    if (!data) return null;
    const dist = data.grade_distribution || { A: 0, B: 0, C: 0, D: 0 };
    return {
      title: { text: '质量等级分布', left: 'center', textStyle: { fontSize: 14 } },
      tooltip: { trigger: 'axis' },
      grid: { left: 45, right: 20, top: 45, bottom: 25 },
      xAxis: { type: 'category', data: ['A', 'B', 'C', 'D'] },
      yAxis: { type: 'value', minInterval: 1 },
      series: [
        {
          type: 'bar',
          data: ['A', 'B', 'C', 'D'].map((g) => dist[g as keyof typeof dist] || 0),
          itemStyle: {
            color: (p: { dataIndex: number }) =>
              ['#52c41a', '#1890ff', '#faad14', '#f5222d'][p.dataIndex],
          },
          label: { show: true, position: 'top' },
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

  if (!data) {
    return <Empty description="暂无数据质量评估数据" />;
  }

  const s = data.summary;
  const kpis = [
    { label: '主估计总数', value: data.total_estimates },
    { label: '高质量占比 (A+B)', value: s ? s.high_quality_ratio * 100 : 0, precision: 1, suffix: '%' },
    { label: '带 95%CI 占比', value: s ? s.with_ci_ratio * 100 : 0, precision: 1, suffix: '%' },
    { label: '原文溯源占比', value: s ? s.grounded_ratio * 100 : 0, precision: 1, suffix: '%' },
  ];

  const columns = [
    { title: '省份', dataIndex: 'province', key: 'province', width: 110, fixed: 'left' as const },
    { title: '主估计数', dataIndex: 'n_estimates', key: 'n_estimates', width: 90 },
    {
      title: '高质量占比',
      dataIndex: 'high_quality_ratio',
      key: 'high_quality_ratio',
      width: 140,
      render: (v: number, r: QualityProvinceRow) => {
        const pct = Math.round(v * 100);
        return (
          <Progress
            percent={pct}
            size="small"
            strokeColor={pct >= 60 ? '#52c41a' : pct >= 40 ? '#faad14' : '#f5222d'}
          />
        );
      },
    },
    {
      title: '带CI占比',
      dataIndex: 'with_ci_ratio',
      key: 'with_ci_ratio',
      width: 100,
      render: (v: number) => `${Math.round(v * 100)}%`,
    },
    {
      title: '溯源占比',
      dataIndex: 'grounded_ratio',
      key: 'grounded_ratio',
      width: 100,
      render: (v: number) => `${Math.round(v * 100)}%`,
    },
    {
      title: '等级分布',
      dataIndex: 'grades',
      key: 'grades',
      width: 180,
      render: (_: unknown, r: QualityProvinceRow) => (
        <span>
          {['A', 'B', 'C', 'D'].map((g) => (
            <Tag key={g} color={GRADE_COLORS[g]} style={{ marginRight: 4 }}>
              {g}:{r.grades?.[g as keyof typeof r.grades] || 0}
            </Tag>
          ))}
        </span>
      ),
    },
    {
      title: '证据提示',
      key: 'evidence',
      width: 140,
      render: (_: unknown, r: QualityProvinceRow) =>
        r.is_single_estimate ? <Tag color="orange">单点估计</Tag> : <span>-</span>,
    },
  ];

  return (
    <Card size="small" title={<Typography.Text strong>数据质量评估</Typography.Text>}>
      <Spin spinning={loading}>
        {/* KPI 摘要 */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, marginBottom: 16 }}>
          {kpis.map((k) => (
            <div key={k.label} style={{ minWidth: 160 }}>
              <div style={{ color: '#888', fontSize: 12 }}>{k.label}</div>
              <div style={{ fontSize: 24, fontWeight: 600 }}>
                {k.value}
                {k.suffix && <span style={{ fontSize: 14, fontWeight: 400, color: '#888' }}>{k.suffix}</span>}
              </div>
            </div>
          ))}
        </div>

        {!compact && (
          <div style={{ marginBottom: 16 }}>
            <EChart option={gradeOption || {}} style={{ height: 220 }} />
          </div>
        )}

        {data.notes?.length > 0 && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            message={data.notes.join('；')}
          />
        )}

        {!compact && (
          <Table<QualityProvinceRow>
            rowKey="province"
            size="small"
            columns={columns}
            dataSource={data.provinces || []}
            pagination={data.provinces?.length > 10 ? { pageSize: 10, showSizeChanger: true } : false}
            scroll={{ x: 900 }}
          />
        )}
      </Spin>
    </Card>
  );
};

export default QualityPanel;
