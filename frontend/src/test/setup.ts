import '@testing-library/jest-dom';

// Node 22+ 提供了实验性全局 localStorage/sessionStorage，但默认未启用（undefined），
// 可能与 jsdom 的 window 存储冲突或遮蔽。为彻底消除环境差异，这里无条件用
// 一个内存实现覆盖全局存储，保证模块导入期（如 i18n）使用裸全局存储不抛错。
// 浏览器运行时不受影响（该文件仅在测试环境执行）。
function createMemoryStorage(): Storage {
  let store = new Map<string, string>();
  return {
    get length() {
      return store.size;
    },
    clear(): void {
      store = new Map();
    },
    getItem(key: string): string | null {
      return store.has(key) ? store.get(key)! : null;
    },
    key(index: number): string | null {
      return Array.from(store.keys())[index] ?? null;
    },
    removeItem(key: string): void {
      store.delete(key);
    },
    setItem(key: string, value: string): void {
      store.set(key, String(value));
    },
  };
}

function forceGlobalStorage(name: 'localStorage' | 'sessionStorage'): void {
  const impl = createMemoryStorage();
  try {
    Object.defineProperty(globalThis, name, { value: impl, configurable: true });
  } catch {
    // 兜底：若属性不可配置，直接赋值
    (globalThis as any)[name] = impl;
  }
}
forceGlobalStorage('localStorage');
forceGlobalStorage('sessionStorage');

// antd 依赖的全局匹配媒体查询，jsdom 默认未实现，补齐避免 warn/异常
if (!window.matchMedia) {
  window.matchMedia = (query) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
}