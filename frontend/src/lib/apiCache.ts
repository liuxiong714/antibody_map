// 轻量级 GET 请求缓存层
// 用途：对地图/分析等只读查询接口做前端缓存，避免在疾病/省份/年份等筛选切换时重复请求相同数据。
// 设计要点：
//   - 仅缓存通过 `cache: true` 显式开启的 GET 请求，其余请求不受影响，避免数据过期。
//   - 以「用户域 + URL + 排序后的 query 参数」作为缓存 key，避免不同账号串读。
//   - 支持 TTL（默认 60s）、LRU 淘汰（最多 MAX_ENTRIES 条）与手动失效（clearApiCache）。
//   - 缓存命中时并发去重（同一 key 的并发请求共享同一个 Promise），避免重复发请求。

interface CacheEntry {
  data: unknown;
  expiresAt: number;
}

const CACHE = new Map<string, CacheEntry>();
const MAX_ENTRIES = 200;

// 并发去重：同一 key 尚未完成的请求共享同一个 Promise
const IN_FLIGHT = new Map<string, Promise<unknown>>();

const DEFAULT_TTL = 60_000; // 默认 60 秒

/** 当前登录用户域。不同用户/会话使用不同命名空间，防止缓存串读。 */
function userScope(): string {
  const name = localStorage.getItem('username') || sessionStorage.getItem('username');
  if (name) return `u:${name}`;
  const token = localStorage.getItem('token') || sessionStorage.getItem('token');
  return token ? `t:${token.slice(-12)}` : 'anon';
}

/** 生成缓存 key：用户域 + URL + 排序后的 query 参数 */
function buildKey(url: string, params?: Record<string, unknown>): string {
  const scope = userScope();
  if (!params) return `${scope}|${url}`;
  const sorted = Object.keys(params)
    .filter((k) => params[k] !== undefined && params[k] !== null && params[k] !== '')
    .sort()
    .map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(String(params[k]))}`)
    .join('&');
  return sorted ? `${scope}|${url}?${sorted}` : `${scope}|${url}`;
}

/** 读取缓存（命中且未过期返回数据，否则返回 undefined；命中时刷新 LRU 顺序） */
export function getApiCache(url: string, params?: Record<string, unknown>): unknown | undefined {
  const key = buildKey(url, params);
  const entry = CACHE.get(key);
  if (!entry) return undefined;
  if (entry.expiresAt < Date.now()) {
    CACHE.delete(key);
    return undefined;
  }
  // LRU：读取后移动到末尾（最近使用）
  CACHE.delete(key);
  CACHE.set(key, entry);
  return entry.data;
}

/** 写入缓存；超出容量上限时淘汰最久未使用的一条 */
export function setApiCache(url: string, params: Record<string, unknown> | undefined, data: unknown, ttl = DEFAULT_TTL): void {
  const key = buildKey(url, params);
  CACHE.delete(key);
  CACHE.set(key, { data, expiresAt: Date.now() + ttl });
  if (CACHE.size > MAX_ENTRIES) {
    const oldest = CACHE.keys().next().value;
    if (oldest !== undefined) CACHE.delete(oldest);
  }
}

/**
 * 执行带缓存的 GET 请求。
 * - 命中缓存：直接返回缓存数据（含并发去重）。
 * - 未命中：发起真实请求并写入缓存。
 */
export async function cachedGet<T>(
  fetchFn: () => Promise<T>,
  url: string,
  params?: Record<string, unknown>,
  ttl = DEFAULT_TTL,
): Promise<T> {
  const key = buildKey(url, params);
  const cached = getApiCache(url, params);
  if (cached !== undefined) return cached as T;

  // 并发去重：同一 key 的并发请求共享同一个 Promise
  const inFlight = IN_FLIGHT.get(key);
  if (inFlight) return inFlight as Promise<T>;

  const promise = fetchFn()
    .then((data) => {
      setApiCache(url, params, data, ttl);
      return data;
    })
    .finally(() => {
      IN_FLIGHT.delete(key);
    });

  IN_FLIGHT.set(key, promise);
  return promise;
}

/** 清除全部或指定前缀的缓存（数据变更后调用） */
export function clearApiCache(prefix?: string): void {
  if (!prefix) {
    CACHE.clear();
    IN_FLIGHT.clear();
    return;
  }
  // key 形如「用户域|url?params」，按 URL 片段匹配前缀即可命中任意用户域
  for (const key of CACHE.keys()) {
    if (key.includes(prefix)) {
      CACHE.delete(key);
    }
  }
}

/**
 * 登出/切换用户时清空全部前端 GET 缓存。
 * 调用方应在退出登录或账号切换后调用，及时释放上一账号的缓存数据。
 */
export function clearAllApiCache(): void {
  CACHE.clear();
  IN_FLIGHT.clear();
}
