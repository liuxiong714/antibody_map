import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/react';

import ConfidenceBadge from '../ConfidenceBadge';

vi.mock('antd', async (importOriginal) => {
  const actual = await importOriginal<typeof import('antd')>();
  const Tag = ({ color, children }: { color?: string; children?: React.ReactNode }) => (
    <div data-testid="tag" data-color={color ?? 'default'}>
      {children}
    </div>
  );
  return { ...actual, Tag };
});

describe('ConfidenceBadge', () => {
  it('high 显示绿色"高"', () => {
    const { getByTestId } = render(<ConfidenceBadge confidence="high" />);
    expect(getByTestId('tag')).toHaveAttribute('data-color', 'green');
    expect(getByTestId('tag')).toHaveTextContent('高');
  });

  it('medium 显示金色"中"', () => {
    const { getByTestId } = render(<ConfidenceBadge confidence="medium" />);
    expect(getByTestId('tag')).toHaveAttribute('data-color', 'gold');
    expect(getByTestId('tag')).toHaveTextContent('中');
  });

  it('low 显示红色"低"', () => {
    const { getByTestId } = render(<ConfidenceBadge confidence="low" />);
    expect(getByTestId('tag')).toHaveAttribute('data-color', 'red');
    expect(getByTestId('tag')).toHaveTextContent('低');
  });

  it('未知等级回退显示默认色与原始值', () => {
    const { getByTestId } = render(<ConfidenceBadge confidence="unknown" />);
    expect(getByTestId('tag')).toHaveAttribute('data-color', 'default');
    expect(getByTestId('tag')).toHaveTextContent('unknown');
  });
});