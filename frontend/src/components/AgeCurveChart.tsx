/**
 * AgeCurveChart：血清阳性率-年龄曲线。
 *
 * 主图 = 观测点散点（气泡大小 ∝ 样本量）+ 惩罚样条平滑线 + 95% 置信带；
 * 副图 = 年龄别 FOI 曲线（y 轴单位 /年）。复用 chartBuilders 工厂。
 */
import React, { useMemo } from 'react';
import { Alert, Card, Empty, Space, Spin, Tag } from 'antd';
import EChart from './EChart';
import type { AgeCurveResponse } from '../types';
import { ageCurveWithBand, foiLineChart } from '../utils/chartBuilders';

interface Props {
  data: AgeCurveResponse | null;
  loading?: boolean;
  title?: string;
  height?: number;
}

const AgeCurveChart: React.FC<Props> = ({
  data,
  loading,
  title = '血清阳性率-年龄曲线',
  height = 300,
}) => {
  const mainOption = useMemo(() => {
    if (!data || !data.curve || data.curve.length === 0) return null;
    return ageCurveWithBand(
      '拟合 P(a)（惩罚样条 + 95% CI）',
      data.curve,
      data.points.map((p) => ({ age: p.age_mid, prevalence: p.prevalence, n: p.n })),
    );
  }, [data]);

  const foiOption = useMemo(() => {
    if (!data || !data.foi_curve || data.foi_curve.length === 0) return null;
    return foiLineChart('年龄别 FOI（感染力）', data.foi_curve);
  }, [data]);

  return (
    <Card
      size="small"
      title={<Tag color="blue">年龄曲线</Tag>}
      extra={
        data ? (
          <span style={{ fontSize: 12, color: '#999' }}>
            数据点 {data.n_points}
            {data.meta?.lambda_smooth != null ? ` · λp=${data.meta.lambda_smooth.toExponential(2)}` : ''}
            {data.meta?.dropped_points ? ` · 剔除 ${data.meta.dropped_points} 条` : ''}
          </span>
        ) : undefined
      }
    >
      <Spin spinning={!!loading}>
        {mainOption ? (
          <EChart option={mainOption} style={{ height }} />
        ) : (
          <Empty
            description="暂无年龄曲线数据（需≥8个可计算年龄中点的已审核主估计）"
            style={{ padding: '30px 0' }}
          />
        )}
        {foiOption ? <EChart option={foiOption} style={{ height: height - 40 }} /> : null}
        {data ? (
          <>
            {(data.meta?.covarage_warning || data.meta?.monotonic_violation) && (
              <Alert
                type="warning"
                showIcon
                style={{ marginTop: 8 }}
                message={[
                  data.meta?.covarage_warning ? '年龄覆盖稀疏（相邻年龄点间隔>10年或跨度<5年）' : null,
                  data.meta?.monotonic_violation ? '拟合曲线出现下降段（阳性率-年龄预期非减）' : null,
                ]
                  .filter(Boolean)
                  .join('；')}
              />
            )}
          </>
        ) : null}
      </Spin>
    </Card>
  );
};

export default AgeCurveChart;
