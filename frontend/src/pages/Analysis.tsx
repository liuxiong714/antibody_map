import React, { useState, useCallback, useEffect } from 'react';
import { Card, Row, Col, Spin, Empty, message, Button } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import DiseaseSelector from '../components/DiseaseSelector';
import ProvinceSelector from '../components/ProvinceSelector';
import MapSelector from '../components/MapSelector';
import { getTrend, getRegionCompare, getAgeStratify } from '../services/map';
import { useFilterStore } from '../store';

type DataItem = Record<string, unknown>;

const Analysis: React.FC = () => {
  const { disease: globalDisease, dataType: globalDataType, setDisease, setDataType } = useFilterStore();

  // 本地筛选状态（未确认时不触发查询）
  const [localDisease, setLocalDisease] = useState(globalDisease);
  const [localDataType, setLocalDataType] = useState(globalDataType);
  const [province, setProvince] = useState('');

  // 实际查询参数（确认后生效）
  const [appliedDisease, setAppliedDisease] = useState('');
  const [appliedDataType, setAppliedDataType] = useState('');
  const [appliedProvince, setAppliedProvince] = useState('');

  const [loading, setLoading] = useState(false);
  const [trendData, setTrendData] = useState<DataItem[]>([]);
  const [regionData, setRegionData] = useState<DataItem[]>([]);
  const [ageData, setAgeData] = useState<DataItem[]>([]);

  const fetchAll = useCallback(async () => {
    if (!appliedDisease && !appliedDataType && !appliedProvince) return;
    setLoading(true);
    try {
      const params: Record<string, unknown> = {};
      if (appliedDisease) params.disease = appliedDisease;
      if (appliedDataType) params.data_type = appliedDataType;
      if (appliedProvince) params.province = appliedProvince;

      const [trend, region, age] = await Promise.all([
        getTrend(params),
        getRegionCompare(params),
        getAgeStratify(params),
      ]);
      setTrendData((trend.data as DataItem[]) || []);
      setRegionData((region.data as DataItem[]) || []);
      setAgeData((age.data as DataItem[]) || []);
    } catch {
      message.error('数据加载失败');
    } finally {
      setLoading(false);
    }
  }, [appliedDisease, appliedDataType, appliedProvince]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // 确认筛选：同步到全局 store 并触发查询
  const handleConfirm = () => {
    setDisease(localDisease);
    setDataType(localDataType);
    setAppliedDisease(localDisease);
    setAppliedDataType(localDataType);
    setAppliedProvince(province);
  };

  // 根据数据类型获取对应的数值字段
  // 趋势接口：seroprevalence → weighted_positivity, gmc → avg_gmc
  // 区域/年龄接口：seroprevalence → avg_positivity, gmc → avg_gmc
  const isGmc = appliedDataType === 'gmc';
  const trendValueField = isGmc ? 'avg_gmc' : 'weighted_positivity';
  const compareValueField = isGmc ? 'avg_gmc' : 'avg_positivity';
  const yAxisLabel = isGmc ? 'GMC' : '阳性率 (%)';

  const trendOption = trendData.length ? {
    title: { text: '年份趋势', left: 'center' },
    xAxis: { type: 'category', data: trendData.map((d) => (d as { year: number }).year) },
    yAxis: { type: 'value', name: yAxisLabel },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v: number) => isGmc ? `${v}` : `${v}%`,
    },
    series: [{
      type: 'line',
      name: yAxisLabel,
      data: trendData.map((d) => (d[trendValueField] ?? null) as number),
      smooth: true,
    }],
  } : null;

  const regionOption = regionData.length ? {
    title: { text: '省份均值对比', left: 'center' },
    xAxis: {
      type: 'category',
      data: regionData.map((d) => (d as { province: string }).province),
      axisLabel: { rotate: 45 },
    },
    yAxis: { type: 'value', name: yAxisLabel },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v: number) => isGmc ? `${v}` : `${v}%`,
    },
    series: [{
      type: 'bar',
      name: yAxisLabel,
      data: regionData.map((d) => (d[compareValueField] ?? null) as number),
    }],
  } : null;

  const ageOption = ageData.length ? {
    title: { text: '年龄分布', left: 'center' },
    xAxis: {
      type: 'category',
      data: ageData.map((d) => (d as { age_group: string }).age_group),
    },
    yAxis: { type: 'value', name: yAxisLabel },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v: number) => isGmc ? `${v}` : `${v}%`,
    },
    series: [{
      type: 'bar',
      name: yAxisLabel,
      data: ageData.map((d) => (d[compareValueField] ?? null) as number),
    }],
  } : null;

  return (
    <>
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={16} align="middle">
          <Col><span style={{ fontWeight: 'bold' }}>筛选：</span></Col>
          <Col><DiseaseSelector value={localDisease} onChange={setLocalDisease} /></Col>
          <Col><MapSelector value={localDataType} onChange={setLocalDataType} /></Col>
          <Col><ProvinceSelector value={province} onChange={setProvince} /></Col>
          <Col>
            <Button type="primary" icon={<SearchOutlined />} onClick={handleConfirm}>
              查询
            </Button>
          </Col>
        </Row>
      </Card>

      <Spin spinning={loading}>
        <Row gutter={16}>
          <Col span={12}>
            <Card>
              {regionOption ? <ReactECharts option={regionOption} style={{ height: 350 }} /> : <Empty description="请选择筛选条件后点击查询" />}
            </Card>
          </Col>
          <Col span={12}>
            <Card>
              {trendOption ? <ReactECharts option={trendOption} style={{ height: 350 }} /> : <Empty description="请选择筛选条件后点击查询" />}
            </Card>
          </Col>
        </Row>
        <Row gutter={16} style={{ marginTop: 16 }}>
          <Col span={12}>
            <Card>
              {ageOption ? <ReactECharts option={ageOption} style={{ height: 350 }} /> : <Empty description="请选择筛选条件后点击查询" />}
            </Card>
          </Col>
        </Row>
      </Spin>
    </>
  );
};

export default Analysis;
