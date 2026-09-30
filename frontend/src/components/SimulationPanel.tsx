/**
 * SimulationPanel：免疫屏障模拟面板（FOI 反推 R0/HIT + 接种情景）。
 *
 * - 滑块设定「假设基础接种覆盖」与「加强针比例」
 * - 点击运行 → 调用 /analysis/simulate
 * - 展示：当前屏障状态（观测阳性率 / FOI / R0 / HIT）、模拟结果、达标所需覆盖
 */
import React from 'react';
import { Alert, Button, Card, Col, Row, Slider, Space, Spin, Statistic, Tag, Typography } from 'antd';
import { ExperimentOutlined } from '@ant-design/icons';
import type { BarrierStatus, SimulationResponse } from '../types';

interface Props {
  data: SimulationResponse | null;
  loading?: boolean;
  coverage: number;
  booster: number;
  onCoverageChange: (v: number) => void;
  onBoosterChange: (v: number) => void;
  onRun: () => void;
}

const STATUS_META: Record<BarrierStatus, { label: string; color: string }> = {
  reached: { label: '已达成群体免疫', color: 'green' },
  near: { label: '接近达标（差≤10百分点）', color: 'gold' },
  not_reached: { label: '未达标', color: 'red' },
  undetermined: { label: '无法判定', color: 'default' },
};

const SimulationPanel: React.FC<Props> = ({
  data,
  loading,
  coverage,
  booster,
  onCoverageChange,
  onBoosterChange,
  onRun,
}) => {
  const current = data?.current;
  const simulated = data?.simulated;

  return (
    <Card
      size="small"
      title={
        <Space>
          <ExperimentOutlined />
          <span>免疫屏障模拟（FOI 反推 R0/HIT）</span>
        </Space>
      }
    >
      <Spin spinning={!!loading}>
        <Row gutter={16}>
          <Col span={10}>
            <div style={{ marginBottom: 8 }}>
              <Typography.Text strong>假设基础接种覆盖：{coverage.toFixed(0)}%</Typography.Text>
              <Slider min={0} max={100} value={coverage} onChange={onCoverageChange} />
            </div>
            <div style={{ marginBottom: 16 }}>
              <Typography.Text strong>加强针比例（作用于未免疫者）：{booster.toFixed(0)}%</Typography.Text>
              <Slider min={0} max={100} value={booster} onChange={onBoosterChange} />
            </div>
            <Button type="primary" onClick={onRun} icon={<ExperimentOutlined />} loading={!!loading}>
              运行模拟
            </Button>
          </Col>
          <Col span={7}>
            <Card size="small" title="当前屏障状态">
              {current ? (
                <Space direction="vertical" size={4}>
                  <span>
                    观测加权阳性率：<b>{current.weighted_positivity_percent != null ? current.weighted_positivity_percent.toFixed(1) + '%' : '-'}</b>
                  </span>
                  <span>加权 FOI：{current.weighted_avg_foi_per_year != null ? current.weighted_avg_foi_per_year.toFixed(4) : '-'}/年</span>
                  <span>估计 R0：{current.estimated_r0 != null ? current.estimated_r0.toFixed(1) : '-'}（文献典型值 {current.r0_reference?.typical ?? '-'}）</span>
                  <span>屏障目标 HIT：{current.hit_percent != null ? current.hit_percent.toFixed(1) + '%' : '-'}</span>
                  <Tag color={STATUS_META[current.status].color}>{STATUS_META[current.status].label}</Tag>
                </Space>
              ) : (
                <Typography.Text type="secondary">暂无当前状态数据</Typography.Text>
              )}
            </Card>
          </Col>
          <Col span={7}>
            <Card size="small" title="模拟结果">
              {simulated ? (
                <Space direction="vertical" size={4}>
                  <span>
                    有效免疫比例：<b>{simulated.effective_coverage_percent.toFixed(1)}%</b>
                  </span>
                  <span>
                    距目标差距：
                    {simulated.gap_to_hit_percent != null
                      ? simulated.gap_to_hit_percent > 0
                        ? <span style={{ color: '#f5222d' }}>尚差 {simulated.gap_to_hit_percent.toFixed(1)} 百分点</span>
                        : <span style={{ color: '#52c41a' }}>已超出 {Math.abs(simulated.gap_to_hit_percent).toFixed(1)} 百分点</span>
                      : '-'}
                  </span>
                  <span>加强针增益：{simulated.gain_from_booster_percent.toFixed(1)} 百分点</span>
                  <Tag color={STATUS_META[simulated.status].color}>{STATUS_META[simulated.status].label}</Tag>
                </Space>
              ) : (
                <Typography.Text type="secondary">点击运行查看模拟结果</Typography.Text>
              )}
            </Card>
          </Col>
        </Row>

        {data && (
          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col span={8}>
              <Statistic
                title="当前假设基础覆盖"
                value={data.assumed_coverage_percent}
                suffix="%"
              />
            </Col>
            <Col span={8}>
              <Statistic
                title="当前加强针比例"
                value={data.booster_rate_percent}
                suffix="%"
              />
            </Col>
            <Col span={8}>
              <Statistic
                title="达标所需基础覆盖（在给定加强针下）"
                value={data.required_coverage_to_reach_hit != null ? data.required_coverage_to_reach_hit : '不可行'}
                suffix={data.required_coverage_to_reach_hit != null ? '%' : undefined}
              />
            </Col>
          </Row>
        )}

        {data?.notes?.length ? (
          <Alert type="warning" showIcon style={{ marginTop: 12 }} message={data.notes.join('；')} />
        ) : null}
      </Spin>
    </Card>
  );
};

export default SimulationPanel;
