/**
 * ChartWithSnapshot：带"引用 + PNG 水印导出"的图表卡片。
 *
 * - 卡片右上角：引用图标（SnapshotCitation）+ 导出 PNG 按钮；
 * - 导出 PNG 时在右下角以 ECharts graphic 附加小字水印（快照号前 8 位 + 数据截至日期），
 *   导出完成后移除水印，不影响屏幕显示。
 */
import React, { useCallback, useRef } from 'react';
import { Button, Card, Space, Tooltip, message } from 'antd';
import { DownloadOutlined } from '@ant-design/icons';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from '../lib/echarts';
import SnapshotCitation from './SnapshotCitation';

interface ChartWithSnapshotProps {
  option: Record<string, unknown> | null | undefined;
  /** 图表标题（卡片标题 + 引用弹层标题） */
  title?: string;
  /** 后端返回的 meta.snapshot_token */
  token?: string | null;
  height?: number | string;
  style?: React.CSSProperties;
  onEvents?: Record<string, (params: unknown) => void>;
  /** 图表下方附加内容（表格、切换按钮等） */
  children?: React.ReactNode;
}

const ChartWithSnapshot: React.FC<ChartWithSnapshotProps> = ({
  option,
  title,
  token,
  height = 350,
  style,
  onEvents,
  children,
}) => {
  const chartRef = useRef<ReactEChartsCore>(null);

  const exportPng = useCallback(() => {
    const inst = chartRef.current?.getEchartsInstance();
    if (!inst) {
      message.warning('图表尚未就绪，请稍后再试');
      return;
    }
    const dataAsOf = new Date().toISOString().slice(0, 10);
    const short = token ? token.slice(0, 8) : 'no-token';
    const watermark = {
      type: 'text',
      right: 8,
      bottom: 4,
      style: { fill: 'rgba(0,0,0,0.25)', fontSize: 10, fontFamily: 'sans-serif' },
      text: `快照 ${short} · 数据截至 ${dataAsOf}`,
    };
    // 导出前注入水印 graphic，导出后移除
    inst.setOption({ graphic: [watermark] });
    const url = inst.getDataURL({ pixelRatio: 2, backgroundColor: '#fff' });
    inst.setOption({ graphic: [] });
    const a = document.createElement('a');
    a.href = url;
    a.download = `antibody_map_${(title || 'chart').replace(/[\\/:*?"<>|\s]+/g, '_')}_${dataAsOf}.png`;
    a.click();
  }, [token, title]);

  return (
    <Card
      size="small"
      title={title}
      extra={
        <Space size={0}>
          <SnapshotCitation token={token} title={title} />
          <Tooltip title="导出 PNG（右下角含水印）">
            <Button type="link" size="small" icon={<DownloadOutlined />} onClick={exportPng} />
          </Tooltip>
        </Space>
      }
      style={{ marginBottom: 12, ...style }}
    >
      {option ? (
        <ReactEChartsCore
          ref={chartRef}
          echarts={echarts}
          option={option}
          style={{ height }}
          notMerge
          lazyUpdate
          onEvents={onEvents}
        />
      ) : (
        <div style={{ height }} />
      )}
      {children}
    </Card>
  );
};

export default ChartWithSnapshot;
