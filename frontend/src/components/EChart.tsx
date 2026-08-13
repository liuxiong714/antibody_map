/**
 * ReactEChartsCore 封装：传入按需加载的 echarts 实例。
 * 替代 echarts-for-react 默认（全量 echarts）以减小打包体积。
 *
 * 用法与 echarts-for-react 的 <ReactECharts> 一致：
 *   <EChart option={...} style={{ height: 350 }} />
 */
import React from 'react';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from '../lib/echarts';

interface EChartProps {
  // 使用宽松类型：echarts option 对象中的 type 字段常被 TS 推断为 string，
  // 严格 EChartsOption 会拒绝非字面量类型，故此处放宽以兼容现有调用。
  option: Record<string, unknown>;
  style?: React.CSSProperties;
  className?: string;
  notMerge?: boolean;
  lazyUpdate?: boolean;
  onEvents?: Record<string, (params: unknown) => void>;
}

const EChart: React.FC<EChartProps> = ({
  option,
  style,
  className,
  notMerge,
  lazyUpdate,
  onEvents,
}) => {
  return (
    <ReactEChartsCore
      echarts={echarts}
      option={option}
      style={style}
      className={className}
      notMerge={notMerge}
      lazyUpdate={lazyUpdate}
      onEvents={onEvents}
    />
  );
};

export default EChart;