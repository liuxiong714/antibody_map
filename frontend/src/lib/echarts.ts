/**
 * ECharts 按需加载模块
 *
 * 仅注册项目实际用到的图表类型与组件，显著减小打包体积
 * （全量引入约 1MB，按需注册后大幅缩减）。
 *
 * 引用方式：
 *   import * as echarts from '@/lib/echarts';
 *   <ReactEChartsCore echarts={echarts} ... />
 */
import * as echarts from 'echarts/core';

// 图表系列（series）
import { LineChart, BarChart, ScatterChart, MapChart, BoxplotChart, HeatmapChart, RadarChart } from 'echarts/charts';

// 组件
import {
  TitleComponent,
  TooltipComponent,
  GridComponent,
  LegendComponent,
  DataZoomComponent,
  VisualMapComponent,
  MarkLineComponent,
  MarkAreaComponent,
  ToolboxComponent,
  GeoComponent,
  RadarComponent,
  PolarComponent,
  DatasetComponent,
} from 'echarts/components';

// 渲染器
import { CanvasRenderer } from 'echarts/renderers';

// 注册所有用到的能力
echarts.use([
  // 系列
  LineChart,
  BarChart,
  ScatterChart,
  MapChart,
  BoxplotChart,
  HeatmapChart,
  RadarChart,
  // 组件
  TitleComponent,
  TooltipComponent,
  GridComponent,
  LegendComponent,
  DataZoomComponent,
  VisualMapComponent,
  MarkLineComponent,
  MarkAreaComponent,
  ToolboxComponent,
  GeoComponent,
  RadarComponent,
  PolarComponent,
  DatasetComponent,
  // 渲染器
  CanvasRenderer,
]);

export * from 'echarts/core';
export type { ECharts } from 'echarts/core';
export default echarts;