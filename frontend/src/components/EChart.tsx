/**
 * ReactEChartsCore 封装：传入按需加载的 echarts 实例。
 * 替代 echarts-for-react 默认（全量 echarts）以减小打包体积。
 */
import React, { useEffect, useRef, useCallback } from 'react';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from '../lib/echarts';

interface EChartProps {
  option: Record<string, unknown>;
  style?: React.CSSProperties;
  className?: string;
  notMerge?: boolean;
  lazyUpdate?: boolean;
  onEvents?: Record<string, (params: unknown) => void>;
}

const EChart = React.forwardRef<ReactEChartsCore, EChartProps>(({
  option,
  style,
  className,
  notMerge,
  lazyUpdate,
  onEvents,
}, ref) => {
  const innerRef = useRef<ReactEChartsCore>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  React.useImperativeHandle(ref, () => innerRef.current as ReactEChartsCore);

  const resize = useCallback(() => {
    const inst = innerRef.current as unknown as { getEchartsInstance?: () => { resize: () => void } } | null;
    inst?.getEchartsInstance?.()?.resize();
  }, []);

  // 监听外层容器尺寸变化，容器变了就主动 resize
  useEffect(() => {
    const dom = wrapRef.current;
    if (!dom) return;
    const ro = new ResizeObserver(() => resize());
    ro.observe(dom);
    return () => ro.disconnect();
  }, [resize]);

  return (
    <div ref={wrapRef} style={{ width: '100%', height: '100%' }}>
      <ReactEChartsCore
        ref={innerRef}
        echarts={echarts}
        option={option}
        style={{ ...style, width: '100%' }}
        className={className}
        notMerge={notMerge}
        lazyUpdate={lazyUpdate}
        onEvents={onEvents}
        autoResize
      />
    </div>
  );
});

EChart.displayName = 'EChart';

export default EChart;
