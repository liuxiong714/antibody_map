import { describe, it, expect } from 'vitest';
import {
  formatRate,
  formatNumber,
  truncate,
  formatAuthors,
} from '../format';

describe('formatRate', () => {
  it('格式化常见数值为两位小数加百分号', () => {
    expect(formatRate(72.5)).toBe('72.50%');
  });

  it('处理 null / undefined 空格返回 "-"', () => {
    expect(formatRate(null)).toBe('-');
    expect(formatRate(undefined)).toBe('-');
  });

  it('对小数做四舍五入处理', () => {
    expect(formatRate(33.333)).toBe('33.33%');
  });
});

describe('formatNumber', () => {
  it('将整数按千分位格式化', () => {
    expect(formatNumber(1234567)).toBe('1,234,567');
  });

  it('null / undefined 返回 "-"', () => {
    expect(formatNumber(null)).toBe('-');
    expect(formatNumber(undefined)).toBe('-');
  });

  it('支持小数保留', () => {
    expect(formatNumber(1234.5)).toBe('1,234.5');
  });
});

describe('truncate', () => {
  it('长度未超限时返回原始字符串', () => {
    expect(truncate('abc', 5)).toBe('abc');
  });

  it('长度超过 max 时截断并追加省略号', () => {
    expect(truncate('hello world', 5)).toBe('hello...');
  });

  it('空字符串返回 "-"', () => {
    expect(truncate('', 5)).toBe('-');
  });
});

describe('formatAuthors', () => {
  it('超过三位作者时取前三位并追加"等"', () => {
    expect(formatAuthors('A;B;C;D;E')).toBe('A, B, C 等');
  });

  it('兼容中文分号分隔', () => {
    expect(formatAuthors('张三；李四；王五')).toBe('张三, 李四, 王五');
  });

  it('不足三位作者时全部保留', () => {
    expect(formatAuthors('A;B')).toBe('A, B');
    expect(formatAuthors('A;B;C')).toBe('A, B, C');
  });

  it('空值返回 "-"', () => {
    expect(formatAuthors(null)).toBe('-');
    expect(formatAuthors(undefined)).toBe('-');
    expect(formatAuthors('')).toBe('-');
  });
});