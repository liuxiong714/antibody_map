import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/react';

import StatusBadge from '../StatusBadge';

vi.mock('antd', async (importOriginal) => {
  const actual = await importOriginal<typeof import('antd')>();
  const Tag = ({ color, children }: { color?: string; children?: React.ReactNode }) => (
    <div data-testid="tag" data-color={color ?? 'default'}>
      {children}
    </div>
  );
  return { ...actual, Tag };
});

describe('StatusBadge', () => {
  it('failed 显示红色"失败"', () => {
    const { getByTestId } = render(<StatusBadge status="failed" />);
    expect(getByTestId('tag')).toHaveAttribute('data-color', 'red');
    expect(getByTestId('tag')).toHaveTextContent('失败');
  });

  it('processing 显示"提取中"', () => {
    const { getByTestId } = render(<StatusBadge status="processing" />);
    expect(getByTestId('tag')).toHaveAttribute('data-color', 'processing');
    expect(getByTestId('tag')).toHaveTextContent('提取中');
  });

  it('done 显示绿色"已完成"', () => {
    const { getByTestId } = render(<StatusBadge status="done" />);
    expect(getByTestId('tag')).toHaveAttribute('data-color', 'green');
    expect(getByTestId('tag')).toHaveTextContent('已完成');
  });

  it('done_no_data 显示"完成（无数据）"', () => {
    const { getByTestId } = render(<StatusBadge status="done_no_data" />);
    expect(getByTestId('tag')).toHaveTextContent('完成（无数据）');
  });

  it('pending 显示"待处理"', () => {
    const { getByTestId } = render(<StatusBadge status="pending" />);
    expect(getByTestId('tag')).toHaveTextContent('待处理');
  });

  it('未知状态回退显示默认色与原始值', () => {
    const { getByTestId } = render(<StatusBadge status="weird" />);
    expect(getByTestId('tag')).toHaveAttribute('data-color', 'default');
    expect(getByTestId('tag')).toHaveTextContent('weird');
  });
});