/**
 * TopBottomRank：省际公平性 Top/Bottom 排名表。
 *
 * 展示达标 TOP5 与未达标 BOTTOM5 省份（按样本量加权阳性率），
 * 含 95% CI 与是否达标标签。
 */
import React from 'react';
import { Card, Col, Empty, Row, Table, Tag, Typography } from 'antd';
import type { EquityAnalysisResponse, EquityProvinceRow } from '../types';

interface Props {
  data: EquityAnalysisResponse | null;
}

const makeColumns = () => [
  { title: '排名', dataIndex: 'rank', key: 'rank', width: 60 },
  { title: '省份', dataIndex: 'province', key: 'province', width: 110 },
  {
    title: '加权阳性率',
    dataIndex: 'weighted_positivity',
    key: 'weighted_positivity',
    width: 110,
    render: (v: number | null) => (v != null ? <b>{v.toFixed(2)}%</b> : '-'),
  },
  {
    title: '95% CI',
    key: 'ci',
    width: 150,
    render: (_: unknown, r: EquityProvinceRow) =>
      r.ci_lower != null && r.ci_upper != null ? `${r.ci_lower.toFixed(1)} ~ ${r.ci_upper.toFixed(1)}` : '-',
  },
  {
    title: '样本量',
    dataIndex: 'total_samples',
    key: 'total_samples',
    width: 100,
    render: (v: number) => v.toLocaleString(),
  },
  {
    title: '研究数',
    dataIndex: 'n_studies',
    key: 'n_studies',
    width: 80,
  },
  {
    title: '达标',
    dataIndex: 'is_meeting_target',
    key: 'is_meeting_target',
    width: 90,
    render: (v: boolean | null) =>
      v == null ? '-' : v ? <Tag color="green">达标</Tag> : <Tag color="red">未达标</Tag>,
  },
];

const RankCard: React.FC<{ title: string; rows: EquityProvinceRow[]; color: string }> = ({ title, rows, color }) => (
  <Card
    size="small"
    title={<Typography.Text style={{ color }} strong>{title}</Typography.Text>}
    style={{ height: '100%' }}
  >
    {rows.length > 0 ? (
      <Table<EquityProvinceRow>
        rowKey={(r) => `${title}-${r.province}`}
        size="small"
        columns={makeColumns()}
        dataSource={rows}
        pagination={false}
        scroll={{ x: 700 }}
      />
    ) : (
      <Empty description="暂无数据" />
    )}
  </Card>
);

const TopBottomRank: React.FC<Props> = ({ data }) => {
  if (!data) return <Empty description="暂无省际排名数据" />;
  return (
    <Row gutter={16}>
      <Col span={12}>
        <RankCard title="达标 TOP5" rows={data.top_provinces || []} color="#52c41a" />
      </Col>
      <Col span={12}>
        <RankCard title="未达标 BOTTOM5" rows={data.bottom_provinces || []} color="#f5222d" />
      </Col>
    </Row>
  );
};

export default TopBottomRank;
