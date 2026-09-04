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
});