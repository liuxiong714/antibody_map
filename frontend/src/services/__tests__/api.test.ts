import { beforeEach, describe, expect, it } from 'vitest';
import api, { setStoredTokens, getStoredToken } from '../api';

/**
 * api.ts 拦截器单测 —— 通过 axios 公开的 handlers 属性直接调用拦截器函数，
 * 不发起真实网络请求，模拟浏览器存储即可完成对「token 注入」「ApiResponse 解包」
 * 「双存储切换」等自主逻辑的验证。
 */

function clearStores() {
  localStorage.removeItem('token');
  localStorage.removeItem('refresh_token');
  localStorage.removeItem('username');
  localStorage.removeItem('is_admin');
  sessionStorage.removeItem('token');
  sessionStorage.removeItem('refresh_token');
  sessionStorage.removeItem('username');
  sessionStorage.removeItem('is_admin');
}

// 读取已注册的请求/响应拦截器函数
function requestInterceptorFulfilled(): (config: any) => any {
  return api.interceptors.request.handlers![0].fulfilled!;
}
function responseInterceptorFulfilled(): (resp: any) => any {
  return api.interceptors.response.handlers![0].fulfilled!;
}

beforeEach(() => {
  clearStores();
});

describe('api 请求拦截器：token 注入', () => {
  const reqIf = requestInterceptorFulfilled();

  it('无 token 时不注入 Authorization 头', () => {
    const config = { headers: {} };
    const out = reqIf(config);
    expect(out.headers.Authorization).toBeUndefined();
  });

  it('localStorage 有 token 时注入 Bearer 头', () => {
    localStorage.setItem('token', 'loc-token-1');
    const config = { headers: {} };
    const out = reqIf(config);
    expect(out.headers.Authorization).toBe('Bearer loc-token-1');
  });

  it('localStorage 为空时回退到 sessionStorage', () => {
    sessionStorage.setItem('token', 'sess-token-1');
    const config = { headers: {} };
    const out = reqIf(config);
    expect(out.headers.Authorization).toBe('Bearer sess-token-1');
  });

  it('不修改除 headers 之外的请求配置', () => {
    localStorage.setItem('token', 't');
    const config = { headers: {}, url: '/map/province-data', method: 'get' };
    const out = reqIf(config);
    expect(out.url).toBe('/map/province-data');
    expect(out.method).toBe('get');
  });
});

describe('api 响应拦截器：ApiResponse 解包', () => {
  const respIf = responseInterceptorFulfilled();

  it('{success, data} 形态 → 将内层 data 提升到 resp.data', () => {
    const resp = { data: { success: true, message: 'ok', data: { foo: 1 } } };
    const out = respIf(resp);
    expect(out.data).toEqual({ foo: 1 });
  });

  it('{code, data} 形态 → 同样提升 data', () => {
    const resp = { data: { code: 0, data: [1, 2, 3] } };
    const out = respIf(resp);
    expect(out.data).toEqual([1, 2, 3]);
  });

  it('非 ApiResponse（无 data/success/code 键）→ 保持原样', () => {
    const resp = { data: 42 };
    const out = respIf(resp);
    expect(out.data).toBe(42);
  });

  it('数组响应 → 保持原样，不误判为 ApiResponse', () => {
    const resp = { data: [1, 2] };
    const out = respIf(resp);
    expect(out.data).toEqual([1, 2]);
  });

  it('data 为 null 但带 code → 提升 null 而非整个 body', () => {
    const resp = { data: { code: 200, data: null } };
    const out = respIf(resp);
    expect(out.data).toBeNull();
  });
});

describe('api 存储切换逻辑', () => {
  it('setStoredTokens 写入 localStorage 并清空另一存储', () => {
    sessionStorage.setItem('token', 'stale');
    setStoredTokens('loc-tok', 'loc-ref', true);
    expect(localStorage.getItem('token')).toBe('loc-tok');
    expect(localStorage.getItem('refresh_token')).toBe('loc-ref');
    expect(sessionStorage.getItem('token')).toBeNull();
    expect(sessionStorage.getItem('refresh_token')).toBeNull();
    expect(getStoredToken()).toBe('loc-tok');
  });

  it('默认按已有 token 所在存储选择活跃存储', () => {
    // 两个存储都为空 → 回退 sessionStorage
    expect(getStoredToken()).toBeNull();
    // 往 localStorage 放 token → getStoredToken 优先读 localStorage
    localStorage.setItem('token', 'loc-active');
    expect(getStoredToken()).toBe('loc-active');
  });

  it('getStoredToken 优先 localStorage', () => {
    localStorage.setItem('token', 'a');
    sessionStorage.setItem('token', 'b');
    expect(getStoredToken()).toBe('a');
  });
});