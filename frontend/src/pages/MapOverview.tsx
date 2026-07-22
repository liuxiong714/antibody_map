import React, { useEffect, useState, useCallback, useRef } from 'react';
import { Card, Row, Col, Statistic, Spin, message, Table, Select, InputNumber, Button } from 'antd';
import ReactECharts from 'echarts-for-react';
import * as echarts from 'echarts';
import { SearchOutlined } from '@ant-design/icons';
import DiseaseSelector from '../components/DiseaseSelector';
import ProvinceSelector from '../components/ProvinceSelector';
import MapSelector from '../components/MapSelector';
import { useFilterStore } from '../store';
import { getProvinceData } from '../services/map';
import { MapDataPoint } from '../types';
import { SERO_COLOR_STOPS, GMC_COLOR_STOPS, GENDER_OPTIONS, OCCUPATION_OPTIONS, PROVINCE_GEOJSON_NAME } from '../utils/constants';

const MapOverview: React.FC = () => {
  const { disease, dataType, province, yearStart, yearEnd, ageMin, ageMax, gender, occupation,
    setDisease, setDataType, setProvince, setYearRange, setAgeRange, setGender, setOccupation } = useFilterStore();
  const [mapReady, setMapReady] = useState(false);
  const [mapData, setMapData] = useState<MapDataPoint[]>([]);
  const [loading, setLoading] = useState(false);

  // Load GeoJSON — register map synchronously BEFORE triggering render
  useEffect(() => {
    fetch('https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json')
      .then((r) => r.json())
      .then((data) => {
        echarts.registerMap('china', data);
        setMapReady(true);
      })
      .catch(() => message.error('地图数据加载失败'));
  }, []);

  // Fetch map data
  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, unknown> = {};
      if (disease) params.disease = disease;
      if (dataType) params.data_type = dataType;
      if (province) params.province = province;
      if (yearStart) params.year_start = yearStart;
      if (yearEnd) params.year_end = yearEnd;
      if (ageMin != null) params.age_min = ageMin;
      if (ageMax != null) params.age_max = ageMax;
      if (gender) params.gender = gender;
      if (occupation) params.occupation = occupation;
      const resp = await getProvinceData(params);
      setMapData(resp.data || []);
    } catch {
      message.error('数据加载失败');
    } finally {
      setLoading(false);
    }
  }, [disease, dataType, province, yearStart, yearEnd, ageMin, ageMax, gender, occupation]);

  useEffect(() => { fetchData(); }, []);

  const getOption = () => {
    if (!mapReady) return {};
    const colorStops = dataType === 'gmc' ? GMC_COLOR_STOPS : SERO_COLOR_STOPS;
    const maxVal = Math.max(...mapData.map((d) => Number(d.weighted_positivity) || 0), 1);

    // 构建短名称 → GeoJSON 全名的映射（用于 ECharts 精确匹配地图区域）
    const nameMap: Record<string, string> = {};
    mapData.forEach((d) => {
      if (d.province && PROVINCE_GEOJSON_NAME[d.province]) {
        nameMap[PROVINCE_GEOJSON_NAME[d.province]] = d.province;
      }
    });

    // 系列数据：将数据库短名称转换为 GeoJSON 全名
    const seriesData = mapData
      .filter((d) => d.province && PROVINCE_GEOJSON_NAME[d.province])
      .map((d) => ({
        name: PROVINCE_GEOJSON_NAME[d.province],
        value: Number(d.weighted_positivity) || 0,
      }));

    return {
      tooltip: {
        trigger: 'item',
        formatter: (params: { name: string; value?: number }) => {
          // params.name 是 GeoJSON 全名，映射回短名称查数据
          const shortName = nameMap[params.name] || params.name;
          const item = mapData.find((d) => d.province === shortName);
          if (!item) return `${params.name}<br/>暂无数据`;
          const valueLabel = dataType === 'gmc' ? 'GMC' : '阳性率';
          const valueUnit = dataType === 'gmc' ? ' μg/ml' : '%';
          return `<b>${shortName}</b><br/>
            ${valueLabel}: ${item.weighted_positivity != null ? Number(item.weighted_positivity).toFixed(2) + valueUnit : '-'}<br/>
            数据点数: ${item.point_count}<br/>
            研究数: ${item.study_count}<br/>
            总样本量: ${item.total_sample.toLocaleString()}`;
        },
      },
      visualMap: {
        min: 0,
        max: maxVal,
        seriesIndex: 0,
        text: [dataType === 'gmc' ? '高' : '高', dataType === 'gmc' ? '低' : '低'],
        inRange: { color: colorStops.map((s) => s.color) },
        calculable: true,
        left: 'left',
        bottom: 20,
      },
      geo: {
        map: 'china',
        roam: true,
        label: { show: true, fontSize: 10, color: '#333' },
        itemStyle: { areaColor: '#f3f3f3', borderColor: '#ccc' },
        emphasis: { itemStyle: { areaColor: '#a6c84c' } },
        regions: mapData
          .filter((d) => d.province && PROVINCE_GEOJSON_NAME[d.province])
          .map((d) => ({
            name: PROVINCE_GEOJSON_NAME[d.province],
          })),
      },
      series: [
        {
          type: 'map',
          map: 'china',
          geoIndex: 0,
          data: seriesData,
        },
      ],
    };
  };

  const totalPoints = mapData.reduce((s, d) => s + d.point_count, 0);
  const totalProvinces = mapData.length;
  const totalSample = mapData.reduce((s, d) => s + d.total_sample, 0);

  return (
    <Spin spinning={loading}>
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={16} align="middle">
          <Col><span style={{ fontWeight: 'bold' }}>筛选条件：</span></Col>
          <Col><DiseaseSelector value={disease} onChange={(v: string) => setDisease(v)} /></Col>
          <Col><MapSelector value={dataType} onChange={setDataType} /></Col>
          <Col><ProvinceSelector value={province} onChange={setProvince} /></Col>
        </Row>
        <Row gutter={16} align="middle" style={{ marginTop: 12 }}>
          <Col><span style={{ fontWeight: 'bold' }}>细分条件：</span></Col>
          <Col>
            <InputNumber style={{ width: 80 }} placeholder="最小年龄" value={ageMin}
              onChange={(v: number | null) => setAgeRange(v, ageMax)} min={0} max={200} />
          </Col>
          <Col><span style={{ padding: '0 4px' }}>~</span></Col>
          <Col>
            <InputNumber style={{ width: 80 }} placeholder="最大年龄" value={ageMax}
              onChange={(v: number | null) => setAgeRange(ageMin, v)} min={0} max={200} />
          </Col>
          <Col>
            <Select value={gender} onChange={setGender} style={{ width: 90 }} placeholder="性别" allowClear
              options={GENDER_OPTIONS} />
          </Col>
          <Col>
            <Select value={occupation} onChange={setOccupation} style={{ width: 130 }} placeholder="职业（人群）" allowClear
              options={OCCUPATION_OPTIONS} />
          </Col>
          <Col>
            <InputNumber style={{ width: 90 }} placeholder="起始年" value={yearStart} onChange={(v: number | null) => setYearRange(v, yearEnd)} />
          </Col>
          <Col><span style={{ padding: '0 4px' }}>~</span></Col>
          <Col>
            <InputNumber style={{ width: 90 }} placeholder="结束年" value={yearEnd} onChange={(v: number | null) => setYearRange(yearStart, v)} />
          </Col>
          <Col>
            <Button type="primary" icon={<SearchOutlined />} onClick={fetchData} loading={loading}>查询</Button>
          </Col>
        </Row>
      </Card>

      <Row gutter={16}>
        <Col span={18}>
          <Card title="中国抗体水平分布图">
            {mapReady ? (
              <ReactECharts
                option={getOption()}
                style={{ height: 520 }}
              />
            ) : (
              <Spin tip="加载地图数据..." style={{ height: 520, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <div style={{ height: 520 }} />
              </Spin>
            )}
          </Card>
        </Col>
        <Col span={6}>
          <Card title="省份详情" style={{ height: '100%' }}>
            <Table
              dataSource={mapData}
              rowKey="province"
              size="small"
              pagination={false}
              scroll={{ y: 440 }}
              columns={[
                { title: '省份', dataIndex: 'province', key: 'province', width: 70 },
                {
                  title: dataType === 'gmc' ? 'GMC' : '阳性率',
                  dataIndex: 'weighted_positivity',
                  key: 'wp',
                  width: 80,
                  render: (v: number | null) => (v != null ? Number(v).toFixed(2) + (dataType === 'gmc' ? ' μg/ml' : '%') : '-'),
                },
                { title: '数据点', dataIndex: 'point_count', key: 'pc', width: 60 },
              ]}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={8}>
          <Card><Statistic title="总数据点数" value={totalPoints} /></Card>
        </Col>
        <Col span={8}>
          <Card><Statistic title="覆盖省份数" value={totalProvinces} /></Card>
        </Col>
        <Col span={8}>
          <Card><Statistic title="总样本量" value={totalSample} formatter={(v) => (v as number).toLocaleString()} /></Card>
        </Col>
      </Row>
    </Spin>
  );
};

export default MapOverview;
