// 轻量级 GET 请求缓存层
// 用途：对地图/分析等只读查询接口做前端缓存，避免在疾病/省份/年份等筛选切换时重复请求相同数据。
// 设计要点：
//   - 仅缓存通过 `cache: true` 显式开启的 GET 请求，其余请求不受影响，避免数据过期。
//   - 以「URL + 排序后的 query 参数」作为缓存 key。
//   - 支持 TTL（默认 60s）与手动失效（clearApiCache）。
//   - 缓存命中时并发去重（同一 key 的并发请求共享同一个 Promise），避免重复发请求。

interface CacheEntry {
  data: unknown;
  expiresAt: number;
}

const CACHE = new Map<string, CacheEntry>();

// 并发去重：同一 key 尚未完成的请求共享同一个 Promise
const IN_FLIGHT = new Map<string, Promise<unknown>>();

const DEFAULT_TTL = 60_000; // 默认 60 秒

/** 生成缓存 key：URL + 排序后的 query 参数 */
function buildKey(url: string, params?: Record<string, unknown>): string {
  if (!params) return url;
  const sorted = Object.keys(params)
    .filter((k) => params[k] !== undefined && params[k] !== null && params[k] !== '')
    .sort()
    .map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(String(params[k]))}`)
    .join('&');
  return sorted ? `${url}?${sorted}` : url;
}

/** 读取缓存（命中且未过期返回数据，否则返回 undefined） */
export function getApiCache(url: string, params?: Record<string, unknown>): unknown | undefined {
  const key = buildKey(url, params);
  const entry = CACHE.get(key);
  if (!entry) return undefined;
  if (entry.expiresAt < Date.now()) {
    CACHE.delete(key);
    return undefined;
  }
  return entry.data;
}

/** 写入缓存 */
export function setApiCache(url: string, params: Record<string, unknown> | undefined, data: unknown, ttl = DEFAULT_TTL): void {
  const key = buildKey(url, params);
  CACHE.set(key, { data, expiresAt: Date.now() + ttl });
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
    return;
  }
  for (const key of CACHE.keys()) {
    if (key.startsWith(prefix)) {
      CACHE.delete(key);
    }
  }
}
