import React, { useEffect, useState, useCallback, useRef } from 'react';
import { Card, Row, Col, Statistic, Spin, message, Table, Select, InputNumber, Button, Slider, Segmented, Space, Tooltip, Tag } from 'antd';
import ReactECharts from 'echarts-for-react';
import * as echarts from 'echarts';
import { SearchOutlined, ReloadOutlined, PlayCircleOutlined, PauseCircleOutlined, StepBackwardOutlined, StepForwardOutlined, CalendarOutlined, SyncOutlined } from '@ant-design/icons';
import DiseaseSelector from '../components/DiseaseSelector';
import ProvinceSelector from '../components/ProvinceSelector';
import MapSelector from '../components/MapSelector';
import { useFilterStore } from '../store';
import { getProvinceData, getYearlyProvinceData, getAvailableYears } from '../services/map';
import { MapDataPoint, YearlyMapData } from '../types';
import { SERO_COLOR_STOPS, GMC_COLOR_STOPS, GENDER_OPTIONS, OCCUPATION_OPTIONS, PROVINCE_GEOJSON_NAME } from '../utils/constants';

const MapOverview: React.FC = () => {
  const { disease, dataType, province, yearStart, yearEnd, ageMin, ageMax, gender, occupation,
    setDisease, setDataType, setProvince, setYearRange, setAgeRange, setGender, setOccupation, reset } = useFilterStore();
  const [mapReady, setMapReady] = useState(false);
  const [mapData, setMapData] = useState<MapDataPoint[]>([]);
  const [loading, setLoading] = useState(false);

  // 时间序列相关状态
  const [dynamicMode, setDynamicMode] = useState<'static' | 'timeline'>('static');
  const [yearlyData, setYearlyData] = useState<YearlyMapData[]>([]);
  const [selectedYear, setSelectedYear] = useState<number | null>(null);
  const [availableYears, setAvailableYears] = useState<number[]>([]);
  const [playing, setPlaying] = useState(false);
  const [playSpeed, setPlaySpeed] = useState(1000);
  const playIntervalRef = useRef<number | null>(null);
  const yearRangeAutoRef = useRef<boolean>(false);  // 年份范围是否由系统自动管理

  // Load GeoJSON — register map synchronously BEFORE triggering render
  useEffect(() => {
    fetch('/china.json')
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
      setMapData(Array.isArray(resp) ? resp : []);
    } catch {
      message.error('数据加载失败');
    } finally {
      setLoading(false);
    }
  }, [disease, dataType, province, yearStart, yearEnd, ageMin, ageMax, gender, occupation]);

  useEffect(() => { fetchData(); }, []);

  // 模式切换时自动加载对应数据，并自动设置年份范围
  useEffect(() => {
    if (dynamicMode === 'timeline') {
      const currentYear = new Date().getFullYear();
      // 切换到时间序列模式时，始终启用自动管理
      yearRangeAutoRef.current = true;
      if (availableYears.length > 0) {
        const minYear = availableYears[0];
        const maxYear = availableYears[availableYears.length - 1];
        const effectiveEnd = Math.min(maxYear, currentYear);
        setYearRange(minYear, effectiveEnd);
      } else {
        setYearRange(2000, currentYear);
      }
      fetchYearlyData();
    }
  }, [dynamicMode]);

  // availableYears 更新时，如果在时间序列模式，自动更新年份范围
  useEffect(() => {
    if (dynamicMode === 'timeline' && availableYears.length > 0) {
      const currentYear = new Date().getFullYear();
      const minYear = availableYears[0];
      const maxYear = availableYears[availableYears.length - 1];
      const effectiveEnd = Math.min(maxYear, currentYear);
      // 系统自动管理模式 或 年份为空时，自动填充
      if (yearRangeAutoRef.current || !yearStart || !yearEnd) {
        yearRangeAutoRef.current = true;
        setYearRange(minYear, effectiveEnd);
      }
    }
  }, [availableYears]);

  // 时间序列模式下，筛选条件变化时自动重新加载
  useEffect(() => {
    if (dynamicMode === 'timeline') {
      fetchYearlyData();
    }
  }, [disease, dataType, province, yearStart, yearEnd, ageMin, ageMax, gender, occupation]);

  // 获取可用年份列表（疾病变化时更新）
  useEffect(() => {
    if (!disease) {
      setAvailableYears([]);
      return;
    }
    getAvailableYears(disease)
      .then(setAvailableYears)
      .catch(() => {
        setAvailableYears([]);
      });
  }, [disease]);

  // 获取按年份分组的数据
  const fetchYearlyData = useCallback(async () => {
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
      const resp = await getYearlyProvinceData(params);
      const sorted = Array.isArray(resp) ? [...resp].sort((a, b) => a.year - b.year) : [];
      setYearlyData(sorted);
      if (sorted.length > 0) {
        setSelectedYear(sorted[0].year);
      } else {
        setSelectedYear(null);
      }
    } catch {
      message.error('时间序列数据加载失败');
    } finally {
      setLoading(false);
    }
  }, [disease, dataType, province, yearStart, yearEnd, ageMin, ageMax, gender, occupation]);

  // 播放/暂停控制
  const stopPlay = useCallback(() => {
    setPlaying(false);
    if (playIntervalRef.current) {
      clearInterval(playIntervalRef.current);
      playIntervalRef.current = null;
    }
  }, []);

  const startPlay = useCallback(() => {
    if (yearlyData.length === 0 || selectedYear == null) return;
    setPlaying(true);
    playIntervalRef.current = window.setInterval(() => {
      setSelectedYear((prev) => {
        if (prev == null) return yearlyData[0].year;
        const idx = yearlyData.findIndex((y) => y.year === prev);
        if (idx < yearlyData.length - 1) {
          return yearlyData[idx + 1].year;
        } else {
          stopPlay();
          return prev;
        }
      });
    }, playSpeed);
  }, [yearlyData, selectedYear, playSpeed, stopPlay]);

  const togglePlay = useCallback(() => {
    if (playing) {
      stopPlay();
    } else {
      startPlay();
    }
  }, [playing, stopPlay, startPlay]);

  const stepYear = useCallback((direction: 'prev' | 'next') => {
    if (yearlyData.length === 0 || selectedYear == null) return;
    const idx = yearlyData.findIndex((y) => y.year === selectedYear);
    const newIdx = direction === 'next'
      ? Math.min(idx + 1, yearlyData.length - 1)
      : Math.max(idx - 1, 0);
    setSelectedYear(yearlyData[newIdx].year);
  }, [yearlyData, selectedYear]);

  // 组件卸载时清理
  useEffect(() => {
    return () => {
      if (playIntervalRef.current) {
        clearInterval(playIntervalRef.current);
      }
    };
  }, []);

  // 获取当前要展示的数据（静态或时间序列模式）
  const currentData: MapDataPoint[] = dynamicMode === 'timeline' && selectedYear != null
    ? yearlyData.find((y) => y.year === selectedYear)?.data || []
    : mapData;

  const getOption = () => {
    if (!mapReady) return {};
    const colorStops = dataType === 'gmc' ? GMC_COLOR_STOPS : SERO_COLOR_STOPS;
    const maxVal = Math.max(...currentData.map((d) => Number(d.weighted_positivity) || 0), 1);

    // 构建短名称 → GeoJSON 全名的映射（用于 ECharts 精确匹配地图区域）
    const nameMap: Record<string, string> = {};
    currentData.forEach((d) => {
      if (d.province && PROVINCE_GEOJSON_NAME[d.province]) {
        nameMap[PROVINCE_GEOJSON_NAME[d.province]] = d.province;
      }
    });

    // 系列数据：将数据库短名称转换为 GeoJSON 全名
    const seriesData = currentData
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
          const item = currentData.find((d) => d.province === shortName);
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
        regions: currentData
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
          animationDuration: 500,
          animationEasing: 'cubicOut',
        },
      ],
    };
  };

  const totalPoints = currentData.reduce((s, d) => s + d.point_count, 0);
  const totalProvinces = currentData.length;
  const totalSample = currentData.reduce((s, d) => s + d.total_sample, 0);

  return (
    <Spin spinning={loading}>
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={16} align="middle">
          <Col><span style={{ fontWeight: 'bold' }}>筛选条件：</span></Col>
          <Col><DiseaseSelector value={disease} onChange={(v: string) => setDisease(v)} /></Col>
          <Col><MapSelector value={dataType} onChange={setDataType} /></Col>
          <Col><ProvinceSelector value={province} onChange={setProvince} /></Col>
          <Col>
            <Segmented
              value={dynamicMode}
              onChange={(v) => setDynamicMode(v as 'static' | 'timeline')}
              options={[
                { label: '静态总览', value: 'static' },
                { label: <><CalendarOutlined /> 时间序列</>, value: 'timeline' },
              ]}
            />
          </Col>
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
            <InputNumber style={{ width: 90 }} placeholder="起始年" value={yearStart} onChange={(v: number | null) => { yearRangeAutoRef.current = false; setYearRange(v, yearEnd); }} />
          </Col>
          <Col><span style={{ padding: '0 4px' }}>~</span></Col>
          <Col>
            <InputNumber style={{ width: 90 }} placeholder="结束年" value={yearEnd} onChange={(v: number | null) => { yearRangeAutoRef.current = false; setYearRange(yearStart, v); }} />
          </Col>
          <Col>
            <Button type="primary" icon={<SearchOutlined />} onClick={() => { dynamicMode === 'timeline' ? fetchYearlyData() : fetchData(); }} loading={loading}>查询</Button>
          </Col>
          <Col>
            <Button icon={<ReloadOutlined />} onClick={() => { stopPlay(); yearRangeAutoRef.current = false; reset(); dynamicMode === 'timeline' ? fetchYearlyData() : fetchData(); }}>重置</Button>
          </Col>
        </Row>
      </Card>

      <Row gutter={16}>
        <Col span={18}>
          <Card
            title={
              <Space>
                <span>中国抗体水平分布图</span>
                {dynamicMode === 'timeline' && selectedYear != null && (
                  <Tag color="blue">当前年份: {selectedYear}</Tag>
                )}
              </Space>
            }
          >
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

          {/* 时间序列控制面板 */}
          {dynamicMode === 'timeline' && yearlyData.length > 0 && (
            <Card
              size="small"
              style={{ marginTop: 12 }}
              title={
                <Space>
                  <CalendarOutlined />
                  <span>时间序列动画</span>
                </Space>
              }
            >
              <Row gutter={16} align="middle">
                <Col flex="auto">
                  <Slider
                    min={yearlyData[0].year}
                    max={yearlyData[yearlyData.length - 1].year}
                    value={selectedYear || 0}
                    onChange={(v) => setSelectedYear(v as number)}
                    marks={Object.fromEntries(
                      yearlyData.map((y) => [y.year, String(y.year)])
                    )}
                    tooltip={{ formatter: (v) => `${v} 年` }}
                  />
                </Col>
                <Col>
                  <Space>
                    <Tooltip title="上一年">
                      <Button
                        icon={<StepBackwardOutlined />}
                        onClick={() => stepYear('prev')}
                        disabled={playing || selectedYear === yearlyData[0].year}
                      />
                    </Tooltip>
                    <Button
                      icon={playing ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
                      onClick={togglePlay}
                      type="primary"
                    >
                      {playing ? '暂停' : '播放'}
                    </Button>
                    <Tooltip title="下一年">
                      <Button
                        icon={<StepForwardOutlined />}
                        onClick={() => stepYear('next')}
                        disabled={playing || selectedYear === yearlyData[yearlyData.length - 1].year}
                      />
                    </Tooltip>
                  </Space>
                </Col>
                <Col>
                  <Select
                    value={playSpeed}
                    onChange={(v) => { setPlaySpeed(v); if (playing) { stopPlay(); setTimeout(startPlay, 100); } }}
                    style={{ width: 100 }}
                    options={[
                      { value: 2000, label: '慢速 2s' },
                      { value: 1000, label: '正常 1s' },
                      { value: 500, label: '快速 0.5s' },
                    ]}
                  />
                </Col>
                <Col>
                  <Tooltip title="实时数据统计">
                    <span style={{ color: '#888', fontSize: 12 }}>
                      {selectedYear != null && yearlyData.find((y) => y.year === selectedYear)
                        ? `${yearlyData.find((y) => y.year === selectedYear)!.data.length} 个省份 · ${yearlyData.find((y) => y.year === selectedYear)!.data.reduce((s, d) => s + d.point_count, 0)} 个数据点`
                        : '暂无数据'}
                    </span>
                  </Tooltip>
                </Col>
              </Row>
            </Card>
          )}
        </Col>
        <Col span={6}>
          <Card title={dynamicMode === 'timeline' && selectedYear ? `${selectedYear}年 省份详情` : '省份详情'} style={{ height: '100%' }}>
            <Table
              dataSource={currentData}
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
