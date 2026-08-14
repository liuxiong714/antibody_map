/**
 * CoverageReviewTable：按疾病维度的审核状态统计表。
 *
 * 列：疾病 / 数据点数 / 样本量合计 / 已审核通过(点数·样本) /
 *     待审核(点数·样本) / 已拒绝(点数·样本) / 审核通过率(Progress)。
 * 「待审核」单元格在待审核数 > 0 时红色高亮并提示「需继续审核」。
 */
import React from 'react';
import { Progress, Table, Tooltip, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { DISEASES } from '../utils/constants';
import type { CoverageReviewDisease } from '../types';

interface Props {
  data: CoverageReviewDisease[];
  loading?: boolean;
}

const diseaseNameMap: Record<string, string> = Object.fromEntries(
  DISEASES.map((d) => [d.key, d.name_cn]),
);

const fmt = (n: number) => n.toLocaleString('en-US');

const CoverageReviewTable: React.FC<Props> = ({ data, loading }) => {
  const columns: ColumnsType<CoverageReviewDisease> = [
    {
      title: '疾病',
      dataIndex: 'disease',
      key: 'disease',
      width: 120,
      render: (d: string) => diseaseNameMap[d] || d,
    },
    {
      title: '数据点数',
      dataIndex: 'total_points',
      key: 'total_points',
      width: 100,
      sorter: (a, b) => a.total_points - b.total_points,
      render: (v: number) => fmt(v),
    },
    {
      title: '样本量合计',
      dataIndex: 'total_samples',
      key: 'total_samples',
      width: 110,
      sorter: (a, b) => a.total_samples - b.total_samples,
      render: (v: number) => fmt(v),
    },
    {
      title: '已审核通过 (点数/样本)',
      key: 'approved',
      width: 150,
      render: (_, r) => (
        <span style={{ color: '#52c41a' }}>
          {fmt(r.approved_points)} / {fmt(r.approved_samples)}
        </span>
      ),
    },
    {
      title: '待审核 (点数/样本)',
      key: 'pending',
      width: 150,
      render: (_, r) => {
        const hasPending = r.pending_points > 0;
        return (
          <Tooltip title={hasPending ? '需继续审核' : undefined}>
            <span
              style={{
                color: hasPending ? '#f5222d' : undefined,
                fontWeight: hasPending ? 600 : undefined,
              }}
            >
              {fmt(r.pending_points)} / {fmt(r.pending_samples)}
              {hasPending && <span style={{ fontSize: 12, marginLeft: 4 }}>需继续审核</span>}
            </span>
          </Tooltip>
        );
      },
    },
    {
      title: '已拒绝 (点数/样本)',
      key: 'rejected',
      width: 150,
      render: (_, r) => (
        <span style={{ color: r.rejected_points > 0 ? '#fa8c16' : undefined }}>
          {fmt(r.rejected_points)} / {fmt(r.rejected_samples)}
        </span>
      ),
    },
    {
      title: '审核通过率',
      dataIndex: 'approval_rate',
      key: 'approval_rate',
      width: 180,
      sorter: (a, b) => a.approval_rate - b.approval_rate,
      render: (v: number) => {
        const pct = Math.round(v * 100);
        return (
          <Progress
            percent={pct}
            size="small"
            strokeColor={pct >= 80 ? '#52c41a' : pct >= 50 ? '#faad14' : '#f5222d'}
          />
        );
      },
    },
  ];

  return (
    <Table<CoverageReviewDisease>
      rowKey="disease"
      size="small"
      loading={loading}
      columns={columns}
      dataSource={data}
      pagination={data.length > 10 ? { pageSize: 10, showSizeChanger: true } : false}
      scroll={{ x: 960 }}
      title={() => (
        <Typography.Text type="secondary">
          按疾病统计审核状态（待审核数大于 0 的疾病建议优先继续审核）
        </Typography.Text>
      )}
    />
  );
};

export default CoverageReviewTable;