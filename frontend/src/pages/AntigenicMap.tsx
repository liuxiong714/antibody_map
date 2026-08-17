import React, { useState, useEffect, useMemo } from 'react';
import { Card, Select, Spin, Empty, Switch, Space, Tag, Row, Col, Statistic, Alert, message } from 'antd';
import { RadarChartOutlined } from '@ant-design/icons';
import ReactECharts from '../components/EChart';
import { getTiterTables, getAntigenicMap } from '../services/map';
import { antigenicMapOption } from '../utils/chartBuilders';
import type { TiterTableItem, AntigenicMapData } from '../types';

const ASSAY_LABEL: Record<string, string> = {
  hi: '血凝抑制 (HI)',
  vnt: '病毒中和 (VNT)',
  elisa: '酶联免疫 (ELISA)',
};

const CONFIDENCE_LABEL: Record<string, string> = {
  high: '高',
  medium: '中',
  low: '低',
};

const AntigenicMap: React.FC = () => {
  const [tables, setTables] = useState<TiterTableItem[]>([]);
  const [tablesLoading, setTablesLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<string | undefined>(undefined);
  const [mapData, setMapData] = useState<AntigenicMapData | null>(null);
  const [loading, setLoading] = useState(false);
  const [showLabels, setShowLabels] = useState(true);

  // 加载可用滴度矩阵列表
  useEffect(() => {
    const load = async () => {
      setTablesLoading(true);
      try {
        const resp = await getTiterTables();
        const items = resp?.items ?? [];
        setTables(items);
        if (items.length && !selectedId) {
          setSelectedId(items[0].id);
        }
      } catch {
        message.error('加载滴度矩阵列表失败');
      } finally {
        setTablesLoading(false);
      }
    };
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 选择矩阵后加载制图结果
  useEffect(() => {
    if (!selectedId) {
      setMapData(null);
      return;
    }
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        const resp = await getAntigenicMap(selectedId);
        if (!cancelled) setMapData(resp);
      } catch (e) {
        if (!cancelled) {
          setMapData(null);
          const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
          message.error(detail || '制图失败');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const selectedTable = tables.find((t) => t.id === selectedId);

  const chartOption = useMemo(() => {
    if (!mapData || !mapData.coordinates?.length) return null;
    return antigenicMapOption(
      mapData.coordinates,
      mapData.stress_normalized ?? mapData.stress_raw,
      mapData.grid_explanation,
      showLabels,
    );
  }, [mapData, showLabels]);

  const droppedCount = mapData?.dropped_rows?.length ?? 0;

  return (
    <>
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={[12, 12]} align="middle">
          <Col>
            <strong style={{ color: '#ff4d4f' }}>* </strong>
          </Col>
          <Col>
            <Select
              style={{ minWidth: 420 }}
              placeholder="选择滴度矩阵（审核通过）"
              loading={tablesLoading}
              value={selectedId}
              onChange={setSelectedId}
              options={tables.map((t) => ({
                value: t.id,
                label: `${t.literature_title}（${ASSAY_LABEL[t.assay_type] ?? t.assay_type}，${t.n_antigens}×${t.n_sera}）`,
              }))}
              showSearch
              optionFilterProp="label"
              notFoundContent={tablesLoading ? <Spin size="small" /> : '暂无审核通过的滴度矩阵'}
            />
          </Col>
          <Col>
            <Space size="middle">
              <span>点标签</span>
              <Switch checked={showLabels} onChange={setShowLabels} />
            </Space>
          </Col>
        </Row>
        {droppedCount > 0 && (
          <Alert
            style={{ marginTop: 8 }}
            type="warning"
            showIcon
            message={`已剔除 ${droppedCount} 个含检出限(<10)或缺失的抗原行（v1 简化策略）`}
          />
        )}
      </Card>

      <Spin spinning={loading}>
        {!selectedId ? (
          <Empty description="暂无审核通过的滴度矩阵，请先在文献提取中完成滴度表提取与审核" />
        ) : !mapData ? (
          <Empty description="该矩阵无法制图或未通过审核" />
        ) : (
          <>
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={6}>
                <Card><Statistic title="检测类型" value={ASSAY_LABEL[mapData.assay_type] ?? mapData.assay_type} /></Card>
              </Col>
              <Col span={6}>
                <Card><Statistic title="抗原 × 血清" value={`${mapData.n_antigen} × ${mapData.n_serum}`} /></Card>
              </Col>
              <Col span={6}>
                <Card>
                  <Statistic
                    title="归一化应力 stress"
                    value={mapData.stress_normalized ?? mapData.stress_raw}
                    precision={4}
                  />
                </Card>
              </Col>
              <Col span={6}>
                <Card>
                  <Statistic title="质量分" value={mapData.quality_score ?? '-'} suffix={mapData.quality_score != null ? '分' : ''} />
                  <div style={{ marginTop: 4 }}>
                    <Tag color={mapData.converged ? 'green' : 'orange'}>
                      {mapData.converged ? '已收敛' : '未收敛'}（{mapData.n_iter} 次迭代）
                    </Tag>
                    {mapData.confidence && (
                      <Tag>{CONFIDENCE_LABEL[mapData.confidence] ?? mapData.confidence}置信度</Tag>
                    )}
                  </div>
                </Card>
              </Col>
            </Row>

            <Card
              title={
                <Space>
                  <RadarChartOutlined />
                  <span>抗原图谱（{selectedTable?.literature_title ?? ''}）</span>
                  {selectedTable && <Tag>{ASSAY_LABEL[selectedTable.assay_type] ?? selectedTable.assay_type}</Tag>}
                </Space>
              }
              style={{ marginBottom: 16 }}
            >
              {chartOption ? (
                <ReactECharts option={chartOption} style={{ height: 520 }} />
              ) : (
                <Empty description="无坐标数据" />
              )}
              <div style={{ color: '#999', fontSize: 12, marginTop: 8 }}>
                {mapData.grid_explanation}；抗原以红色方块(■)表示，血清以蓝色圆点(●)表示；
                距离越近表示抗原-血清反应越接近。方法学：{mapData.meta?.methodology_note ?? ''}
              </div>
            </Card>
          </>
        )}
      </Spin>
    </>
  );
};

export default AntigenicMap;
