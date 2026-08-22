import '@testing-library/jest-dom';

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