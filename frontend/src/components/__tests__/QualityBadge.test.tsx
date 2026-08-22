import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/react';

import QualityBadge from '../QualityBadge';

vi.mock('antd', async (importOriginal) => {
  const actual = await importOriginal<typeof import('antd')>();
  const Badge = ({ color, text }: { color?: string; text?: React.ReactNode }) => (
    <div data-testid="badge" data-color={color}>
      {text}
    </div>
  );
  const Tooltip = ({ title, children }: { title?: React.ReactNode; children?: React.ReactNode }) => (
    <div data-testid="tooltip" data-title={String(title ?? '')}>
      {children}
    </div>
  );
  const Typography = {
    Text: ({ style, children }: { style?: React.CSSProperties; children?: React.ReactNode }) => (
      <span>{children}</span>
    ),
  };
  return { ...actual, Badge, Tooltip, Typography };
});

describe('QualityBadge', () => {
  it('无 qualityGrade 或 qualityScore 时显示未评分占位" - "', () => {
    const { getByTestId } = render(<QualityBadge />);
    expect(getByTestId('badge')).toHaveTextContent('-');
    expect(getByTestId('tooltip')).toHaveAttribute(
      'data-title',
      '审核通过后自动打分（未评分）',
    );
  });

  it('qualityScore 为 null 时同样显示未评分占位', () => {
    const { getByTestId } = render(<QualityBadge qualityGrade="A" qualityScore={null} />);
    expect(getByTestId('badge')).toHaveTextContent('-');
  });

  it('A 等级显示绿色 Badge，文本包含分数与等级', () => {
    const { getByTestId } = render(<QualityBadge qualityGrade="A" qualityScore={95} />);
    expect(getByTestId('badge')).toHaveAttribute('data-color', 'green');
    expect(getByTestId('badge')).toHaveTextContent('95 · A');
    expect(getByTestId('tooltip').getAttribute('data-title')).toContain('质量评分：95 分');
    expect(getByTestId('tooltip').getAttribute('data-title')).toContain('等级：A 高质量');
  });

  it('供 B 等级显示对应颜色', () => {
    const { getByTestId } = render(<QualityBadge qualityGrade="B" qualityScore={70} />);
    expect(getByTestId('badge')).toHaveAttribute('data-color', 'gold');
  });

  it('支持 estimateGrade 显示在 Tooltip 中', () => {
    const { getByTestId } = render(
      <QualityBadge qualityGrade="C" qualityScore={60} estimateGrade="national" />,
    );
    expect(getByTestId('tooltip').getAttribute('data-title')).toContain('调查级别：全国');
  });

  it('breakdown 明细逐项展示在 Tooltip 中', () => {
    const { getByTestId } = render(
      <QualityBadge
        qualityGrade="A"
        qualityScore={90}
        breakdown={{
          sample_size: { score: 10, label: '样本量充足', max: 15 },
        }}
      />,
    );
    const title = getByTestId('tooltip').getAttribute('data-title') ?? '';
    expect(title).toContain('六项得分明细');
    expect(title).toContain('样本量：10/15（样本量充足）');
  });
});