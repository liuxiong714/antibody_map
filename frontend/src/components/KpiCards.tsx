/**
 * KpiCards：通用 KPI 指标卡片组（antd5 Statistic）。
 *
 * 用于公平性 / 数据质量 / 目标达成等分析页展示关键指标：
 * 传入 items 数组，每个 item 包含 label / value / 格式化与配色，
 * 组件内部按 gutter 栅格自动排布。
 */
import React from 'react';
import { Card, Col, Row, Statistic } from 'antd';

export interface KpiItem {
  label: string;
  value: number | string | null;
  /** 数值精度（仅对 number 生效） */
  precision?: number;
  /** 数值后缀（如 %） */
  suffix?: string;
  /** 前缀（如 ¥） */
  prefix?: string;
  /** 数值颜色 */
  valueStyle?: React.CSSProperties;
  /** 提示文本（悬浮展示） */
  tip?: string;
}

interface Props {
  items: KpiItem[];
  loading?: boolean;
  span?: number;
}

const KpiCards: React.FC<Props> = ({ items, loading, span = 6 }) => {
  return (
    <Row gutter={16}>
      {items.map((it, idx) => (
        <Col span={span} key={`${it.label}-${idx}`} style={{ marginBottom: 16 }}>
          <Card size="small" loading={loading}>
            <Statistic
              title={it.tip ? (
                <span title={it.tip}>{it.label}</span>
              ) : it.label}
              value={it.value ?? '-'}
              precision={it.value != null ? it.precision : undefined}
              suffix={it.suffix}
              prefix={it.prefix}
              valueStyle={it.valueStyle}
            />
          </Card>
        </Col>
      ))}
    </Row>
  );
};

export default KpiCards;
