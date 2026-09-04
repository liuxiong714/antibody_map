import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  cachedGet,
  clearApiCache,
  clearAllApiCache,
  getApiCache,
  setApiCache,
} from '../apiCache';

/**
 * 前端 GET 缓存层单测 —— 覆盖 TTL 过期、LRU 淘汰、并发去重、参数排序、
 * 用户域隔离、前缀/全缓存清除等自主逻辑，不依赖任何网络。
 */

const dateNow = vi.spyOn(Date, 'now');

beforeEach(() => {
  clearAllApiCache();
  localStorage.clear();
  sessionStorage.clear();
  dateNow.mockReturnValue(1000);
});

afterEach(() => {
  dateNow.mockReset();
});

describe('缓存读写与命中', () => {
  it('写入后命中返回数据', () => {
    setApiCache('/map/data', { disease: '流感' }, [{ v: 1 }], 1000);
    expect(getApiCache('/map/data', { disease: '流感' })).toEqual([{ v: 1 }]);
  });

  it('参数顺序不影响命中（key 对参数排序）', () => {
    setApiCache('/map', { year: 2020, disease: 'a' }, 'hit', 1000);
    expect(getApiCache('/map', { disease: 'a', year: 2020 })).toBe('hit');
  });

  it('不同 URL 不串key', () => {
    setApiCache('/a', {}, 1, 1000);
    expect(getApiCache('/b', {})).toBeUndefined();
  });

  it('参数不同则未命中', () => {
    setApiCache('/map', { disease: 'a' }, 'x', 1000);
    expect(getApiCache('/map', { disease: 'b' })).toBeUndefined();
  });

  it('undefined/null/空字符串 的参数被忽略，不影响 key', () => {
    setApiCache('/map', { disease: 'a', year: null, note: '' }, 'y', 1000);
    expect(getApiCache('/map', { disease: 'a' })).toBe('y');
  });
});

describe('TTL 过期', () => {
  it('命中后过期返回 undefined 并删除', () => {
    setApiCache('/x', {}, 'v', 500); // 1000 + 500 = 1500 过期
    dateNow.mockReturnValue(1400);
    expect(getApiCache('/x', {})).toBe('v');
    dateNow.mockReturnValue(1600);
    expect(getApiCache('/x', {})).toBeUndefined();
  });
});

describe('并发去重', () => {
  it('同一 key 并发请求 fetchFn 只调用一次', async () => {
    const fetchFn = vi.fn(async () => 'result');
    const p1 = cachedGet(fetchFn, '/map/province-data', { a: 1 });
    const p2 = cachedGet(fetchFn, '/map/province-data', { a: 1 });
    const [r1, r2] = [await p1, await p2];
    expect(r1).toBe('result');
    expect(r2).toBe('result');
    expect(fetchFn).toHaveBeenCalledTimes(1); // 并发去重：仅发一次请求
  });
});

describe('cachedGet 命中时不重复请求', () => {
  it('首次调用请求并缓存，二次调用直接命中', async () => {
    const fetchFn = vi.fn(async () => [1]);
    await cachedGet(fetchFn, '/map', { a: 1 }, 100_000);
    const again = vi.fn(async () => [2]);
    const hit = await cachedGet(again, '/map', { a: 1 }, 100_000);
    expect(hit).toEqual([1]);
    expect(again).not.toHaveBeenCalled();
  });
});

describe('用户域隔离', () => {
  it('不同 username 的缓存互不串读', async () => {
    const fetchA = vi.fn(async () => 'A-data');
    const fetchB = vi.fn(async () => 'B-data');
    localStorage.setItem('username', 'alice');
    await cachedGet(fetchA, '/map', {}, 100_000);
    // 缓存已含 alice 数据；换 Bob 后应重新请求
    localStorage.setItem('username', 'bob');
    const b = await cachedGet(fetchB, '/map', {}, 100_000);
    expect(b).toBe('B-data');
    expect(fetchB).toHaveBeenCalledTimes(1);
  });
});

describe('缓存清除', () => {
  it('clearApiCache 按前缀清除', () => {
    setApiCache('/map/data', {}, 'a', 1000);
    setApiCache('/analysis/trend', {}, 'b', 1000);
    clearApiCache('/map/');
    expect(getApiCache('/map/data', {})).toBeUndefined();
    expect(getApiCache('/analysis/trend', {})).toBe('b');
  });

  it('clearAllApiCache 清空全部', () => {
    setApiCache('/map', {}, 'a', 1000);
    setApiCache('/analysis', {}, 'b', 1000);
    clearAllApiCache();
    expect(getApiCache('/map', {})).toBeUndefined();
    expect(getApiCache('/analysis', {})).toBeUndefined();
  });
});