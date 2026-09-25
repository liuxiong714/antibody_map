import { describe, expect, it } from 'vitest';

import { provinceLabel } from '../constants';

describe('provinceLabel', () => {
  it('已知省份 → 简称·分区标签', () => {
    expect(provinceLabel('北京')).toBe('北京（京·中部）');
  });

  it('未知省份 → 原样返回', () => {
    expect(provinceLabel('不存在省')).toBe('不存在省');
  });
});
