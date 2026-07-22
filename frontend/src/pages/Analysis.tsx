import React, { useState, useCallback, useEffect } from 'react';
import { Card, Row, Col, Spin, Empty, message } from 'antd';
import ReactECharts from 'echarts-for-react';
import DiseaseSelector from '../components/DiseaseSelector';
import ProvinceSelector from '../components/ProvinceSelector';
import MapSelector from '../components/MapSelector';
import { getTrend, getRegionCompare, getAgeStratify } from '../services/map';
import { useFilterStore } from '../store';

const Analysis: React.FC = () => {
  const { disease, dataType, setDisease, setDataType } = useFilterStore();
  const [province, setProvince] = useState('');
  const [loading, setLoading] = useState(false);
  const [trendData, setTrendData] = useState<Record<string, unknown>[]>([]);
  const [regionData, setRegionData] = useState<Record<string, unknown>[]>([]);
  const [ageData, setAgeData] = useState<Record<string, unknown>[]>([]);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, unknown> = {};
      if (disease) params.disease = disease;
      if (dataType) params.data_type = dataType;
      if (province) params.province = province;

      const [trend, region, age] = await Promise.all([
        getTrend(params),
        getRegionCompare(params),
        getAgeStratify(params),
      ]);
      setTrendData((trend.data as Record<string, unknown>[]) || []);
      setRegionData((region.data as Record<string, unknown>[]) || []);
      setAgeData((age.data as Record<string, unknown>[]) || []);
    } catch {
      message.error('数据加载失败');
    } finally {
      setLoading(false);
    }
  }, [disease, dataType, province]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const trendOption = trendData.length ? {
    title: { text: '年份趋势', left: 'center' },
    xAxis: { type: 'category', data: trendData.map((d) => (d as { year: number }).year) },
    yAxis: { type: 'value', name: dataType === 'gmc' ? 'GMC' : '阳性率 (%)' },
    tooltip: { trigger: 'axis' },
    series: [{
      type: 'line',
      data: trendData.map((d) => (d as { weighted_positivity: number }).weighted_positivity),
      smooth: true,
    }],
  } : null;

  const regionOption = regionData.length ? {
    title: { text: '省份均值对比', left: 'center' },
    xAxis: { type: 'category', data: regionData.map((d) => (d as { province: string }).province), axisLabel: { rotate: 45 } },
    yAxis: { type: 'value', name: dataType === 'gmc' ? 'GMC' : '阳性率 (%)' },
    tooltip: { trigger: 'axis' },
    series: [{
      type: 'bar',
      data: regionData.map((d) => (d as { avg_positivity: number }).avg_positivity),
    }],
  } : null;

  const ageOption = ageData.length ? {
    title: { text: '年龄分布', left: 'center' },
    xAxis: { type: 'category', data: ageData.map((d) => (d as { age_group: string }).age_group) },
    yAxis: { type: 'value', name: dataType === 'gmc' ? 'GMC' : '阳性率 (%)' },
    tooltip: { trigger: 'axis' },
    series: [{
      type: 'bar',
      data: ageData.map((d) => (d as { avg_positivity: number }).avg_positivity),
    }],
  } : null;

  return (
    <>
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={16} align="middle">
          <Col><span style={{ fontWeight: 'bold' }}>筛选：</span></Col>
          <Col><DiseaseSelector value={disease} onChange={setDisease} /></Col>
          <Col><MapSelector value={dataType} onChange={setDataType} /></Col>
          <Col><ProvinceSelector value={province} onChange={setProvince} /></Col>
        </Row>
      </Card>

      <Spin spinning={loading}>
        <Row gutter={16}>
          <Col span={12}>
            <Card>
              {regionOption ? <ReactECharts option={regionOption} style={{ height: 350 }} /> : <Empty description="暂无数据" />}
            </Card>
          </Col>
          <Col span={12}>
            <Card>
              {trendOption ? <ReactECharts option={trendOption} style={{ height: 350 }} /> : <Empty description="暂无数据" />}
            </Card>
          </Col>
        </Row>
        <Row gutter={16} style={{ marginTop: 16 }}>
          <Col span={12}>
            <Card>
              {ageOption ? <ReactECharts option={ageOption} style={{ height: 350 }} /> : <Empty description="暂无数据" />}
            </Card>
          </Col>
        </Row>
      </Spin>
    </>
  );
};

export default Analysis;
