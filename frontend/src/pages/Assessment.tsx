import React, { useState } from 'react';
import { Card, Button, Row, Col, Statistic, Spin, Empty, Progress, Tag, message, InputNumber } from 'antd';
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
  no_data: { color: '#999', label: '暂无数据' },
};

const Assessment: React.FC = () => {
  const [disease, setDisease] = useState('');
  const [province, setProvince] = useState('');
  const [yearStart, setYearStart] = useState<number | null>(null);
  const [yearEnd, setYearEnd] = useState<number | null>(null);
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
      const resp = await getImmuneBarrier(params);
      setResult(resp.data);
    } catch {
      message.error('查询失败');
    } finally {
      setLoading(false);
    }
  };

  const cfg = result ? STATUS_CONFIG[result.status] || STATUS_CONFIG.no_data : null;
  const rate = result?.summary.weighted_positivity_rate;
  const threshold = result?.who_threshold;
  const progressPercent = (threshold && rate != null) ? Math.min((rate / threshold) * 100, 100) : 0;

  // ECharts yearly trend
  const trendOption = result?.yearly_trend?.length ? {
    xAxis: { type: 'category', data: result.yearly_trend.map((t) => t.year) },
    yAxis: { type: 'value', name: '阳性率 (%)' },
    tooltip: { trigger: 'axis' },
    series: [
      {
        type: 'line', data: result.yearly_trend.map((t) => t.weighted_positivity),
        markLine: threshold ? {
          silent: true,
          data: [{ yAxis: threshold, label: { formatter: `WHO 阈值: ${threshold}%` }, lineStyle: { color: '#ff4d4f', type: 'dashed' } }],
        } : undefined,
      },
    ],
  } : null;

  return (
    <>
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={16} align="middle">
          <Col><strong style={{ color: '#ff4d4f' }}>* </strong></Col>
          <Col><DiseaseSelector value={disease} onChange={setDisease} allowClear={false} /></Col>
          <Col><ProvinceSelector value={province} onChange={setProvince} /></Col>
          <Col><InputNumber placeholder="起始年份" value={yearStart} onChange={setYearStart} style={{ width: 120 }} /></Col>
          <Col><InputNumber placeholder="结束年份" value={yearEnd} onChange={setYearEnd} style={{ width: 120 }} /></Col>
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
                <Card><Statistic title="数据点数" value={result.summary.total_data_points} /></Card>
              </Col>
              <Col span={6}>
                <Card><Statistic title="涉及文献数" value={result.summary.total_literatures} /></Card>
              </Col>
              <Col span={6}>
                <Card><Statistic title="总样本量" value={result.summary.total_samples} formatter={(v) => (v as number).toLocaleString()} /></Card>
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

            <Card title="WHO 阈值对比" style={{ marginBottom: 16 }}>
              <Row align="middle" gutter={16}>
                <Col>
                  <Tag color="blue" style={{ fontSize: 16, padding: '4px 12px' }}>
                    WHO 推荐阈值: {threshold ?? '-'}%
                  </Tag>
                </Col>
                <Col flex="auto">
                  <Progress
                    percent={progressPercent}
                    format={() => `${rate != null ? rate : 0}% / ${threshold ?? '-'}%`}
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
          </>
        )}
      </Spin>
    </>
  );
};

export default Assessment;
