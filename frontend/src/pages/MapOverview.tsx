import React, { useEffect, useState, useCallback, useRef } from 'react';
import { Card, Row, Col, Statistic, Spin, message, Table, Select, InputNumber, Button, Slider, Segmented, Space, Tooltip, Tag, Modal, Descriptions } from 'antd';
import * as echarts from '../lib/echarts';
import { SearchOutlined, ReloadOutlined, PlayCircleOutlined, PauseCircleOutlined, StepBackwardOutlined, StepForwardOutlined, CalendarOutlined, ArrowLeftOutlined, DownloadOutlined, CompassOutlined } from '@ant-design/icons';
import DiseaseSelector from '../components/DiseaseSelector';
import ProvinceSelector from '../components/ProvinceSelector';
import MapSelector from '../components/MapSelector';
import { useFilterStore } from '../store';
import { getProvinceData, getYearlyProvinceData, getAvailableYears, getCityData, getPopulationOptions, getSummary } from '../services/map';
import { MapDataPoint, YearlyMapData } from '../types';
import { SERO_COLOR_STOPS, GMC_COLOR_STOPS, GENDER_OPTIONS, PROVINCE_GEOJSON_NAME, DISEASES } from '../utils/constants';

// 英文 disease key → 中文名称
const DISEASE_CN_MAP: Record<string, string> = Object.fromEntries(
  DISEASES.map((d) => [d.key, d.name_cn])
);
const diseaseToCn = (key?: string): string => {
  if (!key) return '';
  return DISEASE_CN_MAP[key] || key;
};

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

  // 省份详情相关状态
  const [selectedProvince, setSelectedProvince] = useState<string | null>(null);
  const [provinceYearly, setProvinceYearly] = useState<YearlyMapData[]>([]);
  const [provinceCities, setProvinceCities] = useState<MapDataPoint[]>([]);
  const [provinceDetailLoading, setProvinceDetailLoading] = useState(false);

  // 地图下钻状态：drillProvince 不为空时显示该省份的城市级散点图
  const [drillProvince, setDrillProvince] = useState<string | null>(null);
  const [drillCityData, setDrillCityData] = useState<MapDataPoint[]>([]);

  // 城市详情弹窗
  const [cityDetailOpen, setCityDetailOpen] = useState(false);
  const [cityDetailData, setCityDetailData] = useState<MapDataPoint | null>(null);

  // 动态人群（职业）选项——根据文献中实际定义的研究对象自动更新
  const [populationOptions, setPopulationOptions] = useState<string[]>([]);

  // 汇总统计（含已审核/未审核区分）
  const [summaryData, setSummaryData] = useState<{
    point_count: number;
    province_count: number;
    total_sample: number;
    unapproved_point_count: number;
    unapproved_province_count: number;
    unapproved_total_sample: number;
  } | null>(null);

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

  // 动态获取人群（职业）选项——根据已审核数据点的 population 字段自动更新
  // 疾病切换时重新获取（不同疾病可能有不同的人群分类）
  useEffect(() => {
    getPopulationOptions(disease || undefined)
      .then((opts) => setPopulationOptions(Array.isArray(opts) ? opts : []))
      .catch((e) => console.error('获取人群选项失败:', e));
  }, [disease]);

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
      if (occupation.length > 0) params.occupation = occupation.join(',');
      const resp = await getProvinceData(params);
      setMapData(Array.isArray(resp) ? resp : []);

      // 同时获取汇总统计（含已审核/未审核区分）
      const summaryParams: Record<string, unknown> = {};
      if (disease) summaryParams.disease = disease;
      if (dataType) summaryParams.data_type = dataType;
      getSummary(summaryParams).then(setSummaryData).catch(() => {});
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
      if (occupation.length > 0) params.occupation = occupation.join(',');
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

  // 点击地图省份，获取该省份的详细数据
  const handleProvinceClick = useCallback(async (provinceName: string) => {
    setSelectedProvince(provinceName);
    setDrillProvince(provinceName);
    setProvinceDetailLoading(true);
    try {
      const baseParams: Record<string, unknown> = { province: provinceName };
      if (disease) baseParams.disease = disease;
      if (dataType) baseParams.data_type = dataType;
      if (yearStart) baseParams.year_start = yearStart;
      if (yearEnd) baseParams.year_end = yearEnd;
      if (ageMin != null) baseParams.age_min = ageMin;
      if (ageMax != null) baseParams.age_max = ageMax;
      if (gender) baseParams.gender = gender;
      if (occupation.length > 0) baseParams.occupation = occupation.join(',');

      // 并行获取：历年趋势数据 + 城市分布数据
      const [yearlyResp, cityResp] = await Promise.all([
        getYearlyProvinceData(baseParams),
        getCityData({ province: provinceName, ...(disease ? { disease } : {}), ...(dataType ? { data_type: dataType } : {}) }),
      ]);
      setProvinceYearly(Array.isArray(yearlyResp) ? [...yearlyResp].sort((a, b) => a.year - b.year) : []);
      const cities = Array.isArray(cityResp) ? cityResp : [];
      setProvinceCities(cities);
      setDrillCityData(cities);
    } catch {
      setProvinceYearly([]);
      setProvinceCities([]);
      setDrillCityData([]);
    } finally {
      setProvinceDetailLoading(false);
    }
  }, [disease, dataType, yearStart, yearEnd, ageMin, ageMax, gender, occupation]);

  // 城市散点点击：显示详情弹窗
  const handleCityScatterClick = useCallback((cityData: MapDataPoint) => {
    setCityDetailData(cityData);
    setCityDetailOpen(true);
  }, []);

  // 返回全国视图（取消地图下钻）
  const handleBackToNational = useCallback(() => {
    setDrillProvince(null);
    setDrillCityData([]);
    setSelectedProvince(null);
  }, []);

  // 图表容器 ref
  const chartContainerRef = useRef<HTMLDivElement | null>(null);
  const chartInstanceRef = useRef<echarts.ECharts | null>(null);
  const handleProvinceClickRef = useRef(handleProvinceClick);
  const handleCityScatterClickRef = useRef(handleCityScatterClick);
  const drillCityDataRef = useRef(drillCityData);
  const handleBackToNationalRef = useRef(handleBackToNational);
  const drillProvinceRef = useRef(drillProvince);
  // 趋势图容器 ref
  const trendChartRef = useRef<HTMLDivElement | null>(null);
  const trendChartInstanceRef = useRef<echarts.ECharts | null>(null);

  // 保持 ref 与最新的回调和数据同步
  useEffect(() => {
    handleProvinceClickRef.current = handleProvinceClick;
    handleCityScatterClickRef.current = handleCityScatterClick;
    drillCityDataRef.current = drillCityData;
    handleBackToNationalRef.current = handleBackToNational;
    drillProvinceRef.current = drillProvince;
  });

  // 初始化 ECharts 实例并绑定事件（仅在 mapReady 后执行一次）
  useEffect(() => {
    if (!mapReady || !chartContainerRef.current) return;
    // 若已有实例，先销毁
    if (chartInstanceRef.current) {
      chartInstanceRef.current.dispose();
    }
    const instance = echarts.init(chartContainerRef.current);
    chartInstanceRef.current = instance;
    // 确保容器尺寸正确后再渲染
    requestAnimationFrame(() => {
      if (chartInstanceRef.current === instance) {
        instance.resize();
      }
    });

    // 绑定点击事件
    const clickHandler = (params: any) => {
      const name: string = params.name;
      const seriesType: string = params.seriesType;
      const data: { disease?: string } | undefined = params.data;
      console.log('[MapClick] params:', { name, componentType: params.componentType, seriesType });
      // 散点图点击：城市详情
      if (seriesType === 'scatter') {
        const clickedDisease = data?.disease || '';
        const cityItem = drillCityDataRef.current.find(
          (d) => d.city === name && (d.disease || '') === clickedDisease
        );
        if (cityItem) handleCityScatterClickRef.current(cityItem);
        return;
      }
      // 地图点击：省份详情
      const entry = Object.entries(PROVINCE_GEOJSON_NAME).find(([, geoName]) => geoName === name);
      const shortName = entry ? entry[0] : name;
      console.log('[MapClick] shortName:', shortName);
      if (shortName) {
        handleProvinceClickRef.current(shortName);
      } else if (drillProvinceRef.current) {
        // 点击空白区域（非有效省份）：下钻模式下返回全国视图
        handleBackToNationalRef.current();
      }
    };
    instance.on('click', clickHandler);
    // 临时暴露到 window 用于自动化测试（调试用，可删除）
    (window as any).__mapClickHandler = clickHandler;

    // 窗口大小变化时自适应
    const handleResize = () => instance.resize();
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      instance.dispose();
      chartInstanceRef.current = null;
    };
  }, [mapReady]); // 只在 mapReady 变化时重新初始化

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
      .filter((d): d is MapDataPoint & { province: string } => !!d.province && !!PROVINCE_GEOJSON_NAME[d.province!])
      .map((d) => ({
        name: PROVINCE_GEOJSON_NAME[d.province],
        value: Number(d.weighted_positivity) || 0,
      }));

    // 地图中心点：下钻到省份时聚焦该省
    const provinceCenter: Record<string, [number, number]> = {
      '北京': [116.4, 39.9], '天津': [117.2, 39.1], '河北': [114.5, 38.0],
      '山西': [112.5, 37.9], '内蒙古': [111.8, 40.8], '辽宁': [123.4, 41.8],
      '吉林': [125.3, 43.8], '黑龙江': [126.5, 45.8], '上海': [121.5, 31.2],
      '江苏': [118.8, 32.1], '浙江': [120.2, 30.3], '安徽': [117.2, 31.8],
      '福建': [119.3, 26.1], '江西': [115.9, 28.7], '山东': [117.1, 36.7],
      '河南': [113.6, 34.7], '湖北': [114.3, 30.6], '湖南': [112.9, 28.2],
      '广东': [113.3, 23.1], '广西': [108.4, 22.8], '海南': [110.2, 20.0],
      '重庆': [106.6, 29.6], '四川': [104.1, 30.6], '贵州': [106.6, 26.6],
      '云南': [102.8, 24.9], '西藏': [91.2, 29.7], '陕西': [108.9, 34.3],
      '甘肃': [103.8, 36.1], '青海': [101.8, 36.6], '宁夏': [106.2, 38.5],
      '新疆': [87.6, 43.8], '台湾': [121.5, 25.0], '香港': [114.2, 22.3],
      '澳门': [113.5, 22.2],
    };
    const center = drillProvince && provinceCenter[drillProvince]
      ? provinceCenter[drillProvince]
      : [105.0, 35.0];
    const zoom = drillProvince ? 6 : 1.2;

    // 城市级散点数据
    const scatterData = drillCityData
      .filter((d) => d.longitude != null && d.latitude != null && d.weighted_positivity != null)
      .map((d) => ({
        name: d.city,
        disease: d.disease || '',
        value: [d.longitude, d.latitude, Number(d.weighted_positivity)],
        point_count: d.point_count,
        total_sample: d.total_sample,
      }));

    const valueLabel = dataType === 'gmc' ? 'GMC' : '阳性率';
    const valueUnit = dataType === 'gmc' ? ' μg/ml' : '%';

    const series: any[] = [
      {
        type: 'map',
        map: 'china',
        geoIndex: 0,
        data: seriesData,
        animationDuration: 500,
        animationEasing: 'cubicOut',
      },
    ];

    // 下钻模式：添加城市散点
    if (scatterData.length > 0) {
      series.push({
        type: 'scatter',
        coordinateSystem: 'geo',
        data: scatterData,
        symbolSize: (val: number[]) => {
          const rate = val[2] || 0;
          // 根据阳性率大小决定散点大小（8-28px）
          return Math.max(8, Math.min(28, rate / 5));
        },
        label: {
          show: true,
          formatter: (params: { name: string }) => params.name,
          position: 'right',
          fontSize: 10,
          color: '#333',
          textBorderColor: '#fff',
          textBorderWidth: 2,
        },
        labelLayout: { hideOverlap: true },
        emphasis: {
          label: { show: true, fontSize: 12, fontWeight: 'bold' },
          itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.5)' },
        },
        itemStyle: {
          color: (params: { value: number[] }) => {
            const rate = params.value[2] || 0;
            const stops = colorStops;
            let color = stops[0].color;
            for (let i = stops.length - 1; i >= 0; i--) {
              if (rate >= stops[i].min) {
                color = stops[i].color;
                break;
              }
            }
            return color;
          },
          borderColor: '#fff',
          borderWidth: 1,
          opacity: 0.85,
        },
        tooltip: {
          formatter: (params: { name: string; value: number[]; data: { point_count?: number; total_sample?: number; disease?: string } }) => {
            const diseaseLabel = params.data.disease ? `<br/>疾病: ${diseaseToCn(params.data.disease)}` : '';
            return `<b>${params.name}</b>${diseaseLabel}<br/>
              ${valueLabel}: ${params.value[2] != null ? (params.value[2] as number).toFixed(2) + valueUnit : '-'}<br/>
              数据点数: ${params.data.point_count ?? 0}<br/>
              总样本量: ${(params.data.total_sample ?? 0).toLocaleString()}`;
          },
        },
      });
    }

    return {
      tooltip: {
        trigger: 'item',
        formatter: (params: { name: string; value?: number; componentType?: string }) => {
          // 散点图的 tooltip 由 scatter series 自行处理
          if (params.componentType === 'series') return undefined as any;
          const shortName = nameMap[params.name] || params.name;
          const item = currentData.find((d) => d.province === shortName);
          if (!item) return `${params.name}<br/>暂无数据`;
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
        text: ['高', '低'],
        inRange: { color: colorStops.map((s) => s.color) },
        calculable: true,
        left: 'left',
        bottom: 20,
      },
      geo: {
        map: 'china',
        roam: true,
        center: center as [number, number],
        zoom: zoom,
        label: { show: !drillProvince, fontSize: 10, color: '#333' },
        itemStyle: { areaColor: '#f3f3f3', borderColor: '#ccc' },
        emphasis: { itemStyle: { areaColor: '#a6c84c' } },
        regions: currentData
          .filter((d): d is MapDataPoint & { province: string } => !!d.province && !!PROVINCE_GEOJSON_NAME[d.province!])
          .map((d) => ({
            name: PROVINCE_GEOJSON_NAME[d.province],
          })),
      },
      series,
    };
  };

  // 省份历年趋势图配置
  const getTrendOption = () => {
    const tableData = provinceYearly.map((y) => {
      const item = y.data.find((d) => d.province === selectedProvince);
      return {
        year: y.year,
        value: item?.weighted_positivity ?? null,
      };
    });
    if (tableData.length === 0) return {};
    const valueLabel = dataType === 'gmc' ? 'GMC' : '阳性率';
    const unit = dataType === 'gmc' ? ' μg/ml' : '%';
    return {
      tooltip: {
        trigger: 'axis',
        formatter: (params: Array<{ axisValue: string; data: number | null }>) =>
          `${params[0].axisValue}年<br/>${valueLabel}: ${params[0].data != null ? params[0].data.toFixed(2) + unit : '无数据'}`,
      },
      grid: { left: 35, right: 10, top: 10, bottom: 25 },
      xAxis: {
        type: 'category',
        data: tableData.map((d) => String(d.year)),
        axisLabel: { fontSize: 9, interval: Math.floor(tableData.length / 5) },
      },
      yAxis: {
        type: 'value',
        axisLabel: { fontSize: 9, formatter: (v: number) => v + (dataType === 'gmc' ? '' : '%') },
        scale: true,
      },
      series: [{
        type: 'line',
        data: tableData.map((d) => d.value),
        smooth: true,
        symbol: 'circle',
        symbolSize: 5,
        lineStyle: { width: 2, color: '#1890ff' },
        itemStyle: { color: '#1890ff' },
        areaStyle: { color: 'rgba(24,144,255,0.1)' },
      }],
    };
  };

  // 当数据变化时更新图表 option
  useEffect(() => {
    const instance = chartInstanceRef.current;
    if (!instance || !mapReady) return;
    instance.setOption(getOption(), true);
  }, [mapReady, currentData, drillProvince, drillCityData, dataType, dynamicMode, selectedYear]);

  // 趋势图管理
  useEffect(() => {
    if (!trendChartRef.current) return;
    if (!trendChartInstanceRef.current) {
      trendChartInstanceRef.current = echarts.init(trendChartRef.current);
    }
    const trendOption = getTrendOption();
    if (Object.keys(trendOption).length > 0) {
      trendChartInstanceRef.current.setOption(trendOption, true);
    }
    return () => {
      if (trendChartInstanceRef.current) {
        trendChartInstanceRef.current.dispose();
        trendChartInstanceRef.current = null;
      }
    };
  }, [provinceYearly, selectedProvince, dataType]);

  const totalPoints = currentData.reduce((s, d) => s + d.point_count, 0);
  const totalProvinces = currentData.length;
  const totalSample = currentData.reduce((s, d) => s + d.total_sample, 0);

  // 当前选中省份在 currentData 中的数据
  const currentProvinceData = selectedProvince
    ? currentData.find((d) => d.province === selectedProvince)
    : null;

  // 省份历年趋势数据（扁平化为表格数据源）
  const provinceYearlyTableData = provinceYearly.map((y) => {
    const item = y.data.find((d) => d.province === selectedProvince);
    return {
      key: `${y.year}-${item?.disease || ''}`,
      year: y.year,
      disease: diseaseToCn(item?.disease || disease),
      value: item?.weighted_positivity ?? null,
      point_count: item?.point_count ?? 0,
      total_sample: item?.total_sample ?? 0,
    };
  });

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
            <Select
              mode="multiple"
              value={occupation}
              onChange={setOccupation}
              style={{ width: 180 }}
              placeholder="搜索职业（人群）"
              showSearch
              allowClear
              maxTagCount={2}
              filterOption={(input, option) =>
                (option?.label as string || '').toLowerCase().includes(input.toLowerCase())
              }
              options={populationOptions.map((p) => ({ value: p, label: p }))}
            />
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
          <Col>
            <Button icon={<DownloadOutlined />} onClick={() => {
              const params = new URLSearchParams();
              if (disease) params.set('disease', disease);
              if (dataType) params.set('data_type', dataType);
              if (province) params.set('province', province);
              if (yearStart) params.set('year_start', String(yearStart));
              if (yearEnd) params.set('year_end', String(yearEnd));
              if (ageMin != null) params.set('age_min', String(ageMin));
              if (ageMax != null) params.set('age_max', String(ageMax));
              if (gender) params.set('gender', gender);
              if (occupation.length > 0) params.set('occupation', occupation.join(','));
              window.open(`/api/v1/map/export-data-points?${params.toString()}`);
            }}>
              导出 CSV
            </Button>
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
                {drillProvince && (
                  <Button size="small" type="text" icon={<CompassOutlined />} onClick={handleBackToNational}>重置地图</Button>
                )}
              </Space>
            }
          >
            {mapReady ? (
              <div ref={chartContainerRef} style={{ height: 520, width: '100%' }} />
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
                    marks={(() => {
                      const total = yearlyData.length;
                      // 根据年份数量自动计算标记间隔，避免标签重叠
                      let interval: number;
                      if (total <= 10) interval = 1;
                      else if (total <= 20) interval = 2;
                      else if (total <= 30) interval = 3;
                      else interval = 5;
                      const marks: Record<number, string> = {};
                      yearlyData.forEach((y, i) => {
                        // 首尾年份或间隔倍数时显示标记
                        if (i === 0 || i === total - 1 || i % interval === 0) {
                          marks[y.year] = String(y.year);
                        }
                      });
                      return marks;
                    })()}
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
          <Card
            title={
              <Space>
                {selectedProvince && (
                  <Button size="small" type="text" icon={<ArrowLeftOutlined />} onClick={() => setSelectedProvince(null)} />
                )}
                <span>{selectedProvince ? `${selectedProvince} 详情` : (dynamicMode === 'timeline' && selectedYear ? `${selectedYear}年 省份列表` : '省份列表')}</span>
              </Space>
            }
            style={{ height: '100%' }}
          >
            {selectedProvince ? (
              <Spin spinning={provinceDetailLoading}>
                {/* 疾病信息 */}
                {disease && (
                  <div style={{ marginBottom: 12, padding: '4px 8px', background: '#e6f7ff', borderRadius: 4, fontSize: 13, color: '#1890ff' }}>
                    疾病: <strong>{disease}</strong>
                  </div>
                )}

                {/* 当前指标统计 */}
                {currentProvinceData && (
                  <Row gutter={8} style={{ marginBottom: 12 }}>
                    <Col span={12}>
                      <Statistic
                        title={dataType === 'gmc' ? 'GMC' : '加权阳性率'}
                        value={currentProvinceData.weighted_positivity != null ? Number(currentProvinceData.weighted_positivity).toFixed(2) : '-'}
                        suffix={dataType === 'gmc' ? ' μg/ml' : '%'}
                        valueStyle={{ fontSize: 18 }}
                      />
                    </Col>
                    <Col span={12}>
                      <Statistic title="总样本量" value={currentProvinceData.total_sample} valueStyle={{ fontSize: 18 }} />
                    </Col>
                  </Row>
                )}
                {currentProvinceData && (
                  <Row gutter={8} style={{ marginBottom: 12 }}>
                    <Col span={12}><span style={{ fontSize: 12, color: '#888' }}>数据点: {currentProvinceData.point_count}</span></Col>
                    <Col span={12}><span style={{ fontSize: 12, color: '#888' }}>研究数: {currentProvinceData.study_count}</span></Col>
                  </Row>
                )}

                {/* 历年趋势图 */}
                {provinceYearlyTableData.length > 0 && (
                  <div style={{ marginBottom: 12 }}>
                    <div style={{ fontSize: 12, fontWeight: 'bold', color: '#666', marginBottom: 4 }}>历年趋势</div>
                    <div ref={trendChartRef} style={{ height: 120 }} />
                  </div>
                )}

                {/* 历年数据表 */}
                {provinceYearlyTableData.length > 0 && (
                  <div style={{ marginBottom: 12 }}>
                    <div style={{ fontSize: 12, fontWeight: 'bold', color: '#666', marginBottom: 4 }}>历年数据</div>
                    <Table
                      dataSource={provinceYearlyTableData}
                      rowKey="key"
                      size="small"
                      pagination={false}
                      scroll={{ y: 120 }}
                      columns={[
                        { title: '年份', dataIndex: 'year', key: 'year', width: 50 },
                        { title: '疾病', dataIndex: 'disease', key: 'disease', width: 80, ellipsis: true },
                        {
                          title: dataType === 'gmc' ? 'GMC' : '阳性率',
                          dataIndex: 'value',
                          key: 'value',
                          width: 70,
                          render: (v: number | null) => (v != null ? Number(v).toFixed(2) + (dataType === 'gmc' ? '' : '%') : '-'),
                        },
                        { title: '样本', dataIndex: 'total_sample', key: 'total_sample', width: 55 },
                      ]}
                    />
                  </div>
                )}

                {/* 城市分布 */}
                {provinceCities.length > 0 && (
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 'bold', color: '#666', marginBottom: 4 }}>城市分布</div>
                    <Table
                      dataSource={provinceCities}
                      rowKey={(r: MapDataPoint) => `${r.city}-${r.disease || ''}`}
                      size="small"
                      pagination={false}
                      scroll={{ y: 120 }}
                      columns={[
                        { title: '城市', dataIndex: 'city', key: 'city', width: 70 },
                        { title: '疾病', dataIndex: 'disease', key: 'disease', width: 80, ellipsis: true, render: (v: string) => diseaseToCn(v) },
                        {
                          title: dataType === 'gmc' ? 'GMC' : '阳性率',
                          dataIndex: 'weighted_positivity',
                          key: 'wp',
                          width: 65,
                          render: (v: number | null) => (v != null ? Number(v).toFixed(2) + (dataType === 'gmc' ? '' : '%') : '-'),
                        },
                        { title: '数据点', dataIndex: 'point_count', key: 'pc', width: 50 },
                      ]}
                    />
                  </div>
                )}

                {/* 无数据提示 */}
                {!provinceDetailLoading && provinceYearlyTableData.length === 0 && provinceCities.length === 0 && (
                  <div style={{ textAlign: 'center', color: '#999', padding: '20px 0' }}>该省份暂无详细数据</div>
                )}
              </Spin>
            ) : (
              <>
                <div style={{ marginBottom: 8, fontSize: 12, color: '#999' }}>💡 点击地图省份查看详细信息</div>
                <Table
                  dataSource={currentData}
                  rowKey="province"
                  size="small"
                  pagination={false}
                  scroll={{ y: 420 }}
                  onRow={(record) => ({
                    onClick: () => record.province && handleProvinceClick(record.province),
                    style: { cursor: 'pointer' },
                  })}
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
              </>
            )}
          </Card>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={8}>
          <Card>
            <Statistic
              title="总数据点数"
              value={summaryData?.point_count ?? totalPoints}
              valueStyle={{ color: '#52c41a' }}
            />
            {summaryData && summaryData.unapproved_point_count > 0 && (
              <div style={{ fontSize: 13, color: '#fa8c16', marginTop: 4 }}>
                未审核：{summaryData.unapproved_point_count}
              </div>
            )}
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="覆盖省份数"
              value={summaryData?.province_count ?? totalProvinces}
              valueStyle={{ color: '#52c41a' }}
            />
            {summaryData && summaryData.unapproved_province_count > 0 && (
              <div style={{ fontSize: 13, color: '#fa8c16', marginTop: 4 }}>
                未审核覆盖：{summaryData.unapproved_province_count}
              </div>
            )}
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="总样本量"
              value={summaryData?.total_sample ?? totalSample}
              formatter={(v) => Number(v).toLocaleString()}
              valueStyle={{ color: '#52c41a' }}
            />
            {summaryData && summaryData.unapproved_total_sample > 0 && (
              <div style={{ fontSize: 13, color: '#fa8c16', marginTop: 4 }}>
                未审核：{summaryData.unapproved_total_sample.toLocaleString()}
              </div>
            )}
          </Card>
        </Col>
      </Row>

      {/* 城市详情弹窗 */}
      <Modal
        title={cityDetailData ? `${cityDetailData.city} 详情` : '城市详情'}
        open={cityDetailOpen}
        onCancel={() => setCityDetailOpen(false)}
        footer={null}
        width={400}
      >
        {cityDetailData && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="城市">{cityDetailData.city}</Descriptions.Item>
            <Descriptions.Item label="疾病">{diseaseToCn(cityDetailData.disease || disease) || '-'}</Descriptions.Item>
            <Descriptions.Item label="省份">{drillProvince || '-'}</Descriptions.Item>
            <Descriptions.Item label={dataType === 'gmc' ? 'GMC' : '加权阳性率'}>
              {cityDetailData.weighted_positivity != null
                ? Number(cityDetailData.weighted_positivity).toFixed(2) + (dataType === 'gmc' ? ' μg/ml' : '%')
                : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="数据点数">{cityDetailData.point_count}</Descriptions.Item>
            <Descriptions.Item label="研究数">{cityDetailData.study_count}</Descriptions.Item>
            <Descriptions.Item label="总样本量">{cityDetailData.total_sample.toLocaleString()}</Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </Spin>
  );
};

export default MapOverview;
