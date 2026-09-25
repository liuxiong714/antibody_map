import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';

// mock echarts core：避免 jsdom 环境运行真实 ECharts（canvas/ResizeObserver 依赖）。
// mock 组件把 option/style 透传进 dataset，便于断言封装是否原样转发 props。
vi.mock('echarts-for-react/lib/core', () => ({
  // eslint-disable-next-line react/display-name
  default: ({ option, style, className, ...rest }: any) => {
    const { notMerge, lazyUpdate, onEvents } = rest;
    return (
      <div
        data-testid="echart-core"
        data-option={JSON.stringify(option ?? null)}
        data-merge={String(notMerge ?? '')}
        data-lazy={String(lazyUpdate ?? '')}
        data-event={String(!!onEvents)}
        className={className}
        style={style}
      />
    );
  },
}));

import EChart from '../EChart';

describe('EChart 封装（冒烟）', () => {
  it('透传 option 给 echarts core', () => {
    const option = { series: [{ type: 'line', data: [1, 2, 3] }] };
    const { getByTestId } = render(<EChart option={option} />);
    const el = getByTestId('echart-core');
    expect(JSON.parse(el.getAttribute('data-option')!)).toEqual(option);
  });

  it('透传 style 与 className', () => {
    const { getByTestId } = render(
      <EChart option={{}} style={{ height: 350 }} className="my-chart" />,
    );
    const el = getByTestId('echart-core');
    expect(el.getAttribute('class')).toBe('my-chart');
    expect(el.style.height).toBe('350px');
  });

  it('透传 notMerge / lazyUpdate / onEvents', () => {
    const onEvents = { click: () => {} };
    const { getByTestId } = render(
      <EChart option={{}} notMerge lazyUpdate onEvents={onEvents} />,
    );
    const el = getByTestId('echart-core');
    expect(el.getAttribute('data-merge')).toBe('true');
    expect(el.getAttribute('data-lazy')).toBe('true');
    expect(el.getAttribute('data-event')).toBe('true');
  });

  it('容器尺寸变化时触发 resize 回调（ResizeObserver → resize）', () => {
    // 用能捕获回调的 ResizeObserver 替换测试环境桩，手动触发尺寸变化
    const original = globalThis.ResizeObserver;
    const callbacks: Array<() => void> = [];
    class CapturingResizeObserver {
      constructor(cb: () => void) {
        callbacks.push(cb);
      }
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    }
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver = CapturingResizeObserver;

    try {
      const { unmount } = render(<EChart option={{}} />);
      expect(callbacks).toHaveLength(1);
      // 触发回调：未挂载 echarts 实例时应安全短路，不抛异常
      expect(() => callbacks[0]()).not.toThrow();
      unmount();
    } finally {
      (globalThis as { ResizeObserver?: unknown }).ResizeObserver = original;
    }
  });
});