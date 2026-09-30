/**
 * ============================================================
 * 主题模块入口 — 提供主题切换的 Provider / Hook 及相关常量
 *
 *   - ThemeProvider      包裹应用，注入主题上下文并渲染 ConfigProvider
 *   - useTheme()         读取当前主题与切换函数
 *   - THEME_OPTIONS      主题切换器下拉选项
 *   - CANDIDATE_ACCENTS  候选主题下各分析模块专属强调色（Analysis 卡片使用）
 *
 * 主题色来源：
 *   - default（默认主题）→ ./theme.ts 的 academicTheme / academicColors
 *   - candidate（候选主题）→ 登录页配色家族（参阅 LoginPage.css）
 *   - enhanced（精致版主题）→ 学术深蓝精细化美化（渐变按钮/发光/圆角优化）
 * ============================================================
 */
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { ConfigProvider } from "antd";
import { academicTheme, academicColors, enhancedTheme } from "./theme";
import type { ThemeConfig } from "antd";

/* ============ 主题类型 / 选项 ============ */
export type ThemeName = "default" | "candidate" | "enhanced";

export const THEME_OPTIONS: Array<{ value: ThemeName; label: string }> = [
  { value: "default", label: "经典主题" },
  { value: "enhanced", label: "精致学术（推荐）" },
  { value: "candidate", label: "紫罗兰主题" },
];

/* ============ 候选主题：分析模块专属强调色 ============ */
export interface Accent {
  color: string;
  bg: string;
}

export const CANDIDATE_ACCENTS: Record<string, Accent> = {
  summary: { color: "#2563eb", bg: "#eff6ff" },
  datapoints: { color: "#0ea5e9", bg: "#f0f9ff" },
  coverage: { color: "#14b8a6", bg: "#f0fdfa" },
  review: { color: "#10b981", bg: "#ecfdf5" },
  ageCurve: { color: "#f59e0b", bg: "#fffbeb" },
  foi: { color: "#ef4444", bg: "#fef2f2" },
  vaccine: { color: "#8b5cf6", bg: "#f5f3ff" },
  advanced: { color: "#06b6d4", bg: "#ecfeff" },
  equity: { color: "#d946ef", bg: "#fdf4ff" },
  quality: { color: "#f97316", bg: "#fff7ed" },
  goal: { color: "#16a34a", bg: "#f0fdf4" },
  advancedAnalysis: { color: "#6366f1", bg: "#eef2ff" },
  metaAnalysis: { color: "#9333ea", bg: "#faf5ff" },
  birthCohort: { color: "#e11d48", bg: "#fff1f2" },
  _default: { color: "#2563eb", bg: "#eff6ff" },
};

/* ============ 候选主题 Ant Design 配置（登录页配色家族） ============ */
const candidateTheme: ThemeConfig = {
  token: {
    colorPrimary: "#4f46e5",
    colorInfo: "#2563eb",
    colorLink: "#4f46e5",
    colorSuccess: "#059669",
    colorWarning: "#f59e0b",
    colorError: "#dc2626",
    colorTextBase: academicColors.textBase,
    colorTextSecondary: academicColors.textSecondary,
    colorTextTertiary: academicColors.textTertiary,
    colorTextPlaceholder: academicColors.textPlaceholder,
    colorBgLayout: academicColors.bgLayout,
    colorBgContainer: academicColors.bgContainer,
    colorBorder: academicColors.border,
    colorBorderSecondary: academicColors.borderSecondary,
    borderRadius: 8,
    borderRadiusLG: 12,
    borderRadiusSM: 6,
    fontSize: 14,
    fontFamily: academicTheme.token?.fontFamily,
    controlHeight: 36,
  },
  components: {
    Layout: {
      siderBg: "#1e1b4b",
      headerBg: academicColors.bgContainer,
      headerHeight: 64,
      headerPadding: "0 24px",
      bodyBg: academicColors.bgLayout,
    },
    Menu: {
      darkItemBg: "#1e1b4b",
      darkSubMenuItemBg: "#1e1b4b",
      darkItemColor: "rgba(255, 255, 255, 0.72)",
      darkItemSelectedBg: "#4f46e5",
      darkItemSelectedColor: "#ffffff",
      darkItemHoverBg: "rgba(99, 102, 241, 0.18)",
      itemBorderRadius: 8,
    },
    Button: {
      primaryShadow: "0 4px 12px rgba(79, 70, 229, 0.3)",
      fontWeight: 500,
      defaultShadow: "none",
    },
    Card: {
      borderRadiusLG: 12,
      boxShadowTertiary: "0 2px 8px rgba(79, 70, 229, 0.08)",
    },
    Table: {
      headerBg: "#eef2ff",
      headerColor: "#3730a3",
      headerSplitColor: "transparent",
      rowHoverBg: "#eef2ff",
    },
    Input: {
      activeShadow: "0 0 0 3px rgba(79, 70, 229, 0.12)",
    },
    Select: {
      optionSelectedBg: "#eef2ff",
    },
  },
};

const ACTIVE_THEMES: Record<ThemeName, ThemeConfig> = {
  default: academicTheme,
  candidate: candidateTheme,
  enhanced: enhancedTheme,
};

/** 候选主题切换时需要同步覆盖的 CSS 变量（与 theme.css 的 --ab-* 对齐） */
const CANDIDATE_CSS_VARS: Record<string, string> = {
  "--ab-primary": "#4f46e5",
  "--ab-primary-light": "#6366f1",
  "--ab-primary-deep": "#1e1b4b",
  "--ab-primary-hover": "#6366f1",
  "--ab-primary-active": "#1e1b4b",
  "--ab-accent": "#4f46e5",
  "--ab-info-blue": "#2563eb",
  "--ab-bg-table-header": "#eef2ff",
  "--ab-bg-hover": "#eef2ff",
  "--ab-shadow-primary": "0 4px 12px rgba(79, 70, 229, 0.3)",
  "--ab-gradient-brand": "linear-gradient(135deg, #1e1b4b 0%, #4f46e5 100%)",
};

/* ============ 主题上下文 ============ */
interface ThemeContextValue {
  theme: ThemeName;
  setTheme: (t: ThemeName) => void;
}

const THEME_STORAGE_KEY = "antibody-theme";

const ThemeContext = createContext<ThemeContextValue>({
  theme: "default",
  setTheme: () => {},
});

export const useTheme = (): ThemeContextValue => useContext(ThemeContext);

/* ============ ThemeProvider ============ */
export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [theme, setThemeState] = useState<ThemeName>(() => {
    const saved = localStorage.getItem(THEME_STORAGE_KEY);
    if (saved === "candidate" || saved === "enhanced") {
      return saved;
    }
    return "default";
  });

  // 应用主题到 DOM：
  // 1. candidate 主题通过设置 CSS 变量实现
  // 2. enhanced 主题通过 html[data-app-theme="enhanced"] 属性驱动 CSS 选择器
  useEffect(() => {
    const root = document.documentElement;

    // 处理 enhanced 主题的 data-app-theme 属性（避免与 antd 内部 data-theme 冲突）
    if (theme === "enhanced") {
      root.setAttribute("data-app-theme", "enhanced");
    } else {
      root.removeAttribute("data-app-theme");
    }

    // 处理 candidate 主题的 CSS 变量
    if (theme === "candidate") {
      Object.entries(CANDIDATE_CSS_VARS).forEach(([key, value]) => {
        root.style.setProperty(key, value);
      });
    } else {
      Object.keys(CANDIDATE_CSS_VARS).forEach((key) => {
        root.style.removeProperty(key);
      });
    }
  }, [theme]);

  const setTheme = useCallback((t: ThemeName) => {
    setThemeState(t);
    localStorage.setItem(THEME_STORAGE_KEY, t);
  }, []);

  const value = useMemo(() => ({ theme, setTheme }), [theme, setTheme]);

  return (
    <ThemeContext.Provider value={value}>
      <ConfigProvider theme={ACTIVE_THEMES[theme]}>{children}</ConfigProvider>
    </ThemeContext.Provider>
  );
};

export default ThemeProvider;