import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import DiseaseSelector from '../DiseaseSelector';

// Mock antd Select，以便稳定地控制其交互行为（避免依赖真实下拉渲染）
vi.mock('antd', async (importOriginal) => {
  const actual = await importOriginal<typeof import('antd')>();
  const MockSelect = ({
    value,
    onChange,
    options,
    allowClear,
    placeholder,
  }: {
    value?: string;
    onChange?: (v: unknown) => void;
    options?: { value: string; label: string }[];
    allowClear?: boolean;
    placeholder?: string;
  }) => (
    <div data-testid="mock-select">
      <span data-testid="select-value">{String(value ?? '')}</span>
      <span data-testid="select-placeholder">{String(placeholder ?? '')}</span>
      <button
        type="button"
        data-testid="select-options-count"
        onClick={() => onChange?.(options?.[0]?.value)}
      >
        {String(options?.length ?? 0)}
      </button>
      <button
        type="button"
        data-testid="select-clear"
        disabled={!allowClear}
        onClick={() => onChange?.(undefined)}
      >
        清除
      </button>
    </div>
  );
  return { ...actual, Select: MockSelect };
});

describe('DiseaseSelector', () => {
  it('渲染 Select 并传入失效值作为 value', () => {
    const { container } = render(<DiseaseSelector value="measles" onChange={vi.fn()} />);
    expect(container.querySelector('[data-testid="select-value"]')).toHaveTextContent('measles');
  });

  it('选择选项时透传其值给 onChange（字符串直接传递）', () => {
    const onChange = vi.fn();
    render(<DiseaseSelector value="covid19" onChange={onChange} />);
    fireEvent.click(screen.getByTestId('select-options-count'));
    expect(onChange).toHaveBeenCalledWith('measles');
  });

  it('清除时回调传值为空字符串', () => {
    const onChange = vi.fn();
    render(<DiseaseSelector value="measles" onChange={onChange} />);
    fireEvent.click(screen.getByTestId('select-clear'));
    expect(onChange).toHaveBeenCalledWith('');
  });

  it('提供来源于 DISEASES 的选项（含数量与首项 label）', () => {
    render(<DiseaseSelector value="" onChange={vi.fn()} />);
    // DISEASES 共 15 项
    expect(screen.getByTestId('select-options-count')).toHaveTextContent('15');
  });

  it('未传 value 时展示占位文案"选择疾病"', () => {
    render(<DiseaseSelector value="" onChange={vi.fn()} />);
    expect(screen.getByTestId('select-placeholder')).toHaveTextContent('选择疾病');
  });

  it('allowClear 默认为 true', () => {
    render(<DiseaseSelector value="" onChange={vi.fn()} />);
    expect(screen.getByTestId('select-clear')).not.toBeDisabled();
  });
});