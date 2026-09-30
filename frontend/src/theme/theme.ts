/**
 * ============================================================
 * 科研学术主题（Academic Blue）
 * 参考 LoginPage.css 配色风格：深海军蓝 + 科技蓝 + 金色高亮
 * 用于 Ant Design 5 ConfigProvider 主题定制
 *
 * 色值与 theme.css 中的 CSS 变量（--ab-*）保持一致，两处需同步修改。
 * ============================================================
 */
import type { ThemeConfig } from "antd";

/* ============ 品牌色值令牌 ============ */
export const academicColors = {
  /* 品牌主色（深海军蓝） */
  primary: "#0a2e6c",
  primaryLight: "#123a7a",
  primaryDeep: "#071f4d",
  primaryHover: "#123a7a",
  primaryActive: "#071f4d",

  /* 辅助青色（登录按钮/logo 渐变第二色） */
  accent: "#0e7490",
  accentDeep: "#155e75",

  /* 科技蓝（数据高亮/地图点缀） */
  techBlue: "#66ccff",
  techBlueSoft: "#8fd4ff",
  infoBlue: "#2b7fd4",

  /* 金色高亮（热点/警示/强调） */
  gold: "#f59e0b",
  goldLight: "#fcd34d",
  goldDeep: "#d97706",

  /* 语义色 */
  success: "#059669",
  warning: "#f59e0b",
  error: "#dc2626",
  info: "#2b7fd4",

  /* 中性色（文字层级） */
  textBase: "#1f2937",
  textSecondary: "#4b5563",
  textTertiary: "#8492a6",
  textPlaceholder: "#9ca3af",

  /* 背景 / 边框 */
  bgLayout: "#f4f7fb",
  bgContainer: "#ffffff",
  bgInput: "#f5f7fa",
  border: "#d1d5db",
  borderSecondary: "#e5e7eb",
  tableHeaderBg: "#f0f5ff",
} as const;

/* ============ 精致版主题色值（Enhanced Academic Navy） ============
   在默认主题基础上做精细化美化：渐变按钮、发光效果、圆角优化、阴影层次
   ============================================================ */
export const enhancedColors = {
  /* 品牌主色（深海军蓝，与默认一致） */
  primary: "#0a2e6c",
  primaryLight: "#1a4a8f",
  primaryDeep: "#071f4d",
  primaryHover: "#123a7a",
  primaryActive: "#061a3d",

  /* 辅助青色（更亮，发光效果更好） */
  accent: "#0e7490",
  accentLight: "#16a3b8",
  accentDeep: "#155e75",

  /* 科技蓝（发光用） */
  techBlue: "#66ccff",
  techBlueSoft: "#93d5ff",
  infoBlue: "#3b82f6",

  /* 金色高亮 */
  gold: "#f59e0b",
  goldLight: "#fcd34d",
  goldDeep: "#d97706",

  /* 语义色（更饱和，视觉更精致） */
  success: "#10b981",
  successDeep: "#059669",
  warning: "#f59e0b",
  warningDeep: "#d97706",
  error: "#ef4444",
  errorDeep: "#dc2626",
  info: "#3b82f6",
  infoDeep: "#2563eb",

  /* 中性色（优化文字层级对比） */
  textBase: "#0f172a",
  textSecondary: "#475569",
  textTertiary: "#94a3b8",
  textPlaceholder: "#cbd5e1",

  /* 背景 / 边框（更干净的灰白体系） */
  bgLayout: "#f1f5f9",
  bgContainer: "#ffffff",
  bgInput: "#f8fafc",
  bgHover: "#f0f7ff",
  border: "#e2e8f0",
  borderLight: "#f1f5f9",
  tableHeaderBg: "#f0f7ff",
} as const;

/* ============ 学术图表色板（数据可视化） ============ */
export const academicChartPalette = {
  /** 分类色板（8 色：蓝 → 青 → 金 → 红 → 绿 → 紫 → 亮蓝 → 灰） */
  categorical: [
    "#0a2e6c",
    "#0e7490",
    "#f59e0b",
    "#dc2626",
    "#059669",
    "#7c3aed",
    "#2b7fd4",
    "#64748b",
  ],
  /** 热力地图顺序色带（Blues，浅 → 深） */
  sequentialBlues: [
    "#d6f0ff",
    "#a6d8f7",
    "#66ccff",
    "#2b7fd4",
    "#123a7a",
    "#071f4d",
  ],
  /** 分叉色带（热点/冷点，蓝 → 中性 → 红） */
  diverging: ["#2b7fd4", "#a6d8f7", "#f4f7fb", "#fcd34d", "#dc2626"],
  /** 地图热点高亮 */
  hotspot: "#ffa500",
} as const;

/* ============ Ant Design 主题配置 ============ */
export const academicTheme: ThemeConfig = {
  token: {
    colorPrimary: academicColors.primary,
    colorInfo: academicColors.infoBlue,
    colorLink: academicColors.accent,
    colorSuccess: academicColors.success,
    colorWarning: academicColors.warning,
    colorError: academicColors.error,
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
    fontFamily:
      '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif',
    controlHeight: 36,
  },
  components: {
    /* 侧边栏 + 顶栏：深海军蓝替代 AntD 默认 #001529 */
    Layout: {
      siderBg: academicColors.primaryDeep,
      headerBg: academicColors.bgContainer,
      headerHeight: 64,
      headerPadding: "0 24px",
      bodyBg: academicColors.bgLayout,
    },
    /* 深色菜单：深海军蓝底 + 科技蓝选中 */
    Menu: {
      darkItemBg: academicColors.primaryDeep,
      darkSubMenuItemBg: academicColors.primaryDeep,
      darkItemColor: "rgba(255, 255, 255, 0.72)",
      darkItemSelectedBg: academicColors.primary,
      darkItemSelectedColor: academicColors.techBlue,
      darkItemHoverBg: "rgba(102, 204, 255, 0.12)",
      itemBorderRadius: 8,
    },
    Button: {
      primaryShadow: "0 4px 12px rgba(10, 46, 108, 0.3)",
      fontWeight: 500,
      defaultShadow: "none",
    },
    Card: {
      borderRadiusLG: 12,
      boxShadowTertiary: "0 2px 8px rgba(10, 46, 108, 0.06)",
    },
    Table: {
      headerBg: academicColors.tableHeaderBg,
      headerColor: academicColors.primary,
      headerSplitColor: "transparent",
      rowHoverBg: "#f0f7ff",
    },
    Input: {
      activeShadow: "0 0 0 3px rgba(10, 46, 108, 0.1)",
    },
    Select: {
      optionSelectedBg: "#eef4fb",
    },
  },
};

/* ============ 精致版 Ant Design 主题配置（Enhanced Academic Navy） ============ */
export const enhancedTheme: ThemeConfig = {
  token: {
    colorPrimary: enhancedColors.primary,
    colorInfo: enhancedColors.infoBlue,
    colorLink: enhancedColors.accent,
    colorSuccess: enhancedColors.success,
    colorWarning: enhancedColors.warning,
    colorError: enhancedColors.error,
    colorTextBase: enhancedColors.textBase,
    colorTextSecondary: enhancedColors.textSecondary,
    colorTextTertiary: enhancedColors.textTertiary,
    colorTextPlaceholder: enhancedColors.textPlaceholder,
    colorBgLayout: enhancedColors.bgLayout,
    colorBgContainer: enhancedColors.bgContainer,
    colorBorder: enhancedColors.border,
    colorBorderSecondary: enhancedColors.borderLight,
    borderRadius: 10,
    borderRadiusLG: 14,
    borderRadiusSM: 8,
    fontSize: 14,
    fontFamily:
      '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif',
    controlHeight: 38,
    /* 精致版：运动曲线更柔和 */
    motionDurationMid: "0.25s",
    motionEaseInOut: "cubic-bezier(0.4, 0, 0.2, 1)",
  },
  components: {
    Layout: {
      siderBg: enhancedColors.primaryDeep,
      headerBg: enhancedColors.bgContainer,
      headerHeight: 64,
      headerPadding: "0 24px",
      bodyBg: enhancedColors.bgLayout,
    },
    Menu: {
      darkItemBg: "transparent",
      darkSubMenuItemBg: "transparent",
      darkItemColor: "rgba(255, 255, 255, 0.7)",
      darkItemSelectedBg: "rgba(102, 204, 255, 0.15)",
      darkItemSelectedColor: "#ffffff",
      darkItemHoverBg: "rgba(102, 204, 255, 0.08)",
      itemBorderRadius: 10,
      /* 精致版：菜单项间距优化 */
      itemMarginInline: 10,
      itemMarginBlock: 2,
    },
    Button: {
      /* 精致版：主按钮发光阴影 */
      primaryShadow: "0 4px 16px rgba(10, 46, 108, 0.25)",
      fontWeight: 500,
      defaultShadow: "none",
      borderRadius: 10,
      /* 精致版：按钮高度优化 */
      controlHeight: 38,
    },
    Card: {
      borderRadiusLG: 14,
      boxShadowTertiary: "0 2px 10px rgba(10, 46, 108, 0.06)",
      boxShadowSecondary: "0 4px 16px rgba(10, 46, 108, 0.08)",
    },
    Table: {
      headerBg: enhancedColors.tableHeaderBg,
      headerColor: enhancedColors.primary,
      headerSplitColor: "transparent",
      rowHoverBg: "#f0f7ff",
      headerBorderRadius: 12,
      cellPaddingBlock: 12,
      cellPaddingInline: 14,
    },
    Input: {
      activeShadow: "0 0 0 3px rgba(102, 204, 255, 0.15)",
      hoverBorderColor: enhancedColors.accent,
      activeBorderColor: enhancedColors.primary,
      borderRadius: 10,
    },
    InputNumber: {
      borderRadius: 10,
    },
    Select: {
      optionSelectedBg: "#eef4ff",
      borderRadius: 10,
    },
    DatePicker: {
      borderRadius: 10,
    },
    Tag: {
      borderRadiusSM: 6,
      borderRadius: 8,
    },
    Badge: {
      dotSize: 8,
    },
    Tabs: {
      itemColor: enhancedColors.textSecondary,
      itemSelectedColor: enhancedColors.primary,
      itemHoverColor: enhancedColors.accent,
      inkBarColor: enhancedColors.primary,
      horizontalItemPadding: "12px 14px",
    },
    Modal: {
      borderRadiusLG: 14,
    },
    Drawer: {
      borderRadiusLG: 14,
    },
    Tooltip: {
      borderRadius: 8,
    },
    Popover: {
      borderRadiusLG: 12,
    },
    Progress: {
      colorInfo: enhancedColors.primary,
      colorSuccess: enhancedColors.success,
      colorWarning: enhancedColors.warning,
      colorError: enhancedColors.error,
    },
  },
};
