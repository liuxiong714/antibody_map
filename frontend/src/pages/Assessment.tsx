import React, { useState } from 'react';
import { Card, Button, Row, Col, Statistic, Spin, Empty, Progress, Tag, message, InputNumber, Table, Tooltip } from 'antd';
import type { TableProps } from 'antd';
import { SafetyOutlined, InfoCircleOutlined } from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import DiseaseSelector from '../components/DiseaseSelector';
import ProvinceSelector from '../components/ProvinceSelector';
import { getImmuneBarrier } from '../services/map';
import { ImmuneBarrierData } from '../types';

const STATUS_CONFIG: Record<string, { color: string; label: string }> = {
  established: { color: '#52c41a', label: '免疫屏障已建立' },
  borderline: { color: '#faad14', label: '接近但未完全建立' },
  insufficient: { color: '#ff4d4f', label: '免疫屏障不足' },
  undetermined: { color: '#bfbfbf', label: '数据不足' },
  no_data: { color: '#999', label: '暂无数据' },
};

const HIT_SOURCE_LABEL: Record<string, string> = {
  foi: 'FOI 估算',
  who: 'WHO 建议',
  ref_r0: '文献 R0',
  none: '无',
};

interface ProvinceMatrixRow {
  province: string;
  data_point_count: number;
  total_samples: number;
  weighted_positivity_rate: number | null;
  weighted_avg_foi_per_year: number | null;
  estimated_r0_from_foi: number | null;
  hit_target_percent: number | null;
  status: string;
}

const Assessment: React.FC = () => {
  const [disease, setDisease] = useState('');
  const [province, setProvince] = useState('');
  const [yearStart, setYearStart] = useState<number | null>(null);
  const [yearEnd, setYearEnd] = useState<number | null>(null);
  const [ageMin, setAgeMin] = useState<number | null>(null);
  const [ageMax, setAgeMax] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ImmuneBarrierData | null>(null);

  const handleQuery = async () => {
    if (!disease) { message.warning('请选择疾病'); return; }
    setLoading(true);
    setResult(null);
    try {
      const params: Record<string, unknown> = { disease };
      if (province) params.province = province;
      if (yearStart) params.year_start = yearStart;
      if (yearEnd) params.year_end = yearEnd;
      if (ageMin != null) params.age_min = ageMin;
      if (ageMax != null) params.age_max = ageMax;
      const resp = await getImmuneBarrier(params);
      setResult(resp);
    } catch {
      message.error('查询失败');
    } finally {
      setLoading(false);
    }
  };

  const cfg = result ? STATUS_CONFIG[result.status] || STATUS_CONFIG.no_data : null;
  const rate = result?.summary?.weighted_positivity_rate;
  const hitTarget = result?.summary?.hit_target_used_percent ?? result?.who_threshold;
  const hitSource = result?.summary?.hit_target_source ?? 'none';

  const progressPercent = (hitTarget && rate != null) ? Math.min((rate / hitTarget) * 100, 100) : 0;

  // ECharts yearly trend
  const trendOption = result?.yearly_trend?.length ? {
    xAxis: { type: 'category', data: result.yearly_trend.map((t) => t.year) },
    yAxis: { type: 'value', name: '阳性率 (%)' },
    tooltip: { trigger: 'axis' },
    series: [
      {
        type: 'line', data: result.yearly_trend.map((t) => t.weighted_positivity),
        markLine: hitTarget ? {
          silent: true,
          data: [{ yAxis: hitTarget, label: { formatter: `阈值: ${hitTarget}%` }, lineStyle: { color: '#ff4d4f', type: 'dashed' } }],
        } : undefined,
      },
    ],
  } : null;

  // 年龄分层柱状图
  const ageChartOption = result?.age_groups?.length ? {
    xAxis: {
      type: 'category',
      data: result.age_groups.map((g) => g.age_group),
      axisLabel: { interval: 0 },
    },
    yAxis: { type: 'value', name: '阳性率 (%)' },
    tooltip: {
      trigger: 'axis',
      formatter: (params: Array<{ dataIndex: number; value: number }>) => {
        const idx = params[0]?.dataIndex;
        if (idx == null || !result.age_groups) return '';
        const g = result.age_groups[idx];
        return `${g.age_group}<br/>阳性率: ${g.weighted_positivity_rate ?? '-'}%<br/>FOI: ${g.weighted_avg_foi_per_year ?? '-'} /年<br/>样本: ${g.total_samples}<br/>状态: ${STATUS_CONFIG[g.status]?.label ?? g.status}`;
      },
    },
    series: [
      {
        type: 'bar',
        data: result.age_groups.map((g) => ({
          value: g.weighted_positivity_rate ?? 0,
          itemStyle: { color: STATUS_CONFIG[g.status]?.color ?? '#999' },
        })),
        barWidth: '40%',
        markLine: hitTarget ? {
          silent: true,
          data: [{ yAxis: hitTarget, label: { formatter: `阈值: ${hitTarget}%` }, lineStyle: { color: '#ff4d4f', type: 'dashed' } }],
        } : undefined,
      },
    ],
  } : null;

  // 省份矩阵表格列定义
  const provinceColumns: TableProps<ProvinceMatrixRow>['columns'] = [
    { title: '省份', dataIndex: 'province', key: 'province', width: 100 },
    { title: '数据点数', dataIndex: 'data_point_count', key: 'dp', width: 80, sorter: (a, b) => a.data_point_count - b.data_point_count },
    {
      title: '样本量', dataIndex: 'total_samples', key: 'samples', width: 100,
      sorter: (a, b) => a.total_samples - b.total_samples,
      render: (v: number) => v.toLocaleString(),
    },
    {
      title: '加权阳性率', dataIndex: 'weighted_positivity_rate', key: 'wpr', width: 110,
      sorter: (a, b) => (a.weighted_positivity_rate ?? -1) - (b.weighted_positivity_rate ?? -1),
      render: (v: number | null) => v != null ? `${v}%` : '-',
    },
    {
      title: 'FOI (/年)', dataIndex: 'weighted_avg_foi_per_year', key: 'foi', width: 100,
      sorter: (a, b) => (a.weighted_avg_foi_per_year ?? -1) - (b.weighted_avg_foi_per_year ?? -1),
      render: (v: number | null) => v != null ? v.toFixed(4) : '-',
    },
    {
      title: '估算 R0', dataIndex: 'estimated_r0_from_foi', key: 'r0', width: 90,
      sorter: (a, b) => (a.estimated_r0_from_foi ?? -1) - (b.estimated_r0_from_foi ?? -1),
      render: (v: number | null) => v != null ? v.toFixed(2) : '-',
    },
    {
      title: '屏障状态', dataIndex: 'status', key: 'status', width: 140,
      filters: [
        { text: '已建立', value: 'established' },
        { text: '接近', value: 'borderline' },
        { text: '不足', value: 'insufficient' },
        { text: '数据不足', value: 'undetermined' },
      ],
      onFilter: (value, record) => record.status === value,
      render: (s: string) => {
        const c = STATUS_CONFIG[s] || STATUS_CONFIG.no_data;
        return <Tag color={c.color}>{c.label}</Tag>;
      },
    },
  ];

  return (
    <>
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={[12, 12]} align="middle">
          <Col><strong style={{ color: '#ff4d4f' }}>* </strong></Col>
          <Col><DiseaseSelector value={disease} onChange={setDisease} allowClear={false} /></Col>
          <Col><ProvinceSelector value={province} onChange={setProvince} /></Col>
          <Col><InputNumber placeholder="起始年份" value={yearStart} onChange={setYearStart} style={{ width: 110 }} /></Col>
          <Col><InputNumber placeholder="结束年份" value={yearEnd} onChange={setYearEnd} style={{ width: 110 }} /></Col>
          <Col><InputNumber placeholder="最小年龄" value={ageMin} onChange={setAgeMin} min={0} max={120} style={{ width: 110 }} /></Col>
          <Col><InputNumber placeholder="最大年龄" value={ageMax} onChange={setAgeMax} min={0} max={120} style={{ width: 110 }} /></Col>
          <Col>
            <Button type="primary" icon={<SafetyOutlined />} onClick={handleQuery} loading={loading}>
              查询免疫屏障
            </Button>
          </Col>
        </Row>
      </Card>

      <Spin spinning={loading}>
        {!result ? (
          <Empty description="请选择疾病并点击查询" />
        ) : (
          <>
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={6}>
                <Card><Statistic title="数据点数" value={result?.summary?.total_data_points ?? 0} /></Card>
              </Col>
              <Col span={6}>
                <Card><Statistic title="涉及文献数" value={result?.summary?.total_literatures ?? 0} /></Card>
              </Col>
              <Col span={6}>
                <Card><Statistic title="总样本量" value={result?.summary?.total_samples ?? 0} formatter={(v) => (v as number).toLocaleString()} /></Card>
              </Col>
              <Col span={6}>
                <Card>
                  <Statistic
                    title="加权阳性率"
                    value={rate != null ? Number(rate).toFixed(2) + '%' : '-'}
                    valueStyle={{ color: cfg?.color }}
                  />
                </Card>
              </Col>
            </Row>

            <Card title="免疫屏障阈值对比" style={{ marginBottom: 16 }}>
              <Row align="middle" gutter={16} style={{ marginBottom: 12 }}>
                <Col>
                  <Tooltip title={`阈值来源：${HIT_SOURCE_LABEL[hitSource] ?? hitSource}`}>
                    <Tag color="blue" style={{ fontSize: 16, padding: '4px 12px' }}>
                      阈值: {hitTarget ?? '-'}%（{HIT_SOURCE_LABEL[hitSource] ?? hitSource}）
                    </Tag>
                  </Tooltip>
                </Col>
                {result?.who_threshold != null && result.summary?.hit_target_source !== 'who' && (
                  <Col>
                    <Tag color="default">WHO 推荐: {result.who_threshold}%</Tag>
                  </Col>
                )}
                <Col flex="auto">
                  <Progress
                    percent={progressPercent}
                    format={() => `${rate != null ? rate : 0}% / ${hitTarget ?? '-'}%`}
                    strokeColor={cfg?.color}
                    status={result.status === 'established' ? 'success' : 'active'}
                  />
                </Col>
                <Col>
                  <Tag color={cfg?.color} style={{ fontSize: 14, padding: '4px 12px' }}>
                    {cfg?.label}
                  </Tag>
                </Col>
              </Row>
              <Row gutter={16}>
                <Col span={6}>
                  <Statistic
                    title="加权平均 FOI"
                    value={result?.summary?.weighted_avg_foi_per_year != null ? Number(result.summary.weighted_avg_foi_per_year).toFixed(4) : '-'}
                    suffix={result?.summary?.weighted_avg_foi_per_year != null ? '/年' : ''}
                  />
                </Col>
                <Col span={6}>
                  <Statistic
                    title="估算 R0 (FOI)"
                    value={result?.summary?.estimated_r0_from_foi != null ? Number(result.summary.estimated_r0_from_foi).toFixed(2) : '-'}
                  />
                </Col>
                <Col span={6}>
                  <Statistic
                    title="HIT (FOI 估算)"
                    value={result?.summary?.hit_from_foi_percent != null ? Number(result.summary.hit_from_foi_percent).toFixed(2) + '%' : '-'}
                  />
                </Col>
                <Col span={6}>
                  <Statistic
                    title="HIT (文献 R0)"
                    value={result?.summary?.hit_from_reference_r0_percent != null ? Number(result.summary.hit_from_reference_r0_percent).toFixed(2) + '%' : '-'}
                  />
                </Col>
              </Row>
              {result?.r0_reference && result.r0_reference.typical != null && (
                <div style={{ marginTop: 8, color: '#888', fontSize: 12 }}>
                  文献 R0 参考：典型 {result.r0_reference.typical}（区间 {result.r0_reference.range_low ?? '—'} ~ {result.r0_reference.range_high ?? '—'}）
                </div>
              )}
            </Card>

            <Card
              title={<><InfoCircleOutlined /> 评估结论</>}
              style={{ marginBottom: 16, background: '#fafafa' }}
            >
              <p style={{ fontSize: 15, lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>{result.assessment}</p>
            </Card>

            {trendOption && (
              <Card title="逐年趋势" style={{ marginBottom: 16 }}>
                <ReactECharts option={trendOption} style={{ height: 350 }} />
              </Card>
            )}

            {ageChartOption && (
              <Card title="年龄分层分析" style={{ marginBottom: 16 }}>
                <ReactECharts option={ageChartOption} style={{ height: 350 }} />
              </Card>
            )}

            {result?.province_matrix && result.province_matrix.length > 0 && (
              <Card title="省份对比矩阵" style={{ marginBottom: 16 }}>
                <Table<ProvinceMatrixRow>
                  rowKey={(r) => r.province}
                  columns={provinceColumns}
                  dataSource={result.province_matrix}
                  pagination={{ pageSize: 10, showSizeChanger: true }}
                  size="small"
                />
              </Card>
            )}
          </>
        )}
      </Spin>
    </>
  );
};

export default Assessment;
