import React, { useState, useCallback, useEffect } from 'react';
import { Card, Row, Col, Spin, Empty, message, Button, Tabs, Table, Space, Statistic, Alert, Tag, Collapse, Tooltip, Progress, Select, Segmented, Radio, Modal, Descriptions } from 'antd';
import { SearchOutlined, WarningOutlined, CheckCircleOutlined, FileSearchOutlined, DownloadOutlined, ExperimentOutlined, SafetyCertificateOutlined, BarChartOutlined, FundOutlined, AimOutlined, DashboardOutlined, EnvironmentOutlined, LineChartOutlined } from '@ant-design/icons';
import ReactECharts from '../components/EChart';
import ChartWithSnapshot from '../components/ChartWithSnapshot';
import * as echarts from '../lib/echarts';
import DiseaseSelector from '../components/DiseaseSelector';
import ProvinceSelector from '../components/ProvinceSelector';
import MapSelector from '../components/MapSelector';
import AdvancedCharts from '../components/AdvancedCharts';
import KpiCards from '../components/KpiCards';
import EquityRadar from '../components/EquityRadar';
import QualityPanel from '../components/QualityPanel';
import TrendWithCI from '../components/TrendWithCI';
import AgeCurveChart from '../components/AgeCurveChart';
import TopBottomRank from '../components/TopBottomRank';
import GoalTrackingChart from '../components/GoalTrackingChart';
import SimulationPanel from '../components/SimulationPanel';
import CoverageReviewTable from '../components/CoverageReviewTable';
import CoverageReviewChart from '../components/CoverageReviewChart';
import { getTrend, getRegionCompare, getAgeStratify, getApprovedDataPoints, getDataGapAnalysis, getFoiHerdImmunity, getVaccineEffectivenessCoverage, getEquityAnalysis, getQualityAssessment, getGoalTracking, getAgeCurve, getMetaMerge, getMetaAnalysis, getAssayHeterogeneity, getSimulation, getProvinceData, fetchCoverageReview, getBirthCohort } from '../services/map';
import { useFilterStore } from '../store';
import type { TableRowSelection } from 'antd/es/table/interface';
import type { DataGapAnalysisResult, DataGapItem, ProvinceYearRow, FoiHerdImmunityResult, VaccineEffectivenessCoverageResult, FoiProvinceMatrixRow, VaccineProvinceMatrixRow, FoiPerDiseaseResult, VaccinePerDiseaseResult, EquityAnalysisResponse, QualityAssessmentResponse, GoalTrackingResponse, AgeCurveResponse, MetaMergeResponse, AssayHeterogeneityResponse, SimulationResponse, MapDataPoint, MetaMergeProvinceResult, AssayHeterogeneityRow, HeterogeneityLevel, CoverageReviewResult, MetaAnalysisResponse, MetaAnalysisGroup, BirthCohortResponse } from '../types';
import { DISEASES, PROVINCE_GEOJSON_NAME } from '../utils/constants';
import { lineWithBand, barWithError, forestPlotOption, funnelPlotOption, wilsonCi, ftTransform, birthCohortHeatmapOption, birthCohortLinesOption } from '../utils/chartBuilders';

type DataItem = Record<string, unknown>;

type TrendSignificance = {
  slope_per_year: number | null;
  p_value: number | null;
  r_squared: number | null;
  direction: 'increasing' | 'decreasing' | 'flat' | null;
  n: number;
};

type TrendTest = {
  z: number;
  p_value: number;
  direction: 'increasing' | 'decreasing' | 'flat';
  direction_label: '上升' | '下降' | '不显著';
};

type ComparisonTest = {
  province_a?: string;
  province_b?: string;
  p1: number;
  p2: number;
  n1: number;
  n2: number;
  rd: number;
  rd_ci_lower: number;
  rd_ci_upper: number;
  rr: number | null;
  rr_ci_lower: number | null;
  rr_ci_upper: number | null;
  z: number;
  p_value: number;
  significant: boolean;
  conclusion: string;
};

type RegionRateView = 'crude' | 'asr';

// 从任意分析响应中安全提取快照 token（响应 meta.snapshot_token）
const tokenOf = (d: unknown): string | null =>
  ((d as { meta?: { snapshot_token?: string } })?.meta?.snapshot_token) ?? null;

const Analysis: React.FC = () => {
  const { disease: globalDisease, dataType: globalDataType, setDisease, setDataType } = useFilterStore();

  // 本地筛选状态
  const [localDisease, setLocalDisease] = useState(globalDisease);
  const [localDataType, setLocalDataType] = useState(globalDataType);
  const [province, setProvince] = useState<string[]>([]);

  // 实际查询参数
  const [appliedDisease, setAppliedDisease] = useState('');
  const [appliedDataType, setAppliedDataType] = useState('');
  const [appliedProvinces, setAppliedProvinces] = useState<string[]>([]);

  const [loading, setLoading] = useState(false);
  const [trendData, setTrendData] = useState<DataItem[]>([]);
  const [trendSignificance, setTrendSignificance] = useState<TrendSignificance | null>(null);
  const [trendTest, setTrendTest] = useState<TrendTest | null>(null);
  const [regionData, setRegionData] = useState<DataItem[]>([]);
  const [comparisonTest, setComparisonTest] = useState<ComparisonTest | null>(null);
  const [regionRateView, setRegionRateView] = useState<RegionRateView>('crude');
  const [pairModalVisible, setPairModalVisible] = useState(false);
  const [ageData, setAgeData] = useState<DataItem[]>([]);

  // 审核通过的数据点
  const [approvedData, setApprovedData] = useState<DataItem[]>([]);
  const [approvedTotal, setApprovedTotal] = useState(0);
  const [approvedLoading, setApprovedLoading] = useState(false);
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [selectedRows, setSelectedRows] = useState<DataItem[]>([]);
  const [activeTab, setActiveTab] = useState('summary');
  // 各分析模块的快照 token（来自响应 meta.snapshot_token）
  const [snapshotTokens, setSnapshotTokens] = useState<Record<string, string | null>>({});
  const [dpPage, setDpPage] = useState(1);
  const [dpPageSize, setDpPageSize] = useState(50);
  const [dpSortBy, setDpSortBy] = useState<string | undefined>(undefined);
  const [dpSortOrder, setDpSortOrder] = useState<string | undefined>(undefined);

  // 数据覆盖度分析
  const [gapData, setGapData] = useState<DataGapAnalysisResult | null>(null);
  // 审核状态统计（按疾病）
  const [coverageReview, setCoverageReview] = useState<CoverageReviewResult | null>(null);
  const [coverageReviewLoading, setCoverageReviewLoading] = useState(false);
  const [coverageReviewDisease, setCoverageReviewDisease] = useState('');
  const [gapLoading, setGapLoading] = useState(false);

  // FOI（感染力）+ 群体免疫阈值分析
  const [foiData, setFoiData] = useState<FoiHerdImmunityResult | null>(null);
  const [foiLoading, setFoiLoading] = useState(false);
  const [foiSelectedDisease, setFoiSelectedDisease] = useState<string>('');

  // 疫苗效果 VE + 接种率分析
  const [vaccineData, setVaccineData] = useState<VaccineEffectivenessCoverageResult | null>(null);
  const [vaccineLoading, setVaccineLoading] = useState(false);
  const [vaccineSelectedDisease, setVaccineSelectedDisease] = useState<string>('');

  // ===================== 公平性 / 数据质量 / 目标达成 / 高级分析 =====================

  // 中国地图（geo）是否就绪
  const [mapReady, setMapReady] = useState(false);

  // 公平性分析
  const [equityData, setEquityData] = useState<EquityAnalysisResponse | null>(null);
  const [equityLoading, setEquityLoading] = useState(false);

  // 数据质量（全库）
  const [qualityData, setQualityData] = useState<QualityAssessmentResponse | null>(null);
  const [qualityLoading, setQualityLoading] = useState(false);

  // 目标达成追踪
  const [goalData, setGoalData] = useState<GoalTrackingResponse | null>(null);
  const [goalLoading, setGoalLoading] = useState(false);

  // 高级分析：年龄曲线 / meta / assay / 模拟
  const [ageCurveData, setAgeCurveData] = useState<AgeCurveResponse | null>(null);
  const [ageCurveLoading, setAgeCurveLoading] = useState(false);
  const [metaData, setMetaData] = useState<MetaMergeResponse | null>(null);
  const [metaLoading, setMetaLoading] = useState(false);
  const [metaAnalysisData, setMetaAnalysisData] = useState<MetaAnalysisResponse | null>(null);
  const [metaAnalysisLoading, setMetaAnalysisLoading] = useState(false);
  const [metaGroupBy, setMetaGroupBy] = useState<string>('');
  // 出生队列：birth_year = collection_year − age_mid，按十年段分桶
  const [birthCohortData, setBirthCohortData] = useState<BirthCohortResponse | null>(null);
  const [birthCohortLoading, setBirthCohortLoading] = useState(false);
  const [assayData, setAssayData] = useState<AssayHeterogeneityResponse | null>(null);
  const [assayLoading, setAssayLoading] = useState(false);
  const [simData, setSimData] = useState<SimulationResponse | null>(null);
  const [simLoading, setSimLoading] = useState(false);
  const [simCoverage, setSimCoverage] = useState(90);
  const [simBooster, setSimBooster] = useState(0);

  // 地图钻取：选中的省份及其联动数据（TrendWithCI / AgeCurveChart / QualityPanel）
  const [drillProvince, setDrillProvince] = useState<string | null>(null);
  const [drillTrend, setDrillTrend] = useState<Array<{ year: number; value: number | null; ci_lower: number | null; ci_upper: number | null }>>([]);
  const [drillAgeCurve, setDrillAgeCurve] = useState<AgeCurveResponse | null>(null);
  const [drillQuality, setDrillQuality] = useState<QualityAssessmentResponse | null>(null);
  const [drillLoading, setDrillLoading] = useState(false);

  // 地图省份着色数据
  const [mapData, setMapData] = useState<MapDataPoint[]>([]);
  const [mapLoading, setMapLoading] = useState(false);

  const fetchAll = useCallback(async () => {
    if (!appliedDisease && !appliedDataType && appliedProvinces.length === 0) return;
    setLoading(true);
    try {
      const params: Record<string, unknown> = {};
      if (appliedDisease) params.disease = appliedDisease;
      if (appliedDataType) params.data_type = appliedDataType;
      if (appliedProvinces.length > 0) params.province = appliedProvinces.join(',');

      const [trend, region, age] = await Promise.all([
        getTrend(params),
        getRegionCompare(params),
        getAgeStratify(params),
      ]);
      const trendResp = (trend as { trend: DataItem[]; trend_significance?: TrendSignificance; trend_test?: TrendTest } | null) || null;
      setTrendData(trendResp?.trend || []);
      setTrendSignificance(trendResp?.trend_significance || null);
      setTrendTest(trendResp?.trend_test || null);
      const regionResp = (region as { regions?: DataItem[]; comparison_test?: ComparisonTest | null } | null) || null;
      const regionList = Array.isArray(region) ? (region as DataItem[]) : (regionResp?.regions || []);
      setRegionData(regionList);
      setComparisonTest(regionResp?.comparison_test || null);
      const ageResp = (age as { age_groups?: DataItem[] } | null) || null;
      setAgeData((Array.isArray(age) ? (age as DataItem[]) : (ageResp?.age_groups || [])));
      // 记录各模块快照 token（供图表卡片引用/水印使用）
      setSnapshotTokens({
        trend: ((trend as { meta?: { snapshot_token?: string } })?.meta?.snapshot_token) ?? null,
        region: ((region as { meta?: { snapshot_token?: string } })?.meta?.snapshot_token) ?? null,
        age: ((age as { meta?: { snapshot_token?: string } })?.meta?.snapshot_token) ?? null,
      });
    } catch (err) {
      console.error('[Analysis] 数据加载失败:', err);
      message.error('数据加载失败');
    } finally {
      setLoading(false);
    }
  }, [appliedDisease, appliedDataType, appliedProvinces]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // 获取数据覆盖度分析
  const fetchGapData = useCallback(async () => {
    setGapLoading(true);
    try {
      const params: Record<string, unknown> = {};
      if (appliedDisease) params.disease = appliedDisease;
      const data = await getDataGapAnalysis(Object.keys(params).length > 0 ? params : undefined);
      setGapData(data);
    } catch (err) {
      console.error('[Analysis] 数据覆盖度分析加载失败:', err);
      message.error('数据覆盖度分析加载失败');
    } finally {
      setGapLoading(false);
    }
  }, [appliedDisease]);

  useEffect(() => {
    if (activeTab === 'coverage') {
      fetchGapData();
    }
  }, [activeTab, fetchGapData]);

  // 获取审核状态统计（按疾病）
  const fetchCoverageReviewData = useCallback(async () => {
    setCoverageReviewLoading(true);
    try {
      const params: Record<string, unknown> = {};
      if (coverageReviewDisease) params.disease = coverageReviewDisease;
      const data = await fetchCoverageReview(Object.keys(params).length > 0 ? params : undefined);
      setCoverageReview(data);
    } catch (err) {
      console.error('[Analysis] 审核状态统计加载失败:', err);
      message.error('审核状态统计加载失败');
    } finally {
      setCoverageReviewLoading(false);
    }
  }, [coverageReviewDisease]);

  useEffect(() => {
    if (activeTab === 'coverage') {
      fetchCoverageReviewData();
    }
  }, [activeTab, fetchCoverageReviewData]);

  // 获取 FOI 感染力 + 群体免疫阈值分析
  const fetchFoiData = useCallback(async () => {
    setFoiLoading(true);
    try {
      const params: Record<string, unknown> = {};
      if (appliedDisease) params.disease = appliedDisease;
      if (appliedProvinces.length > 0) params.province = appliedProvinces.join(',');
      const data = await getFoiHerdImmunity(params);
      setFoiData(data);
      // 默认选中第一个疾病
      const results = data.per_disease_results || [];
      if (results.length > 0 && !foiSelectedDisease) {
        setFoiSelectedDisease(results[0].disease);
      }
    } catch (err) {
      console.error('[Analysis] FOI分析加载失败:', err);
      message.error('FOI感染力分析加载失败');
    } finally {
      setFoiLoading(false);
    }
  }, [appliedDisease, appliedProvinces]);

  useEffect(() => {
    if (activeTab === 'foi') {
      fetchFoiData();
    }
  }, [activeTab, fetchFoiData]);

  // 获取 疫苗 VE + 接种率综合分析
  const fetchVaccineData = useCallback(async () => {
    setVaccineLoading(true);
    try {
      const params: Record<string, unknown> = {};
      if (appliedDisease) params.disease = appliedDisease;
      if (appliedProvinces.length > 0) params.province = appliedProvinces.join(',');
      const data = await getVaccineEffectivenessCoverage(params);
      setVaccineData(data);
      // 默认选中第一个疾病
      const veResults = data.per_disease_results || [];
      if (veResults.length > 0 && !vaccineSelectedDisease) {
        setVaccineSelectedDisease(veResults[0].disease);
      }
    } catch (err) {
      console.error('[Analysis] 疫苗分析加载失败:', err);
      message.error('疫苗效力与接种率分析加载失败');
    } finally {
      setVaccineLoading(false);
    }
  }, [appliedDisease, appliedProvinces]);

  useEffect(() => {
    if (activeTab === 'vaccine') {
      fetchVaccineData();
    }
  }, [activeTab, fetchVaccineData]);

  // ===================== 公平性 / 数据质量 / 目标达成 / 高级分析：数据加载 =====================

  // 注册中国地图（geo），与 MapOverview 一致，加载一次即可
  useEffect(() => {
    fetch('/china.json')
      .then((r) => r.json())
      .then((data) => {
        echarts.registerMap('china', data);
        setMapReady(true);
      })
      .catch(() => message.error('中国地图数据加载失败'));
  }, []);

  // 地图省份着色数据
  const fetchMapData = useCallback(async () => {
    setMapLoading(true);
    try {
      const params: Record<string, unknown> = {};
      if (appliedDisease) params.disease = appliedDisease;
      if (appliedDataType) params.data_type = appliedDataType;
      const data = await getProvinceData(params);
      setMapData(data || []);
    } catch (err) {
      console.error('[Analysis] 地图数据加载失败:', err);
      setMapData([]);
    } finally {
      setMapLoading(false);
    }
  }, [appliedDisease, appliedDataType]);

  useEffect(() => { fetchMapData(); }, [fetchMapData]);

  // 公平性分析
  const fetchEquity = useCallback(async () => {
    setEquityLoading(true);
    try {
      const params: Record<string, unknown> = {};
      if (appliedDisease) params.disease = appliedDisease;
      const data = await getEquityAnalysis(params);
      setEquityData(data);
    } catch (err) {
      console.error('[Analysis] 公平性分析加载失败:', err);
      message.error('公平性分析加载失败');
    } finally {
      setEquityLoading(false);
    }
  }, [appliedDisease]);

  // 数据质量（全库）
  const fetchQuality = useCallback(async () => {
    setQualityLoading(true);
    try {
      const params: Record<string, unknown> = {};
      if (appliedDisease) params.disease = appliedDisease;
      const data = await getQualityAssessment(params);
      setQualityData(data);
    } catch (err) {
      console.error('[Analysis] 数据质量评估加载失败:', err);
      message.error('数据质量评估加载失败');
    } finally {
      setQualityLoading(false);
    }
  }, [appliedDisease]);

  // 目标达成追踪
  const fetchGoal = useCallback(async () => {
    setGoalLoading(true);
    try {
      const params: Record<string, unknown> = {};
      if (appliedDisease) params.disease = appliedDisease;
      const data = await getGoalTracking(params);
      setGoalData(data);
    } catch (err) {
      console.error('[Analysis] 目标达成追踪加载失败:', err);
      message.error('目标达成追踪加载失败');
    } finally {
      setGoalLoading(false);
    }
  }, [appliedDisease]);

  // 高级分析：年龄曲线（惩罚样条平滑 + 置信带 + FOI）
  const fetchAgeCurve = useCallback(async () => {
    if (!appliedDisease) {
      setAgeCurveData(null);
      return;
    }
    setAgeCurveLoading(true);
    try {
      const params: Record<string, unknown> = { disease: appliedDisease };
      const data = await getAgeCurve(params);
      setAgeCurveData(data);
    } catch (err) {
      console.error('[Analysis] 年龄曲线加载失败:', err);
      message.error('年龄曲线加载失败');
    } finally {
      setAgeCurveLoading(false);
    }
  }, [appliedDisease]);

  // 高级分析：meta 合并
  const fetchMeta = useCallback(async () => {
    setMetaLoading(true);
    try {
      const params: Record<string, unknown> = {};
      if (appliedDisease) params.disease = appliedDisease;
      const data = await getMetaMerge(params);
      setMetaData(data);
    } catch (err) {
      console.error('[Analysis] meta 合并加载失败:', err);
      message.error('meta 合并加载失败');
    } finally {
      setMetaLoading(false);
    }
  }, [appliedDisease]);

  // 证据合成：多文献 Meta 分析（森林图 / 漏斗图）
  const fetchMetaAnalysis = useCallback(async () => {
    if (!appliedDisease) {
      setMetaAnalysisData(null);
      return;
    }
    setMetaAnalysisLoading(true);
    try {
      const params: Record<string, unknown> = { disease: appliedDisease };
      if (metaGroupBy) params.group_by = metaGroupBy;
      const data = await getMetaAnalysis(params);
      setMetaAnalysisData(data);
    } catch (err) {
      console.error('[Analysis] 证据合成加载失败:', err);
      message.error('证据合成加载失败');
    } finally {
      setMetaAnalysisLoading(false);
    }
  }, [appliedDisease, metaGroupBy]);

  // 出生队列：birth_year = collection_year − age_mid，聚合 (十年段, 调查年)
  const fetchBirthCohort = useCallback(async () => {
    if (!appliedDisease) {
      setBirthCohortData(null);
      return;
    }
    setBirthCohortLoading(true);
    try {
      const params: Record<string, unknown> = { disease: appliedDisease };
      if (appliedProvinces.length > 0) params.province = appliedProvinces.join(',');
      const data = await getBirthCohort(params);
      setBirthCohortData(data);
    } catch (err) {
      console.error('[Analysis] 出生队列加载失败:', err);
      message.error('出生队列加载失败');
    } finally {
      setBirthCohortLoading(false);
    }
  }, [appliedDisease, appliedProvinces]);

  // 高级分析：assay 异质性
  const fetchAssay = useCallback(async () => {
    setAssayLoading(true);
    try {
      const params: Record<string, unknown> = {};
      if (appliedDisease) params.disease = appliedDisease;
      const data = await getAssayHeterogeneity(params);
      setAssayData(data);
    } catch (err) {
      console.error('[Analysis] assay 异质性加载失败:', err);
      message.error('assay 异质性分析加载失败');
    } finally {
      setAssayLoading(false);
    }
  }, [appliedDisease]);

  // 高级分析：免疫屏障模拟
  const fetchSimulation = useCallback(async (coverage: number, booster: number) => {
    setSimLoading(true);
    try {
      const params: Record<string, unknown> = { assumed_coverage: coverage, booster_rate: booster };
      if (appliedDisease) params.disease = appliedDisease;
      const data = await getSimulation(params);
      setSimData(data);
    } catch (err) {
      console.error('[Analysis] 免疫屏障模拟加载失败:', err);
      message.error('免疫屏障模拟加载失败');
    } finally {
      setSimLoading(false);
    }
  }, [appliedDisease]);

  // 地图钻取：加载选中省的 趋势(带CI) + 年龄曲线 + 数据质量
  const fetchDrillDown = useCallback(async (prov: string) => {
    setDrillLoading(true);
    try {
      const base: Record<string, unknown> = { province: prov };
      if (appliedDisease) base.disease = appliedDisease;
      const [trend, quality, age] = await Promise.all([
        getTrend({ ...base, data_type: 'seroprevalence' }),
        getQualityAssessment(base),
        // 年龄曲线端点要求必传 disease；未选疾病时跳过
        appliedDisease ? getAgeCurve({ ...base }) : Promise.resolve(null),
      ]);
      const trendItems = (trend as { trend: Array<{ year: number; weighted_positivity: number | null; positivity_ci_lower: number | null; positivity_ci_upper: number | null }> }).trend || [];
      setDrillTrend(trendItems.map((t) => ({
        year: t.year,
        value: t.weighted_positivity,
        ci_lower: t.positivity_ci_lower,
        ci_upper: t.positivity_ci_upper,
      })));
      setDrillAgeCurve(age as AgeCurveResponse | null);
      setDrillQuality(quality);
    } catch (err) {
      console.error('[Analysis] 省份钻取数据加载失败:', err);
      message.error('省份钻取数据加载失败');
    } finally {
      setDrillLoading(false);
    }
  }, [appliedDisease]);

  // 地图省份点击 → 钻取
  const handleProvinceClick = useCallback((params: unknown) => {
    const name = (params as { name?: string })?.name;
    if (!name) return;
    const entry = Object.entries(PROVINCE_GEOJSON_NAME).find(([, geoName]) => geoName === name);
    const shortName = entry ? entry[0] : name;
    if (!shortName || shortName === '台湾' || shortName === '香港' || shortName === '澳门') return;
    setDrillProvince(shortName);
    fetchDrillDown(shortName);
  }, [fetchDrillDown]);

  // Tab 切换时加载对应数据
  useEffect(() => {
    if (activeTab === 'equity') fetchEquity();
  }, [activeTab, fetchEquity]);

  useEffect(() => {
    if (activeTab === 'quality') fetchQuality();
  }, [activeTab, fetchQuality]);

  useEffect(() => {
    if (activeTab === 'goal') fetchGoal();
  }, [activeTab, fetchGoal]);

  useEffect(() => {
    if (activeTab === 'advancedAnalysis' || activeTab === 'ageCurve') fetchAgeCurve();
  }, [activeTab, fetchAgeCurve]);

  useEffect(() => {
    if (activeTab === 'advancedAnalysis') {
      fetchMeta();
      fetchAssay();
    }
  }, [activeTab, fetchMeta, fetchAssay]);

  useEffect(() => {
    if (activeTab === 'metaAnalysis') fetchMetaAnalysis();
  }, [activeTab, fetchMetaAnalysis]);

  useEffect(() => {
    if (activeTab === 'birthCohort') fetchBirthCohort();
  }, [activeTab, fetchBirthCohort]);

  // 获取审核通过的数据点
  const fetchApprovedData = useCallback(async (page: number, pageSize: number, sortBy?: string, sortOrder?: string) => {
    setApprovedLoading(true);
    try {
      const params: Record<string, unknown> = {
        offset: (page - 1) * pageSize,
        limit: pageSize,
      };
      if (appliedDisease) params.disease = appliedDisease;
      if (appliedDataType) params.data_type = appliedDataType;
      if (appliedProvinces.length > 0) params.province = appliedProvinces.join(',');
      if (sortBy) { params.sort_by = sortBy; params.sort_order = sortOrder || 'desc'; }

      const res = await getApprovedDataPoints(params);
      const data = res as { items: DataItem[]; total: number };
      setApprovedData(data.items || []);
      setApprovedTotal(data.total || 0);
      setSnapshotTokens((prev) => ({
        ...prev,
        datapoints: ((res as { meta?: { snapshot_token?: string } })?.meta?.snapshot_token) ?? null,
      }));
    } catch (err) {
      console.error('[Analysis] 数据点加载失败:', err);
      message.error('数据点加载失败');
    } finally {
      setApprovedLoading(false);
    }
  }, [appliedDisease, appliedDataType, appliedProvinces]);

  // 切换到数据点可视化tab时加载
  useEffect(() => {
    if (activeTab === 'datapoints') {
      fetchApprovedData(dpPage, dpPageSize, dpSortBy, dpSortOrder);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, fetchApprovedData, dpPage, dpPageSize, dpSortBy, dpSortOrder]);

  // 确认筛选
  const handleConfirm = () => {
    setDisease(localDisease);
    setDataType(localDataType);
    setAppliedDisease(localDisease);
    setAppliedDataType(localDataType);
    setAppliedProvinces(province);
    // 清除已选数据点
    setSelectedRowKeys([]);
    setSelectedRows([]);
  };

  // ===================== 汇总分析图表 =====================

  const isGmc = appliedDataType === 'gmc';
  const trendValueField = isGmc ? 'avg_gmc' : 'weighted_positivity';
  const trendLoField = isGmc ? 'gmc_ci_lower' : 'positivity_ci_lower';
  const trendHiField = isGmc ? 'gmc_ci_upper' : 'positivity_ci_upper';
  const compareValueField = isGmc ? 'avg_gmc' : 'avg_positivity';
  const compareLoField = isGmc ? 'gmc_ci_lower' : 'positivity_ci_lower';
  const compareHiField = isGmc ? 'gmc_ci_upper' : 'positivity_ci_upper';
  const valueUnit = isGmc ? '' : '%';

  // 趋势：折线 + 置信带
  const trendOption = trendData.length ? lineWithBand(
    '年份趋势',
    trendData.map((d) => (d as { year: number }).year),
    trendData.map((d) => (d[trendValueField] ?? null) as number),
    trendData.map((d) => (d[trendLoField] ?? null) as number),
    trendData.map((d) => (d[trendHiField] ?? null) as number),
    valueUnit,
  ) : null;

  // 区域对比：柱状 + 误差线（粗率 avg_positivity ↔ 标化率 asr）
  const regionValueField = regionRateView === 'asr' ? 'asr' : compareValueField;
  const regionLoField = regionRateView === 'asr' ? 'asr_ci_lower' : compareLoField;
  const regionHiField = regionRateView === 'asr' ? 'asr_ci_upper' : compareHiField;
  const regionOption = regionData.length ? barWithError(
    regionRateView === 'asr' ? '省份年龄标化率（ASR）' : '省份均值对比',
    regionData.map((d) => (d as { province: string }).province),
    regionData.map((d) => (d[regionValueField] ?? null) as number),
    regionData.map((d) => (d[regionLoField] ?? null) as number),
    regionData.map((d) => (d[regionHiField] ?? null) as number),
    valueUnit,
  ) : null;

  // 年龄分布：柱状 + 误差线
  const ageOption = ageData.length ? barWithError(
    '年龄分布',
    ageData.map((d) => (d as { age_group: string }).age_group),
    ageData.map((d) => (d[compareValueField] ?? null) as number),
    ageData.map((d) => (d[compareLoField] ?? null) as number),
    ageData.map((d) => (d[compareHiField] ?? null) as number),
    valueUnit,
  ) : null;

  // ===================== 数据点表格 =====================

  const dataPointColumns = [
    { title: '文献名称', dataIndex: 'literature_title', key: 'literature_title', width: 200, ellipsis: true, sorter: true },
    { title: '疾病', dataIndex: 'disease', key: 'disease', width: 100, ellipsis: true, sorter: true },
    { title: '省份', dataIndex: 'province', key: 'province', width: 100, ellipsis: true, sorter: true },
    { title: '城市', dataIndex: 'city', key: 'city', width: 100, ellipsis: true, sorter: true },
    { title: '年龄组', dataIndex: 'age_group', key: 'age_group', width: 100, ellipsis: true, sorter: true },
    { title: '样本量', dataIndex: 'sample_size', key: 'sample_size', width: 80, sorter: true },
    { title: '数据类型', dataIndex: 'data_type', key: 'data_type', width: 110, sorter: true,
      render: (v: string) => v === 'seroprevalence' ? '血清阳性率' : v === 'gmc' ? 'GMC' : v },
    { title: '数值', dataIndex: 'value', key: 'value', width: 80, sorter: true,
      render: (v: number | null) => v != null ? v.toFixed(2) : '-' },
    { title: '单位', dataIndex: 'unit', key: 'unit', width: 60, ellipsis: true, sorter: true },
    { title: 'CI下限', dataIndex: 'ci_lower', key: 'ci_lower', width: 80,
      render: (v: number | null) => v != null ? v.toFixed(2) : '-' },
    { title: 'CI上限', dataIndex: 'ci_upper', key: 'ci_upper', width: 80,
      render: (v: number | null) => v != null ? v.toFixed(2) : '-' },
    { title: '采集年份', dataIndex: 'collection_year', key: 'collection_year', width: 90, sorter: true },
    { title: '检测方法', dataIndex: 'method', key: 'method', width: 100, ellipsis: true, sorter: true },
    { title: '人群', dataIndex: 'population', key: 'population', width: 90, ellipsis: true, sorter: true },
  ];

  const rowSelection: TableRowSelection<DataItem> = {
    selectedRowKeys,
    onChange: (keys: React.Key[], rows: DataItem[]) => {
      setSelectedRowKeys(keys);
      setSelectedRows(rows);
    },
  };

  const handleTableChange = (
    pagination: { current?: number; pageSize?: number },
    _filters: unknown,
    sorter: any,
  ) => {
    const page = pagination.current || 1;
    const pageSize = pagination.pageSize || 50;
    setDpPage(page);
    setDpPageSize(pageSize);

    let sortBy: string | undefined;
    let sortOrder: string | undefined;
    const singleSorter = Array.isArray(sorter) ? sorter[0] : sorter;
    if (singleSorter && singleSorter.order) {
      sortBy = String(singleSorter.field);
      sortOrder = singleSorter.order === 'ascend' ? 'asc' : 'desc';
    }
    setDpSortBy(sortBy);
    setDpSortOrder(sortOrder);
    fetchApprovedData(page, pageSize, sortBy, sortOrder);
  };

  // ===================== 选中数据点图表 =====================

  const barColors = ['#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de', '#3ba272', '#fc8452', '#9a60b4'];

  const selectedBarOption = selectedRows.length > 0 ? {
    title: { text: '选中数据点数值对比', left: 'center' },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
    },
    xAxis: {
      type: 'category',
      data: selectedRows.map((r, i) => {
        const parts = [r.province as string, r.age_group as string, r.collection_year as number].filter(Boolean);
        return parts.join('-') || `数据点${i + 1}`;
      }),
      axisLabel: { rotate: 45, interval: 0, fontSize: 10 },
    },
    yAxis: { type: 'value', name: '数值' },
    grid: { bottom: 120, top: 50 },
    series: [{
      type: 'bar',
      name: '数值',
      data: selectedRows.map((r, i) => ({
        value: (r.value as number) ?? 0,
        itemStyle: { color: barColors[i % barColors.length] },
      })),
      label: {
        show: true,
        position: 'top',
        formatter: (p: { value: number }) => p.value.toFixed(1),
      },
    }],
  } : null;

  // 散点图：样本量 vs 数值
  const scatterOption = selectedRows.filter(r => r.sample_size != null && r.value != null).length > 1 ? {
    title: { text: '样本量 vs 数值', left: 'center' },
    tooltip: {
      trigger: 'item',
      formatter: (p: { name: string; value: [number, number] }) => {
        return `${p.name}<br/>样本量: ${p.value[0]}<br/>数值: ${p.value[1]}`;
      },
    },
    xAxis: { type: 'value', name: '样本量' },
    yAxis: { type: 'value', name: '数值' },
    series: [{
      type: 'scatter',
      data: selectedRows
        .filter(r => r.sample_size != null && r.value != null)
        .map((r, i) => {
          const parts = [r.province as string, r.age_group as string, r.collection_year as number].filter(Boolean);
          return {
            name: parts.join('-') || `数据点${i + 1}`,
            value: [r.sample_size as number, r.value as number],
          };
        }),
      symbolSize: 12,
      itemStyle: { color: '#5470c6' },
    }],
  } : null;

  // ===================== 筛选面板 =====================

  const filterPanel = (
    <Card style={{ marginBottom: 16 }}>
      <Row gutter={16} align="middle">
        <Col><span style={{ fontWeight: 'bold' }}>筛选：</span></Col>
        <Col><DiseaseSelector value={localDisease} onChange={setLocalDisease} /></Col>
        <Col><MapSelector value={localDataType} onChange={setLocalDataType} /></Col>
        <Col><ProvinceSelector multiple value={province} onChange={setProvince} /></Col>
        <Col>
          <Button type="primary" icon={<SearchOutlined />} onClick={handleConfirm}>
            查询
          </Button>
        </Col>
        <Col>
          <Button icon={<DownloadOutlined />} onClick={() => {
            const params = new URLSearchParams();
            if (localDisease) params.set('disease', localDisease);
            if (localDataType) params.set('data_type', localDataType);
            if (province.length > 0) params.set('province', province.join(','));
            window.open(`/api/v1/analysis/export?${params.toString()}`);
          }}>
            导出 Excel
          </Button>
        </Col>
        <Col>
          <Button icon={<DownloadOutlined />} onClick={() => {
            const params = new URLSearchParams();
            if (localDisease) params.set('disease', localDisease);
            if (localDataType) params.set('data_type', localDataType);
            if (province.length > 0) params.set('province', province.join(','));
            window.open(`/api/v1/analysis/dataset-snapshot?${params.toString()}`);
          }}>
            数据集快照
          </Button>
        </Col>
      </Row>
    </Card>
  );

  // ===================== 汇总分析内容 =====================

  const regionCompareColumns = [
    { title: '省份', dataIndex: 'province', key: 'province', width: 80, ellipsis: true, sorter: (a: DataItem, b: DataItem) => String(a.province).localeCompare(String(b.province)) },
    {
      title: '粗率 (%)',
      key: 'crude',
      width: 110,
      render: (_: unknown, r: DataItem) => {
        const v = r.avg_positivity as number | null;
        if (v == null) return '-';
        return (
          <span>
            {v.toFixed(2)}
            {r.positivity_ci_lower != null && (
              <span style={{ color: '#999', fontSize: 11 }}>
                <br />({Number(r.positivity_ci_lower).toFixed(1)}~{Number(r.positivity_ci_upper).toFixed(1)})
              </span>
            )}
          </span>
        );
      },
    },
    {
      title: '标化率 ASR (%)',
      key: 'asr',
      width: 130,
      render: (_: unknown, r: DataItem) => {
        const v = r.asr as number | null;
        if (v == null) return <span style={{ color: '#999' }}>—</span>;
        return (
          <span>
            {v.toFixed(2)}
            {r.asr_ci_lower != null && (
              <span style={{ color: '#999', fontSize: 11 }}>
                <br />({Number(r.asr_ci_lower).toFixed(1)}~{Number(r.asr_ci_upper).toFixed(1)})
              </span>
            )}
          </span>
        );
      },
    },
    { title: '样本量', dataIndex: 'total_samples', key: 'total_samples', width: 90, sorter: (a: DataItem, b: DataItem) => Number(a.total_samples) - Number(b.total_samples) },
    { title: '数据点', dataIndex: 'point_count', key: 'point_count', width: 70, sorter: (a: DataItem, b: DataItem) => Number(a.point_count) - Number(b.point_count) },
  ];

  const summaryContent = (
    <Spin spinning={loading}>
      <Row gutter={16}>
        <Col span={12}>
          <ChartWithSnapshot
            title="区域对比（各省阳性率）"
            token={snapshotTokens.region}
            option={regionOption}
            height={350}
          >
            {!regionOption && <Empty description="请选择筛选条件后点击查询" />}
            {regionData.length > 0 && (
              <div style={{ marginTop: 8, textAlign: 'center' }}>
                <Radio.Group
                  value={regionRateView}
                  onChange={(e) => setRegionRateView(e.target.value)}
                  size="small"
                  optionType="button"
                  buttonStyle="solid"
                  style={{ marginRight: 8 }}
                >
                  <Radio.Button value="crude">粗率</Radio.Button>
                  <Radio.Button value="asr">标化率 (ASR)</Radio.Button>
                </Radio.Group>
                {comparisonTest && (
                  <Button
                    size="small"
                    type="link"
                    onClick={() => setPairModalVisible(true)}
                  >
                    两两对比详情
                  </Button>
                )}
              </div>
            )}
            {regionData.length > 0 && (
              <Table
                rowKey="province"
                columns={regionCompareColumns}
                dataSource={regionData}
                size="small"
                pagination={false}
                scroll={{ x: 480, y: 220 }}
                style={{ marginTop: 12 }}
              />
            )}
          </ChartWithSnapshot>
        </Col>
        <Col span={12}>
          <ChartWithSnapshot
            title="逐年趋势分析"
            token={snapshotTokens.trend}
            option={trendOption}
            height={350}
          >
            {!trendOption && <Empty description="请选择筛选条件后点击查询" />}
            <div style={{ marginTop: 8, textAlign: 'center' }}>
              {trendTest && (
                <Tag color={trendTest.p_value < 0.05 ? (trendTest.direction === 'increasing' ? 'green' : 'red') : 'default'}
                  style={{ marginBottom: 4 }}>
                  Cochran-Armitage p={trendTest.p_value.toFixed(3)}
                  {trendTest.p_value < 0.05 ? `，${trendTest.direction_label}趋势${trendTest.direction === 'increasing' ? '↗' : '↘'}` : '，无显著趋势'}
                </Tag>
              )}
              {trendSignificance && (
                <span>
                  <Tag color={trendSignificance.direction === 'increasing' ? 'green' : trendSignificance.direction === 'decreasing' ? 'red' : 'blue'}
                    style={{ marginBottom: 4 }}>
                    趋势：{trendSignificance.direction === 'increasing' ? '上升' : trendSignificance.direction === 'decreasing' ? '下降' : '平稳'}
                  </Tag>
                  <span style={{ marginLeft: 8, fontSize: 12 }}>
                    斜率 {trendSignificance.slope_per_year ?? '—'}/年 · R² {trendSignificance.r_squared ?? '—'} · P {trendSignificance.p_value ?? '—'}
                  </span>
                </span>
              )}
            </div>
          </ChartWithSnapshot>
        </Col>
      </Row>
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={12}>
          <ChartWithSnapshot
            title="年龄分层分析"
            token={snapshotTokens.age}
            option={ageOption}
            height={350}
          >
            {!ageOption && <Empty description="请选择筛选条件后点击查询" />}
          </ChartWithSnapshot>
        </Col>
      </Row>

      {/* 两两对比详情弹窗 */}
      <Modal
        title="两省对比统计检验"
        open={pairModalVisible}
        onCancel={() => setPairModalVisible(false)}
        footer={null}
        width={520}
      >
        {comparisonTest && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="对比省份">
              {comparisonTest.province_a} vs {comparisonTest.province_b}
            </Descriptions.Item>
            <Descriptions.Item label="阳性率">
              {comparisonTest.province_a}: {(comparisonTest.p1 * 100).toFixed(1)}% (n={comparisonTest.n1})
              <br />
              {comparisonTest.province_b}: {(comparisonTest.p2 * 100).toFixed(1)}% (n={comparisonTest.n2})
            </Descriptions.Item>
            <Descriptions.Item label="率差 (RD)">
              {(comparisonTest.rd * 100).toFixed(2)}%
              <br />
              95%CI: {(comparisonTest.rd_ci_lower * 100).toFixed(2)}% ~ {(comparisonTest.rd_ci_upper * 100).toFixed(2)}%
            </Descriptions.Item>
            <Descriptions.Item label="率比 (RR)">
              {comparisonTest.rr != null ? comparisonTest.rr.toFixed(4) : '—'}
              <br />
              {comparisonTest.rr_ci_lower != null && comparisonTest.rr_ci_upper != null
                ? `95%CI: ${comparisonTest.rr_ci_lower.toFixed(4)} ~ ${comparisonTest.rr_ci_upper.toFixed(4)}`
                : '—'}
            </Descriptions.Item>
            <Descriptions.Item label="z 值 / p 值">
              z={comparisonTest.z.toFixed(3)}, p={comparisonTest.p_value.toFixed(4)}
            </Descriptions.Item>
            <Descriptions.Item label="结论">
              <Alert
                type={comparisonTest.significant ? 'info' : 'warning'}
                message={comparisonTest.conclusion}
                showIcon
              />
            </Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </Spin>
  );

  // ===================== 数据点可视化内容 =====================

  const datapointsContent = (
    <>
      <Card style={{ marginBottom: 16 }}>
        <Space style={{ marginBottom: 12 }}>
          <span style={{ fontWeight: 'bold' }}>
            审核通过的数据点（共 {approvedTotal} 条，当前已选 {selectedRowKeys.length} 条）
          </span>
        </Space>
        <Table
          rowKey="id"
          rowSelection={rowSelection}
          columns={dataPointColumns}
          dataSource={approvedData}
          loading={approvedLoading}
          size="small"
          scroll={{ x: 1400 }}
          pagination={{
            current: dpPage,
            pageSize: dpPageSize,
            total: approvedTotal,
            showSizeChanger: true,
            showTotal: (total: number) => `共 ${total} 条`,
          }}
          onChange={handleTableChange}
        />
      </Card>

      {selectedRows.length > 0 && (
        <Row gutter={16}>
          <Col span={scatterOption ? 12 : 24}>
            <ChartWithSnapshot
              title="选中数据点数值对比"
              token={snapshotTokens.datapoints}
              option={selectedBarOption}
              height={400}
            >
              {!selectedBarOption && <Empty description="请先选择数据点" />}
            </ChartWithSnapshot>
          </Col>
          {scatterOption && (
            <Col span={12}>
              <ChartWithSnapshot
                title="样本量 vs 数值"
                token={snapshotTokens.datapoints}
                option={scatterOption}
                height={400}
              />
            </Col>
          )}
        </Row>
      )}

      {selectedRows.length === 0 && !approvedLoading && (
        <Card>
          <Empty description="请在表格中勾选数据点，然后查看可视化图表" />
        </Card>
      )}
    </>
  );

  // ===================== 数据覆盖度分析内容 =====================

  const diseaseNameMap: Record<string, string> = Object.fromEntries(
    DISEASES.map((d) => [d.key, d.name_cn])
  );

  // ===================== 新增：状态/评分 辅助函数 =====================
  type CoverageStatus = 'well_covered' | 'need_review' | 'need_supplement' | 'need_both';

  const statusMeta: Record<CoverageStatus, { label: string; color: string; tag: string }> = {
    well_covered: { label: '完善', color: '#52c41a', tag: 'success' },
    need_review: { label: '需审核', color: '#fa8c16', tag: 'warning' },
    need_supplement: { label: '需补充', color: '#f5222d', tag: 'error' },
    need_both: { label: '需审核+补充', color: '#eb2f96', tag: 'magenta' },
  };

  const renderStatus = (status?: CoverageStatus) => {
    if (!status) return '-';
    const s = statusMeta[status];
    return <Tag color={s.tag}>{s.label}</Tag>;
  };

  const renderCompleteness = (score?: number) => {
    if (score == null) return '-';
    let color = '#52c41a';
    if (score < 30) color = '#f5222d';
    else if (score < 60) color = '#fa8c16';
    else if (score < 80) color = '#faad14';
    return (
      <Space>
        <Progress percent={score} size={[60, 6]} showInfo={false} strokeColor={color} />
        <span style={{ color, fontWeight: 'bold', minWidth: 32, display: 'inline-block' }}>{score}</span>
      </Space>
    );
  };

  // 热力图单元格背景色（根据完整性评分 + 数据量）
  const getCellBg = (total: number, status?: CoverageStatus) => {
    if (total === 0) return 'transparent';
    // 基础色系（根据总量）
    let bg = '#fff7e6';
    if (total <= 2) bg = '#fff7e6';
    else if (total <= 5) bg = '#ffe7ba';
    else if (total <= 10) bg = '#ffd591';
    else if (total <= 20) bg = '#ffa940';
    else bg = '#fa541c';
    // 若状态为完善 → 叠加绿色系
    if (status === 'well_covered') {
      if (total <= 2) bg = '#f6ffed';
      else if (total <= 5) bg = '#d9f7be';
      else if (total <= 10) bg = '#b7eb8f';
      else if (total <= 20) bg = '#95de64';
      else bg = '#73d13d';
    }
    // 需要补充 → 叠加红色系
    if (status === 'need_supplement') {
      bg = total < 3 ? '#fff1f0' : '#ffccc7';
    }
    return bg;
  };

  const commonAuditColumns = (sortByPending: boolean = true) => [
    {
      title: '省份', dataIndex: 'province', key: 'province', width: 100,
      sorter: (a: { province: string }, b: { province: string }) => a.province.localeCompare(b.province),
    },
    {
      title: '年份', dataIndex: 'year', key: 'year', width: 80,
      sorter: (a: { year: number | null }, b: { year: number | null }) => (a.year || 0) - (b.year || 0),
      render: (v: number | null) => v || '-',
    },
    {
      title: '疾病', dataIndex: 'disease', key: 'disease', width: 100,
      render: (v: string) => diseaseNameMap[v] || v,
    },
    {
      title: '完整性评分',
      dataIndex: 'completeness_score',
      key: 'completeness_score',
      width: 140,
      sorter: (a: { completeness_score?: number }, b: { completeness_score?: number }) => (a.completeness_score ?? 0) - (b.completeness_score ?? 0),
      render: renderCompleteness,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 110,
      render: renderStatus,
    },
    {
      title: '待审核', dataIndex: 'pending_count', key: 'pending_count', width: 90,
      sorter: (a: { pending_count: number }, b: { pending_count: number }) => a.pending_count - b.pending_count,
      defaultSortOrder: (sortByPending ? 'descend' : 'ascend') as 'descend' | 'ascend',
      render: (v: number) => <Tag color={v >= 10 ? 'red' : v >= 5 ? 'orange' : 'default'}>{v}</Tag>,
    },
    { title: '已通过', dataIndex: 'approved_count', key: 'approved_count', width: 80 },
    { title: '已驳回', dataIndex: 'rejected_count', key: 'rejected_count', width: 80 },
    { title: '总计', dataIndex: 'total_count', key: 'total_count', width: 80 },
  ];

  // 需要审核：默认按 pending 降序
  const reviewColumns = commonAuditColumns(true);
  // 需要补充：默认按 approved 升序
  const supplementColumns = commonAuditColumns(false);

  // 构建省/城市 年份矩阵列（通用函数）
  const buildMatrixColumns = (
    allYears: number[],
    withProvinceColumn: boolean,
    withCityColumn: boolean,
  ) => {
    const cols: any[] = [];
    if (withProvinceColumn) {
      cols.push({
        title: '省份',
        dataIndex: 'province',
        key: 'province',
        width: 80,
        fixed: 'left' as const,
        sorter: (a: any, b: any) => a.province.localeCompare(b.province),
      });
    }
    if (withCityColumn) {
      cols.push({
        title: '城市',
        dataIndex: 'city',
        key: 'city',
        width: 100,
        fixed: 'left' as const,
        sorter: (a: any, b: any) => a.city.localeCompare(b.city),
      });
    }
    cols.push({
      title: '完整性评分',
      dataIndex: 'completeness_score',
      key: 'completeness_score',
      width: 120,
      fixed: 'left' as const,
      sorter: (a: ProvinceYearRow, b: ProvinceYearRow) => (a.completeness_score ?? 0) - (b.completeness_score ?? 0),
      defaultSortOrder: 'descend' as const,
      render: renderCompleteness,
    });
    cols.push({
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      fixed: 'left' as const,
      render: renderStatus,
    });
    cols.push({
      title: '已通过',
      dataIndex: 'approved',
      key: 'approved',
      width: 70,
      sorter: (a: ProvinceYearRow, b: ProvinceYearRow) => (a.approved ?? 0) - (b.approved ?? 0),
    });
    cols.push({
      title: '待审核',
      dataIndex: 'pending',
      key: 'pending',
      width: 70,
      sorter: (a: ProvinceYearRow, b: ProvinceYearRow) => a.pending - b.pending,
      render: (v: number) => v > 0 ? <Tag color="orange">{v}</Tag> : v,
    });
    cols.push({
      title: '总计',
      dataIndex: 'total',
      key: 'total',
      width: 60,
      fixed: 'left' as const,
      sorter: (a: ProvinceYearRow, b: ProvinceYearRow) => a.total - b.total,
      render: (v: number) => <strong>{v}</strong>,
    });
    cols.push(...allYears.map((year) => ({
      title: String(year),
      key: String(year),
      width: 64,
      align: 'center' as const,
      render: (_: unknown, record: ProvinceYearRow) => {
        const cell = record.years[String(year)];
        if (!cell || cell.total === 0) {
          return <span style={{ color: '#ccc' }}>-</span>;
        }
        const bg = getCellBg(cell.total, cell.status);
        const hasPending = cell.pending > 0;
        const statusInfo = cell.status ? statusMeta[cell.status as CoverageStatus] : null;
        const tooltipText = [
          `总计: ${cell.total}`,
          `已通过: ${cell.approved}`,
          `待审核: ${cell.pending}`,
          statusInfo ? `状态: ${statusInfo.label}` : null,
          `评分: ${cell.completeness_score ?? '-'}`,
        ].filter(Boolean).join('\n');
        return (
          <Tooltip title={tooltipText}>
            <div style={{
              background: bg,
              borderRadius: 3,
              padding: '2px 4px',
              textAlign: 'center',
              cursor: 'pointer',
              border: hasPending ? '1px solid #ff4d4f' : `1px solid ${cell.status === 'well_covered' ? '#52c41a' : 'transparent'}`,
            }}>
              <span style={{ fontSize: 12, fontWeight: hasPending ? 'bold' : 'normal' }}>
                {cell.total}
              </span>
            </div>
          </Tooltip>
        );
      },
    })));
    return cols;
  };

  // 构建热力图表格列（省份矩阵）
  const allYears = gapData?.overview.years || [];
  const provinceHeatmapColumns = buildMatrixColumns(allYears, true, false);
  // 构建热力图表格列（城市矩阵）
  const cityHeatmapColumns = buildMatrixColumns(allYears, true, true);

  const coverageContent = (
    <Spin spinning={gapLoading}>
      {gapData ? (
        <>
          {/* 概览统计卡片 */}
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={4}>
              <Card>
                <Statistic
                  title="总数据点"
                  value={gapData.overview.total_data_points}
                  prefix={<FileSearchOutlined />}
                />
              </Card>
            </Col>
            <Col span={4}>
              <Card>
                <Statistic
                  title="覆盖省份"
                  value={gapData.overview.total_provinces}
                  suffix="/ 34"
                  valueStyle={{ color: '#52c41a' }}
                  prefix={<CheckCircleOutlined />}
                />
              </Card>
            </Col>
            <Col span={4}>
              <Card>
                <Statistic
                  title="覆盖城市"
                  value={gapData.overview.total_cities || 0}
                  valueStyle={{ color: '#1677ff' }}
                  prefix={<CheckCircleOutlined />}
                />
              </Card>
            </Col>
            <Col span={4}>
              <Card>
                <Statistic
                  title="已通过数据点"
                  value={gapData.overview.approved_count}
                  valueStyle={{ color: '#52c41a' }}
                />
              </Card>
            </Col>
            <Col span={4}>
              <Card>
                <Statistic
                  title="待审核数据点"
                  value={gapData.overview.pending_count}
                  valueStyle={{ color: gapData.overview.pending_count > 0 ? '#fa541c' : '#52c41a' }}
                  prefix={<WarningOutlined />}
                />
              </Card>
            </Col>
            <Col span={4}>
              <Card>
                <Statistic
                  title="缺失省份-疾病组合"
                  value={gapData.overview.total_gap_combos}
                  valueStyle={{ color: gapData.overview.total_gap_combos > 0 ? '#fa541c' : '#52c41a' }}
                  prefix={<WarningOutlined />}
                />
              </Card>
            </Col>
          </Row>

          {/* 组合状态概览 */}
          {gapData.overview.combo_status_counts && (
            <Row gutter={16} style={{ marginBottom: 16 }}>
              {(['well_covered', 'need_review', 'need_supplement', 'need_both'] as CoverageStatus[]).map(status => {
                const count = gapData.overview.combo_status_counts?.[status] ?? 0;
                const info = statusMeta[status];
                return (
                  <Col span={6} key={status}>
                    <Card>
                      <Statistic
                        title={<span style={{ color: info.color }}>省×年组合：{info.label}</span>}
                        value={count}
                        valueStyle={{ color: info.color }}
                        suffix={`/ ${Object.values(gapData.overview.combo_status_counts || {}).reduce((a: number, b: number) => a + b, 0)}`}
                      />
                    </Card>
                  </Col>
                );
              })}
            </Row>
          )}

          {/* 年份范围信息 */}
          {gapData.overview.year_range && (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
              message={
                <>
                  数据覆盖年份范围：<strong>{gapData.overview.year_range[0]} - {gapData.overview.year_range[1]}</strong>，
                  共 <strong>{gapData.overview.years.length}</strong> 个年份，
                  涉及 <strong>{gapData.overview.total_diseases}</strong> 种疾病。
                  {gapData.overview.well_covered_threshold && (
                    <span style={{ marginLeft: 12, color: '#52c41a' }}>
                      完善判定标准：已通过 ≥ {gapData.overview.well_covered_threshold} 条且无待审核
                    </span>
                  )}
                </>
              }
            />
          )}

          {/* 需要审核提醒 */}
          {gapData.review_needed.length > 0 ? (
            <Card
              title={
                <Space>
                  <WarningOutlined style={{ color: '#fa541c' }} />
                  <span>需要审核的数据点（{gapData.review_needed.length} 个省份-年份-疾病组合待审核）</span>
                </Space>
              }
              style={{ marginBottom: 16 }}
              extra={
                <Space>
                  <Tag color="warning">需审核</Tag>
                  <Tag color="magenta">需审核+补充</Tag>
                </Space>
              }
            >
              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 12 }}
                message="以下省份和年份的数据点尚未完成审核，请前往文献详情页审核后才能纳入分析统计"
              />
              <Table<any>
                rowKey={(r: any) => `${r.province}-${r.year}-${r.disease}`}
                columns={reviewColumns as any}
                dataSource={gapData.review_needed as any[]}
                size="small"
                pagination={{ pageSize: 10, showSizeChanger: true, pageSizeOptions: [10, 20, 50] }}
                scroll={{ x: 950 }}
              />
            </Card>
          ) : (
            <Card style={{ marginBottom: 16 }}>
              <Alert
                type="success"
                showIcon
                message="所有数据点已完成审核，无待审核项"
              />
            </Card>
          )}

          {/* 需要补充提醒 */}
          {gapData.supplement_needed && gapData.supplement_needed.length > 0 ? (
            <Card
              title={
                <Space>
                  <WarningOutlined style={{ color: '#f5222d' }} />
                  <span>需要补充的数据点（{gapData.supplement_needed.length} 个省份-年份-疾病组合需要补充）</span>
                </Space>
              }
              style={{ marginBottom: 16 }}
              extra={
                <Space>
                  <Tag color="error">需补充</Tag>
                  <Tag color="magenta">需审核+补充</Tag>
                </Space>
              }
            >
              <Alert
                type="error"
                showIcon
                style={{ marginBottom: 12 }}
                message="以下省份和年份数据不足或完全没有数据，建议补充相关文献和数据提取"
              />
              <Table<any>
                rowKey={(r: any) => `${r.province}-${r.year}-${r.disease}-sup`}
                columns={supplementColumns as any}
                dataSource={gapData.supplement_needed as any[]}
                size="small"
                pagination={{ pageSize: 10, showSizeChanger: true, pageSizeOptions: [10, 20, 50] }}
                scroll={{ x: 950 }}
              />
            </Card>
          ) : null}

          {/* 数据缺失提醒（按疾病分组）—— 所有疾病均展示，越完善越靠前 */}
          <Card
            title={
              <Space>
                <WarningOutlined style={{ color: '#fa8c16' }} />
                <span>数据覆盖情况（按疾病分组，越完善越靠前）</span>
                <Tag color="blue">共 {gapData.data_gaps.length} 种疾病</Tag>
              </Space>
            }
            style={{ marginBottom: 16 }}
          >
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message="完善的疾病排在最前面（可直接看到覆盖完整的标杆），缺失较多的在后。绿色'覆盖完整'= 省份全覆盖，无需补充。"
            />
            <Collapse
              items={gapData.data_gaps.map((g: DataGapItem) => {
                const fullyCovered = g.missing_count === 0;
                const covPct = g.coverage_percent ?? Math.round(g.covered_count / 34 * 100);
                return {
                  key: g.disease,
                  label: (
                    <Space>
                      <span style={{ fontWeight: 'bold' }}>{diseaseNameMap[g.disease] || g.disease}</span>
                      {fullyCovered ? (
                        <Tag color="gold">✅ 覆盖完整 {g.covered_count}/34 省</Tag>
                      ) : (
                        <>
                          <Tag color="green">已覆盖 {g.covered_count} 省</Tag>
                          <Tag color="red">缺失 {g.missing_count} 省</Tag>
                        </>
                      )}
                      <Tag color={fullyCovered ? 'success' : 'processing'}>
                        完整度 {covPct}%
                      </Tag>
                    </Space>
                  ),
                  children: (
                    <div>
                      {fullyCovered ? (
                        <Alert type="success" showIcon
                          message={`${diseaseNameMap[g.disease] || g.disease}已覆盖全部省份，数据完善`}
                          description="可作为标杆疾病。可拓展年龄组/年份细分或增加抗体类型以进一步提高精度。"
                          style={{ marginBottom: 12 }}
                        />
                      ) : (
                        <>
                          <p style={{ marginBottom: 8, color: '#888' }}>
                            建议补充以下 <b>{g.missing_count}</b> 个省份的{diseaseNameMap[g.disease] || g.disease}相关数据：
                          </p>
                          <Space wrap>
                            {g.missing_provinces.map((p) => (
                              <Tag key={p} color="orange" style={{ marginBottom: 4 }}>{p}</Tag>
                            ))}
                          </Space>
                        </>
                      )}
                      <div style={{ marginTop: 12 }}>
                        <span style={{ color: '#52c41a', fontSize: 13 }}>已有数据省份：</span>
                        <Space wrap size={[4, 4]} style={{ marginTop: 4 }}>
                          {g.covered_provinces.length > 0 ? g.covered_provinces.map((p) => (
                            <Tag key={p} color="blue">{p}</Tag>
                          )) : <Tag>暂无</Tag>}
                        </Space>
                      </div>
                    </div>
                  ),
                };
              })}
            />
          </Card>

          {/* 省份×年份矩阵（按完整性评分降序） */}
          <Card
            title={
              <Space>
                <span>省份 × 年份数据点分布矩阵</span>
                <Tag color="blue">按完整性排序（完善的在前）</Tag>
              </Space>
            }
            extra={
              <Space wrap>
                <Tag color="success">完善</Tag>
                <Tag color="warning">需审核</Tag>
                <Tag color="error">需补充</Tag>
                <Tag color="magenta">需审核+补充</Tag>
                <Tag color="red">红框=有待审核</Tag>
              </Space>
            }
            style={{ marginBottom: 16 }}
          >
            {gapData.province_year_matrix.length > 0 ? (
              <Table
                rowKey="province"
                columns={provinceHeatmapColumns}
                dataSource={gapData.province_year_matrix}
                size="small"
                pagination={false}
                scroll={{ x: 80 + 100 + 120 + 70 + 70 + 60 + allYears.length * 64 }}
              />
            ) : (
              <Empty description="暂无数据" />
            )}
          </Card>

          {/* 城市×年份矩阵（按完整性评分降序） */}
          {gapData.city_year_matrix && gapData.city_year_matrix.length > 0 && (
            <Card
              title={
                <Space>
                  <span>城市 × 年份数据点分布矩阵</span>
                  <Tag color="green">{gapData.city_year_matrix.length} 个城市</Tag>
                  <Tag color="blue">按完整性排序</Tag>
                </Space>
              }
              style={{ marginBottom: 16 }}
            >
              <Table
                rowKey={(r: any) => `${r.province}-${r.city}`}
                columns={cityHeatmapColumns}
                dataSource={gapData.city_year_matrix}
                size="small"
                pagination={{ pageSize: 15, showSizeChanger: true, pageSizeOptions: [15, 30, 50] }}
                scroll={{ x: 80 + 100 + 100 + 120 + 70 + 70 + 60 + allYears.length * 64 }}
              />
            </Card>
          )}
        </>
      ) : (
        <Empty description="正在加载..." />
      )}

      {/* ===== 审核状态统计（按疾病）— 直接展示，无需筛选 ===== */}
      <Card
        size="small"
        title={
          <Space>
            <span>审核状态统计（按疾病）</span>
            <Tag color="blue">数据点 / 样本量 / 通过率</Tag>
          </Space>
        }
        extra={
          <Space>
            <span style={{ color: '#888', fontSize: 13 }}>疾病筛选</span>
            <DiseaseSelector
              value={coverageReviewDisease}
              onChange={setCoverageReviewDisease}
              style={{ width: 160 }}
            />
          </Space>
        }
        style={{ marginTop: 16 }}
      >
        <Spin spinning={coverageReviewLoading}>
          {coverageReview && coverageReview.diseases && coverageReview.diseases.length > 0 ? (
            <>
              {/* 总体概览 */}
              <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={6}>
                  <Statistic title="总疾病数" value={coverageReview.overview.total_diseases} />
                </Col>
                <Col span={6}>
                  <Statistic title="总数据点" value={coverageReview.overview.total_points} />
                </Col>
                <Col span={6}>
                  <Statistic
                    title="待审核数据点"
                    value={coverageReview.overview.pending_points}
                    valueStyle={{ color: coverageReview.overview.pending_points > 0 ? '#fa541c' : '#52c41a' }}
                  />
                </Col>
                <Col span={6}>
                  <Statistic
                    title="总体通过率"
                    value={Math.round(coverageReview.overview.overall_approval_rate * 100)}
                    suffix="%"
                    valueStyle={
                      coverageReview.overview.overall_approval_rate >= 0.8
                        ? { color: '#52c41a' }
                        : coverageReview.overview.overall_approval_rate >= 0.5
                          ? { color: '#faad14' }
                          : { color: '#f5222d' }
                    }
                  />
                </Col>
              </Row>

              <Card size="small" title="各疾病审核状态分布" style={{ marginBottom: 16, border: 'none', boxShadow: 'none' }}>
                <CoverageReviewChart data={coverageReview.diseases} />
              </Card>

              <CoverageReviewTable data={coverageReview.diseases} loading={coverageReviewLoading} />
            </>
          ) : (
            <Empty description="无审核状态统计数据" />
          )}
        </Spin>
      </Card>
    </Spin>
  );

  // ===================== FOI 感染力 + 群体免疫阈值分析 =====================

  const herdStatusMeta: Record<string, { label: string; color: string }> = {
    reached: { label: '已达群体免疫', color: '#52c41a' },
    near: { label: '接近阈值', color: '#faad14' },
    not_reached: { label: '未达阈值', color: '#f5222d' },
    undetermined: { label: '数据不足', color: '#8c8c8c' },
    no_data: { label: '无数据', color: '#bfbfbf' },
  };

  const foiCurrentDisease: FoiPerDiseaseResult | undefined = (foiData?.per_disease_results || []).find(
    (d) => d.disease === foiSelectedDisease
  );

  const foiAgeOption = foiCurrentDisease?.foi_by_age_group.length ? {
    title: { text: '各年龄组 FOI（感染力）对比', left: 'center' },
    tooltip: { trigger: 'axis' },
    legend: { data: ['加权阳性率', '平均FOI/年'], top: 30 },
    grid: { top: 70, bottom: 50 },
    xAxis: {
      type: 'category',
      data: foiCurrentDisease.foi_by_age_group.map((d) => d.age_group),
      axisLabel: { rotate: 0 },
    },
    yAxis: [
      { type: 'value', name: '阳性率 (%)', position: 'left' },
      { type: 'value', name: 'FOI (/年)', position: 'right' },
    ],
    series: [
      {
        name: '加权阳性率',
        type: 'bar',
        yAxisIndex: 0,
        data: foiCurrentDisease.foi_by_age_group.map((d) => d.weighted_positivity_rate),
        itemStyle: { color: '#5470c6' },
        label: {
          show: true,
          position: 'top',
          formatter: (p: { value: number | null }) => p.value != null ? `${p.value}%` : '-',
        },
      },
      {
        name: '平均FOI/年',
        type: 'line',
        yAxisIndex: 1,
        data: foiCurrentDisease.foi_by_age_group.map((d) => d.weighted_avg_foi_per_year),
        smooth: true,
        itemStyle: { color: '#ee6666' },
        lineStyle: { width: 3 },
        symbol: 'circle',
        symbolSize: 8,
      },
    ],
  } : null;

  // 省份 FOI 热力矩阵
  const foiProvinceMatrixForDisease: FoiProvinceMatrixRow[] =
    (foiData?.province_foi_matrix || []).filter((r) => !foiSelectedDisease || r.disease === foiSelectedDisease);

  const foiProvinceColumns = [
    { title: '省份', dataIndex: 'province', key: 'province', width: 100, sorter: (a: FoiProvinceMatrixRow, b: FoiProvinceMatrixRow) => a.province.localeCompare(b.province) },
    { title: '数据点', dataIndex: 'data_point_count', key: 'data_point_count', width: 80, sorter: (a: FoiProvinceMatrixRow, b: FoiProvinceMatrixRow) => a.data_point_count - b.data_point_count },
    { title: '样本量', dataIndex: 'total_samples', key: 'total_samples', width: 80, sorter: (a: FoiProvinceMatrixRow, b: FoiProvinceMatrixRow) => a.total_samples - b.total_samples },
    { title: '加权阳性率', dataIndex: 'weighted_positivity_rate', key: 'weighted_positivity_rate', width: 110, sorter: (a: FoiProvinceMatrixRow, b: FoiProvinceMatrixRow) => (a.weighted_positivity_rate ?? 0) - (b.weighted_positivity_rate ?? 0),
      render: (v: number | null) => v != null ? `${v}%` : '-' },
    { title: 'FOI(/年)', dataIndex: 'weighted_avg_foi_per_year', key: 'weighted_avg_foi_per_year', width: 110, sorter: (a: FoiProvinceMatrixRow, b: FoiProvinceMatrixRow) => (a.weighted_avg_foi_per_year ?? 0) - (b.weighted_avg_foi_per_year ?? 0),
      render: (v: number | null) => v != null ? v.toFixed(5) : '-' },
    { title: '群体免疫状态', dataIndex: 'herd_immunity_status', key: 'herd_immunity_status', width: 130,
      render: (status: string) => {
        const meta = herdStatusMeta[status] || herdStatusMeta.undetermined;
        return <Tag color={meta.color}>{meta.label}</Tag>;
      }
    },
    { title: 'HIT目标', dataIndex: 'hit_target_percent', key: 'hit_target_percent', width: 90,
      render: (v: number | null) => v != null ? `${v}%` : '-' },
  ];

  const foiContent = (
    <Spin spinning={foiLoading}>
      {foiData ? (
        <>
          {/* 疾病选择器 */}
          {(() => { const dr = foiData.per_disease_results || []; return dr.length > 1; })() && (
            <Card style={{ marginBottom: 16 }}>
              <Space>
                <span style={{ fontWeight: 'bold' }}>选择分析疾病：</span>
                <Select
                  value={foiSelectedDisease || undefined}
                  style={{ minWidth: 200 }}
                  onChange={setFoiSelectedDisease}
                  allowClear
                  placeholder="全部疾病（汇总视图）"
                  options={(foiData.per_disease_results || []).map((d) => ({
                    label: `${diseaseNameMap[d.disease] || d.disease} (${d.summary.total_data_points}条数据)`,
                    value: d.disease,
                  }))}
                />
              </Space>
            </Card>
          )}

          {/* 概览统计卡片 */}
          {foiCurrentDisease && (
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={4}>
                <Card>
                  <Statistic
                    title={<span><ExperimentOutlined style={{ color: '#1677ff' }} /> 加权平均FOI (/年)</span>}
                    value={foiCurrentDisease.summary.weighted_avg_foi_per_year ?? undefined}
                    precision={5}
                    valueStyle={{ color: '#1677ff' }}
                  />
                </Card>
              </Col>
              <Col span={4}>
                <Card>
                  <Statistic
                    title="R0（FOI反推）"
                    value={foiCurrentDisease.summary.estimated_r0_from_foi ?? undefined}
                    precision={2}
                    suffix={foiCurrentDisease.summary.r0_reference?.typical ? `(典型${foiCurrentDisease.summary.r0_reference.typical})` : ''}
                    valueStyle={{ color: '#722ed1' }}
                  />
                </Card>
              </Col>
              <Col span={4}>
                <Card>
                  <Statistic
                    title="HIT(FOI→R0)"
                    value={foiCurrentDisease.summary.hit_from_foi_percent ?? undefined}
                    suffix="%"
                    valueStyle={{ color: '#13c2c2' }}
                  />
                </Card>
              </Col>
              <Col span={4}>
                <Card>
                  <Statistic
                    title="HIT(参考R0)"
                    value={foiCurrentDisease.summary.hit_from_reference_r0_percent ?? undefined}
                    suffix="%"
                    valueStyle={{ color: '#eb2f96' }}
                  />
                </Card>
              </Col>
              <Col span={4}>
                <Card>
                  <Statistic
                    title="WHO阈值"
                    value={foiCurrentDisease.summary.who_threshold_percent ?? undefined}
                    suffix="%"
                    valueStyle={{ color: '#fa8c16' }}
                  />
                </Card>
              </Col>
              <Col span={4}>
                <Card>
                  <Statistic
                    title={
                      <span>
                        群体免疫状态
                        <Tooltip title="基于加权阳性率 vs HIT目标（优先FOI估算，其次WHO阈值）">
                          <WarningOutlined style={{ color: '#8c8c8c', marginLeft: 4 }} />
                        </Tooltip>
                      </span>
                    }
                    value={herdStatusMeta[foiCurrentDisease.summary.herd_immunity_status]?.label || '-'}
                    valueStyle={{ color: herdStatusMeta[foiCurrentDisease.summary.herd_immunity_status]?.color }}
                  />
                </Card>
              </Col>
            </Row>
          )}

          {/* 备注说明 */}
          {foiData.notes.length > 0 && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 16 }}
              message={
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {foiData.notes.map((n, i) => <li key={i}>{n}</li>)}
                </ul>
              }
            />
          )}

          {/* 方法学说明 */}
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message={
              <>
                <strong>FOI（感染力）计算方法</strong>：催化模型（Catalytic Model）λ = -ln(1-SP) / age，其中 SP 为血清阳性率（0-1比例），age 为年龄组中点年龄。
                <br />
                <strong>R0估算</strong>：R0 ≈ λ × L（L=预期寿命，默认 {foiCurrentDisease?.summary.life_expectancy_used || 75} 年）。
                <br />
                <strong>群体免疫阈值 HIT</strong>：HIT = 1 - 1/R0（转成百分比），并与WHO推荐阈值对比。
              </>
            }
          />

          {/* 年龄组FOI图表 */}
          {foiCurrentDisease && (
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={24}>
                <ChartWithSnapshot
                  title={`年龄组 FOI 分析（${foiCurrentDisease.foi_by_age_group.length} 个年龄组）`}
                  token={tokenOf(foiData)}
                  option={foiAgeOption}
                  height={400}
                >
                  {!foiAgeOption && <Empty description="暂无足够年龄组数据进行FOI分析" />}
                </ChartWithSnapshot>
              </Col>
            </Row>
          )}

          {/* 省份 FOI 矩阵表格 */}
          <Card
            title={
              <Space>
                <span>省份 × FOI 热力矩阵</span>
                <Tag color="green">{foiProvinceMatrixForDisease.length} 个省份</Tag>
              </Space>
            }
            extra={
              <Space wrap>
                {Object.entries(herdStatusMeta).filter(([k]) => ['reached', 'near', 'not_reached', 'undetermined'].includes(k)).map(([k, v]) => (
                  <Tag key={k} color={v.color}>{v.label}</Tag>
                ))}
              </Space>
            }
            style={{ marginBottom: 16 }}
          >
            {foiProvinceMatrixForDisease.length > 0 ? (
              <Table<FoiProvinceMatrixRow>
                rowKey={(r) => `${r.disease}-${r.province}`}
                columns={foiProvinceColumns}
                dataSource={foiProvinceMatrixForDisease}
                size="small"
                pagination={{ pageSize: 15, showSizeChanger: true, pageSizeOptions: [15, 30, 50] }}
                scroll={{ x: 750 }}
              />
            ) : (
              <Empty description="暂无省份FOI数据" />
            )}
          </Card>
        </>
      ) : (
        <Empty description="正在加载..." />
      )}
    </Spin>
  );

  // ===================== 疫苗效果 VE + 接种率分析 =====================

  const coverageStatusMeta: Record<string, { label: string; color: string }> = {
    on_track: { label: '达标', color: '#52c41a' },
    near: { label: '接近达标', color: '#faad14' },
    below: { label: '偏低', color: '#f5222d' },
    undetermined: { label: '数据不足', color: '#8c8c8c' },
  };

  const vaccineCurrentDisease: VaccinePerDiseaseResult | undefined = (vaccineData?.per_disease_results || []).find(
    (d) => d.disease === vaccineSelectedDisease
  );

  // VE 亚组对比图表
  const veCompareOption = vaccineCurrentDisease?.ve_result
    && vaccineCurrentDisease.ve_result.vaxxed_weighted_sp != null
    && vaccineCurrentDisease.ve_result.unvaxxed_weighted_sp != null ? {
    title: { text: '已接种 vs 未接种 阳性率对比', left: 'center' },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: ['已接种组', '未接种组'],
    },
    yAxis: { type: 'value', name: '阳性率 (%)' },
    series: [{
      type: 'bar',
      data: [
        {
          value: vaccineCurrentDisease.ve_result.vaxxed_weighted_sp,
          itemStyle: { color: '#52c41a' },
          label: { show: true, position: 'top', formatter: '{c}%' },
        },
        {
          value: vaccineCurrentDisease.ve_result.unvaxxed_weighted_sp,
          itemStyle: { color: '#f5222d' },
          label: { show: true, position: 'top', formatter: '{c}%' },
        },
      ],
      barWidth: '50%',
    }],
  } : null;

  // 接种率双轨对比图表
  const vaccineCoverageBarOption = vaccineCurrentDisease ? {
    title: { text: '接种率双轨分析：NIP参考 vs 血清阳性率反推', left: 'center' },
    tooltip: { trigger: 'axis' },
    legend: { data: ['NIP参考接种率', '隐含接种率(SP反推)', '整体血清阳性率'], top: 30 },
    grid: { top: 70, bottom: 40 },
    xAxis: {
      type: 'category',
      data: [diseaseNameMap[vaccineCurrentDisease.disease] || vaccineCurrentDisease.disease],
    },
    yAxis: { type: 'value', name: '%', max: 100 },
    series: [
      {
        name: 'NIP参考接种率',
        type: 'bar',
        data: [vaccineCurrentDisease.coverage.nip_reference_national_percent],
        itemStyle: { color: '#1677ff' },
        label: { show: true, position: 'top', formatter: (p: { value: number | null }) => p.value != null ? `${p.value}%` : '-' },
      },
      {
        name: '隐含接种率(SP反推)',
        type: 'bar',
        data: [vaccineCurrentDisease.coverage.implied_from_seroprevalence_percent],
        itemStyle: { color: '#722ed1' },
        label: { show: true, position: 'top', formatter: (p: { value: number | null }) => p.value != null ? `${p.value}%` : '-' },
      },
      {
        name: '整体血清阳性率',
        type: 'bar',
        data: [vaccineCurrentDisease.overall_weighted_sp],
        itemStyle: { color: '#13c2c2' },
        label: { show: true, position: 'top', formatter: (p: { value: number | null }) => p.value != null ? `${p.value}%` : '-' },
      },
    ],
  } : null;

  // 省份覆盖率矩阵表格
  const vaccineProvinceForDisease: VaccineProvinceMatrixRow[] =
    (vaccineData?.province_coverage_matrix || []).filter((r) => !vaccineSelectedDisease || r.disease === vaccineSelectedDisease);

  const vaccineProvinceColumns = [
    { title: '省份', dataIndex: 'province', key: 'province', width: 100, sorter: (a: VaccineProvinceMatrixRow, b: VaccineProvinceMatrixRow) => a.province.localeCompare(b.province) },
    { title: '数据点', dataIndex: 'data_point_count', key: 'data_point_count', width: 80, sorter: (a: VaccineProvinceMatrixRow, b: VaccineProvinceMatrixRow) => a.data_point_count - b.data_point_count },
    { title: '加权阳性率', dataIndex: 'weighted_sp_percent', key: 'weighted_sp_percent', width: 100,
      sorter: (a: VaccineProvinceMatrixRow, b: VaccineProvinceMatrixRow) => (a.weighted_sp_percent ?? 0) - (b.weighted_sp_percent ?? 0),
      render: (v: number | null) => v != null ? `${v}%` : '-' },
    { title: 'VE(感染%)', dataIndex: 've_infection_percent', key: 've_infection_percent', width: 100,
      sorter: (a: VaccineProvinceMatrixRow, b: VaccineProvinceMatrixRow) => (a.ve_infection_percent ?? -999) - (b.ve_infection_percent ?? -999),
      render: (v: number | null) => v != null ? `${v}%` : <Tag color="default">无亚组</Tag> },
    { title: 'NIP参考接种率', dataIndex: 'nip_reference_coverage_percent', key: 'nip_reference_coverage_percent', width: 130,
      sorter: (a: VaccineProvinceMatrixRow, b: VaccineProvinceMatrixRow) => (a.nip_reference_coverage_percent ?? 0) - (b.nip_reference_coverage_percent ?? 0),
      render: (v: number | null) => v != null ? `${v}%` : '-' },
    { title: '隐含接种率(SP反推)', dataIndex: 'implied_coverage_from_sp_percent', key: 'implied_coverage_from_sp_percent', width: 150,
      sorter: (a: VaccineProvinceMatrixRow, b: VaccineProvinceMatrixRow) => (a.implied_coverage_from_sp_percent ?? 0) - (b.implied_coverage_from_sp_percent ?? 0),
      render: (v: number | null) => v != null ? `${v}%` : '-' },
    { title: '覆盖率状态', dataIndex: 'coverage_status', key: 'coverage_status', width: 110,
      render: (status: string) => {
        const meta = coverageStatusMeta[status] || coverageStatusMeta.undetermined;
        return <Tag color={meta.color}>{meta.label}</Tag>;
      }
    },
  ];

  const vaccineContent = (
    <Spin spinning={vaccineLoading}>
      {vaccineData ? (
        <>
          {/* 疾病选择器 */}
          {(() => { const vdr = vaccineData.per_disease_results || []; return vdr.length > 1; })() && (
            <Card style={{ marginBottom: 16 }}>
              <Space>
                <span style={{ fontWeight: 'bold' }}>选择分析疾病：</span>
                <Select
                  value={vaccineSelectedDisease || undefined}
                  style={{ minWidth: 200 }}
                  onChange={setVaccineSelectedDisease}
                  allowClear
                  placeholder="全部疾病（汇总视图）"
                  options={(vaccineData.per_disease_results || []).map((d) => ({
                    label: `${diseaseNameMap[d.disease] || d.disease} (${d.total_data_points}条数据)`,
                    value: d.disease,
                  }))}
                />
              </Space>
            </Card>
          )}

          {/* 概览统计卡片 */}
          {vaccineCurrentDisease && (
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={4}>
                <Card>
                  <Statistic
                    title={<span><SafetyCertificateOutlined style={{ color: '#52c41a' }} /> 整体血清阳性率</span>}
                    value={vaccineCurrentDisease.overall_weighted_sp ?? undefined}
                    suffix="%"
                    valueStyle={{ color: '#13c2c2' }}
                  />
                </Card>
              </Col>
              <Col span={4}>
                <Card>
                  <Statistic
                    title="群体免疫目标(HIT)"
                    value={vaccineCurrentDisease.herd_immunity_target_percent ?? undefined}
                    suffix="%"
                    valueStyle={{ color: '#1677ff' }}
                  />
                </Card>
              </Col>
              <Col span={4}>
                <Card>
                  <Statistic
                    title={
                      <span>
                        VE(抗感染)
                        <Tooltip title="VE=1-SP_vax/SP_unvax；当接种组阳性率更高(疫苗诱导抗体)时返回None">
                          <WarningOutlined style={{ color: '#8c8c8c', marginLeft: 4 }} />
                        </Tooltip>
                      </span>
                    }
                    value={vaccineCurrentDisease.ve_result?.ve_infection_percent ?? undefined}
                    suffix={vaccineCurrentDisease.ve_result?.ve_infection_percent != null ? '%' : ''}
                    valueStyle={{ color: vaccineCurrentDisease.ve_result?.ve_infection_percent != null ? '#52c41a' : '#8c8c8c' }}
                  />
                </Card>
              </Col>
              <Col span={4}>
                <Card>
                  <Statistic
                    title="NIP参考接种率(全国)"
                    value={vaccineCurrentDisease.coverage.nip_reference_national_percent ?? undefined}
                    suffix="%"
                    valueStyle={{ color: '#1677ff' }}
                  />
                </Card>
              </Col>
              <Col span={4}>
                <Card>
                  <Statistic
                    title={
                      <span>
                        隐含接种率(SP反推)
                        <Tooltip title="隐含接种率 ≈ 整体SP / HIT；保守近似，仅作参考">
                          <WarningOutlined style={{ color: '#8c8c8c', marginLeft: 4 }} />
                        </Tooltip>
                      </span>
                    }
                    value={vaccineCurrentDisease.coverage.implied_from_seroprevalence_percent ?? undefined}
                    suffix="%"
                    valueStyle={{ color: '#722ed1' }}
                  />
                </Card>
              </Col>
              <Col span={4}>
                <Card>
                  <Statistic
                    title="亚组拆分情况"
                    value={vaccineCurrentDisease.ve_result ? '已拆分' : '未找到亚组'}
                    valueStyle={{ color: vaccineCurrentDisease.ve_result ? '#52c41a' : '#fa8c16' }}
                  />
                </Card>
              </Col>
            </Row>
          )}

          {/* 备注说明 */}
          {vaccineData.notes.length > 0 && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 16 }}
              message={
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {vaccineData.notes.map((n, i) => <li key={i}>{n}</li>)}
                </ul>
              }
            />
          )}

          {/* 方法学说明 */}
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message={
              <>
                <strong>疫苗效力 VE 计算</strong>：尝试根据 DataPoint.population 字段中「已接种/未接种」关键词自动拆分亚组，VE = 1 - SP_vax / SP_unvax。
                <br />
                <strong>若 SP_vax ≥ SP_unvax</strong>（如疫苗诱导了抗体，接种组阳性率反而更高），则 VE 不适用，返回 None 并标注解读。
                <br />
                <strong>接种率双轨分析</strong>：NIP 参考接种率（国家免疫规划预设表）vs 隐含接种率（从整体 SP 反推，≈ SP / HIT），两者对照帮助发现接种盲区。
              </>
            }
          />

          {/* 上半部分：VE亚组对比 + 接种率双轨 */}
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={veCompareOption ? 12 : 24}>
              <ChartWithSnapshot
                title="接种率双轨分析（NIP参考 vs 隐含接种率 vs 阳性率）"
                token={tokenOf(vaccineData)}
                option={vaccineCoverageBarOption}
                height={380}
              >
                {!vaccineCoverageBarOption && <Empty description="暂无接种率数据" />}
              </ChartWithSnapshot>
            </Col>
            {veCompareOption && (
              <Col span={12}>
                <ChartWithSnapshot
                  title="亚组VE分析（已接种 vs 未接种）"
                  token={tokenOf(vaccineData)}
                  option={veCompareOption}
                  height={380}
                >
                  {vaccineCurrentDisease?.ve_result?.interpretation && (
                    <Alert
                      style={{ marginTop: 12 }}
                      type={vaccineCurrentDisease.ve_result.ve_infection_percent != null ? 'success' : 'info'}
                      showIcon
                      message={vaccineCurrentDisease.ve_result.interpretation}
                    />
                  )}
                  {vaccineCurrentDisease?.ve_result && (
                    <Row gutter={8} style={{ marginTop: 12 }}>
                      <Col span={12}>
                        <Card size="small" title="已接种组">
                          <Space direction="vertical">
                            <span>数据点：<strong>{vaccineCurrentDisease.ve_result.vaxxed_points}</strong></span>
                            <span>样本量：<strong>{vaccineCurrentDisease.ve_result.vaxxed_total_samples}</strong></span>
                          </Space>
                        </Card>
                      </Col>
                      <Col span={12}>
                        <Card size="small" title="未接种组">
                          <Space direction="vertical">
                            <span>数据点：<strong>{vaccineCurrentDisease.ve_result.unvaxxed_points}</strong></span>
                            <span>样本量：<strong>{vaccineCurrentDisease.ve_result.unvaxxed_total_samples}</strong></span>
                          </Space>
                        </Card>
                      </Col>
                    </Row>
                  )}
                </ChartWithSnapshot>
              </Col>
            )}
          </Row>

          {/* 省份覆盖率矩阵 */}
          <Card
            title={
              <Space>
                <span>省份 × 疫苗覆盖率矩阵（双轨）</span>
                <Tag color="green">{vaccineProvinceForDisease.length} 个省份</Tag>
              </Space>
            }
            extra={
              <Space wrap>
                {Object.entries(coverageStatusMeta).map(([k, v]) => (
                  <Tag key={k} color={v.color}>{v.label}</Tag>
                ))}
              </Space>
            }
          >
            {vaccineProvinceForDisease.length > 0 ? (
              <Table<VaccineProvinceMatrixRow>
                rowKey={(r) => `${r.disease}-${r.province}`}
                columns={vaccineProvinceColumns}
                dataSource={vaccineProvinceForDisease}
                size="small"
                pagination={{ pageSize: 15, showSizeChanger: true, pageSizeOptions: [15, 30, 50] }}
                scroll={{ x: 900 }}
              />
            ) : (
              <Empty description="暂无省份疫苗数据" />
            )}
          </Card>
        </>
      ) : (
        <Empty description="正在加载..." />
      )}
    </Spin>
  );

  // ===================== 中国地图 + 省份钻取 =====================

  const mapOption = mapReady ? {
    tooltip: {
      trigger: 'item',
      formatter: (p: { name: string }) => {
        const shortName = (Object.entries(PROVINCE_GEOJSON_NAME).find(([, v]) => v === p.name) || [null, p.name])[1];
        const item = mapData.find((d) => d.province === shortName);
        if (!item || item.weighted_positivity == null) return `${p.name}<br/>暂无数据`;
        return `<b>${shortName}</b><br/>加权阳性率: ${Number(item.weighted_positivity).toFixed(2)}%<br/>数据点数: ${item.point_count}<br/>总样本量: ${item.total_sample.toLocaleString()}<br/><br/><i>点击省份可钻取查看趋势 / 年龄曲线 / 数据质量</i>`;
      },
    },
    visualMap: {
      min: 0,
      max: 100,
      text: ['高', '低'],
      inRange: { color: ['#e8f5e9', '#66bb6a', '#26a69a', '#ffa726', '#ef5350'] },
      calculable: true,
      left: 'left',
      bottom: 20,
    },
    geo: {
      map: 'china',
      roam: true,
      label: { show: true, fontSize: 9, color: '#333' },
      itemStyle: { areaColor: '#f3f3f3', borderColor: '#ccc' },
      emphasis: { itemStyle: { areaColor: '#40a9ff' }, label: { show: true, fontWeight: 'bold' } },
    },
    series: [{
      type: 'map',
      map: 'china',
      geoIndex: 0,
      data: mapData
        .filter((d): d is MapDataPoint & { province: string } => !!d.province && !!PROVINCE_GEOJSON_NAME[d.province!])
        .map((d) => ({ name: PROVINCE_GEOJSON_NAME[d.province], value: d.weighted_positivity })),
      animationDuration: 500,
      animationEasing: 'cubicOut',
    }],
  } : null;

  // 钻取面板：选中省份的 趋势(带CI) + 年龄曲线 + 数据质量
  const mapDrillSection = (
    <Card
      size="small"
      title={<Space><EnvironmentOutlined /><span>中国地图（点击省份钻取）</span></Space>}
      style={{ marginTop: 16 }}
    >
      <Spin spinning={!mapReady || mapLoading}>
        {mapOption ? (
          <ReactECharts option={mapOption} style={{ height: 420 }} onEvents={{ click: handleProvinceClick }} />
        ) : (
          <Empty description="地图加载中..." style={{ padding: '60px 0' }} />
        )}
      </Spin>
      <div style={{ marginTop: 16 }}>
        {drillProvince ? (
          <Spin spinning={drillLoading}>
            <Alert
              type="success"
              showIcon
              closable
              onClose={() => setDrillProvince(null)}
              message={<span>已钻取省份：<b>{drillProvince}</b>（基于当前疾病筛选，可切换其他疾病后重新点击地图）</span>}
              style={{ marginBottom: 12 }}
            />
            <Row gutter={16}>
              <Col span={12}>
                <TrendWithCI
                  data={drillTrend}
                  title={`${drillProvince} 血清阳性率趋势（95% CI）`}
                  yLabel="阳性率 (%)"
                  height={300}
                />
              </Col>
              <Col span={12}>
                <AgeCurveChart
                  data={drillAgeCurve}
                  loading={drillLoading}
                  title={`${drillProvince} 年龄-阳性率曲线`}
                  height={300}
                />
              </Col>
            </Row>
            <Row gutter={16} style={{ marginTop: 16 }}>
              <Col span={24}>
                <QualityPanel data={drillQuality} loading={drillLoading} compact />
              </Col>
            </Row>
          </Spin>
        ) : (
          <Empty description="点击地图上的省份，钻取查看该省的趋势 / 年龄曲线 / 数据质量" style={{ padding: '30px 0' }} />
        )}
      </div>
    </Card>
  );

  // ===================== 公平性分析内容 =====================

  const equityContent = (
    <Spin spinning={equityLoading}>
      {equityData ? (
        <>
          <KpiCards
            items={[
              { label: '参与省份', value: equityData.summary?.total_provinces ?? equityData.n_provinces, tip: '有已审核主估计的省份数' },
              { label: '数据点总数', value: equityData.n_data_points },
              { label: '基尼系数', value: equityData.summary?.gini != null ? equityData.summary.gini : '-', precision: 3, tip: 'Gini 越接近 0，省际越公平' },
              { label: '变异系数', value: equityData.summary?.coefficient_of_variation != null ? equityData.summary.coefficient_of_variation : '-', precision: 3 },
              { label: '达标省份', value: equityData.summary?.meeting_provinces_count ?? 0, suffix: equityData.summary?.total_provinces ? ` / ${equityData.summary.total_provinces}` : undefined, valueStyle: { color: '#52c41a' }, tip: '加权阳性率 ≥ 目标阈值的省份数' },
            ]}
          />
          <Row gutter={16}>
            <Col span={24}>
              <EquityRadar selectedDisease={appliedDisease} selectedProvince={drillProvince} />
            </Col>
          </Row>
          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col span={24}>
              <TopBottomRank data={equityData} />
            </Col>
          </Row>
          {equityData.notes?.length > 0 && (
            <Alert type="info" showIcon style={{ marginTop: 12 }} message={equityData.notes.join('；')} />
          )}
        </>
      ) : (
        <Empty description="暂无公平性分析数据，请选择疾病后点击查询" style={{ padding: '60px 0' }} />
      )}
    </Spin>
  );

  // ===================== 数据质量分析内容 =====================

  const qualityContent = (
    <>
      <KpiCards
        loading={qualityLoading}
        items={[
          { label: '主估计总数', value: qualityData?.total_estimates ?? null },
          { label: '覆盖省份', value: qualityData?.n_provinces ?? null },
          { label: '高质量占比 (A+B)', value: qualityData?.summary ? qualityData.summary.high_quality_ratio * 100 : null, precision: 1, suffix: '%' },
          { label: '带 95%CI 占比', value: qualityData?.summary ? qualityData.summary.with_ci_ratio * 100 : null, precision: 1, suffix: '%' },
          { label: '原文溯源占比', value: qualityData?.summary ? qualityData.summary.grounded_ratio * 100 : null, precision: 1, suffix: '%' },
        ]}
      />
      <QualityPanel data={qualityData} loading={qualityLoading} />
    </>
  );

  // ===================== 目标达成分析内容 =====================

  const goalContent = (
    <GoalTrackingChart data={goalData} loading={goalLoading} />
  );

  // ===================== 高级分析内容（年龄曲线 / meta / assay / 模拟） =====================

  const metaColumns = [
    { title: '省份', dataIndex: 'province', key: 'province', width: 90, fixed: 'left' as const },
    { title: '研究数 k', dataIndex: 'k', key: 'k', width: 70 },
    { title: '固定效应合并', dataIndex: 'pooled_fixed_percent', key: 'pooled_fixed_percent', width: 100, render: (v: number | null) => v != null ? `${v.toFixed(2)}%` : '-' },
    { title: '随机效应合并', dataIndex: 'pooled_random_percent', key: 'pooled_random_percent', width: 100, render: (v: number | null) => v != null ? `${v.toFixed(2)}%` : '-' },
    { title: 'I² (%)', dataIndex: 'i_squared_percent', key: 'i_squared_percent', width: 70, render: (v: number) => <b style={{ color: v >= 75 ? '#f5222d' : v >= 50 ? '#fa8c16' : '#52c41a' }}>{v.toFixed(1)}</b> },
    { title: 'Q', dataIndex: 'q_statistic', key: 'q_statistic', width: 70, render: (v: number | null) => v != null ? v.toFixed(2) : '-' },
    { title: 'τ²', dataIndex: 'tau_squared', key: 'tau_squared', width: 70, render: (v: number | null) => v != null ? v.toFixed(4) : '-' },
    {
      title: '异质性',
      dataIndex: 'heterogeneity',
      key: 'heterogeneity',
      width: 80,
      render: (v: HeterogeneityLevel) => {
        const meta: Record<HeterogeneityLevel, [string, string]> = { low: ['低', 'green'], moderate: ['中', 'gold'], high: ['高', 'red'], 'n/a': ['N/A', 'default'] };
        const [label, color] = meta[v] || ['-', 'default'];
        return <Tag color={color}>{label}</Tag>;
      },
    },
  ];

  const assayColumns = [
    { title: '检测方法', dataIndex: 'assay', key: 'assay', width: 150 },
    { title: '研究数', dataIndex: 'n_studies', key: 'n_studies', width: 80 },
    { title: '样本量', dataIndex: 'total_samples', key: 'total_samples', width: 100, render: (v: number) => v.toLocaleString() },
    { title: '加权阳性率', dataIndex: 'weighted_positivity', key: 'weighted_positivity', width: 110, render: (v: number | null) => v != null ? `${v.toFixed(2)}%` : '-' },
    { title: '95% CI', key: 'ci', width: 140, render: (_: unknown, r: AssayHeterogeneityRow) => r.ci_lower != null && r.ci_upper != null ? `${r.ci_lower.toFixed(1)} ~ ${r.ci_upper.toFixed(1)}` : '-' },
  ];

  const advancedContent = (
    <Spin spinning={ageCurveLoading || metaLoading || assayLoading || simLoading}>
      <Row gutter={16}>
        <Col span={24}>
          <AgeCurveChart
            data={ageCurveData}
            loading={ageCurveLoading}
          />
        </Col>
      </Row>
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={12}>
          <Card size="small" title={<Space><span>Meta 合并（省级，I² 异质性）</span><Tag color="blue">逆方差加权</Tag></Space>}>
            {metaData && metaData.results.length > 0 ? (
              <Table<MetaMergeProvinceResult>
                rowKey="province"
                size="small"
                pagination={false}
                scroll={{ x: 700 }}
                dataSource={metaData.results}
                columns={metaColumns}
              />
            ) : (
              <Empty description="暂无 Meta 合并结果（需同省多研究已审核主估计）" />
            )}
            {metaData?.notes?.length ? <Alert type="info" showIcon style={{ marginTop: 8 }} message={metaData.notes.join('；')} /> : null}
          </Card>
        </Col>
        <Col span={12}>
          <Card size="small" title={<Space><span>检测方法（Assay）异质性</span><Tag color="purple">跨方法对比</Tag></Space>}>
            {assayData && assayData.results.length > 0 ? (
              <>
                <Alert
                  type={assayData.across_assay_i_squared_percent >= 75 ? 'warning' : assayData.across_assay_i_squared_percent >= 50 ? 'info' : 'success'}
                  showIcon
                  style={{ marginBottom: 12 }}
                  message={`跨 Assay I² = ${assayData.across_assay_i_squared_percent.toFixed(1)}%（Q=${assayData.across_assay_q_statistic != null ? assayData.across_assay_q_statistic.toFixed(2) : '-'}，k=${assayData.across_assay_k}）`}
                />
                <Table<AssayHeterogeneityRow>
                  rowKey="assay"
                  size="small"
                  pagination={false}
                  dataSource={assayData.results}
                  columns={assayColumns}
                />
              </>
            ) : (
              <Empty description="暂无 Assay 异质性数据" />
            )}
            {assayData?.notes?.length ? <Alert type="info" showIcon style={{ marginTop: 8 }} message={assayData.notes.join('；')} /> : null}
          </Card>
        </Col>
      </Row>
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={24}>
          <SimulationPanel
            data={simData}
            loading={simLoading}
            coverage={simCoverage}
            booster={simBooster}
            onCoverageChange={setSimCoverage}
            onBoosterChange={setSimBooster}
            onRun={() => fetchSimulation(simCoverage, simBooster)}
          />
        </Col>
      </Row>
    </Spin>
  );

  // ===================== 证据合成内容（Meta 分析） =====================

  // 渲染单个亚组的：合并摘要卡片 → 森林图 → 漏斗图（无则隐藏）
  const renderMetaGroup = (g: MetaAnalysisGroup, key: string) => {
    const meta = g.meta;
    const pooled = meta.pooled;
    const k = pooled.k;

    // 空状态：k<2，未进行合并，降级展示单项 CI
    if (k < 2) {
      const s = meta.per_study[0];
      const ci = s ? wilsonCi(s.x, s.n) : null;
      return (
        <Card size="small" style={{ marginBottom: 16 }} key={key}>
          <Alert
            type="warning"
            showIcon
            message="当前筛选仅 1 项研究，未进行合并"
            description={
              s
                ? `单项研究：${s.label} —— 阳性率 ${(s.p * 100).toFixed(1)}%（95% CI: ${(ci ? ci.lower * 100 : 0).toFixed(1)}% – ${(ci ? ci.upper * 100 : 0).toFixed(1)}%）`
                : undefined
            }
          />
        </Card>
      );
    }

    const studies = meta.per_study.map((s) => {
      const ci = wilsonCi(s.x, s.n);
      return {
        label: s.label,
        p: s.p * 100,
        ci_lower: ci.lower * 100,
        ci_upper: ci.upper * 100,
        weight: s.weight,
      };
    });

    const forestOption = forestPlotOption(studies, {
      rate: pooled.rate,
      ci_lower: pooled.ci_lower,
      ci_upper: pooled.ci_upper,
      model: pooled.model,
      tau2: pooled.tau2,
      Q: pooled.Q,
      Q_p: pooled.Q_p,
      I2: pooled.I2,
      k: pooled.k,
    });

    const tCenter =
      pooled.n_rep != null && pooled.rate != null ? ftTransform(pooled.rate / 100, pooled.n_rep) : null;
    const funnelOption =
      meta.funnel && meta.funnel.length > 0 ? funnelPlotOption(meta.funnel, meta.egger, tCenter) : null;

    const groupTitle = g.group === 'all' ? '整体合并' : `亚组：${g.group}`;

    return (
      <div key={key}>
        <Card size="small" style={{ marginBottom: 16 }}>
          <Row gutter={16} align="middle">
            <Col>
              <span style={{ fontSize: 13, color: '#666' }}>{groupTitle}</span>
            </Col>
            <Col flex="auto">
              <Space size="large" wrap>
                <Statistic
                  title="合并率"
                  value={pooled.rate ?? 0}
                  precision={pooled.rate != null ? 1 : 0}
                  suffix="%"
                />
                <Statistic
                  title="95% CI"
                  value={
                    pooled.ci_lower != null && pooled.ci_upper != null
                      ? `${pooled.ci_lower.toFixed(1)}% – ${pooled.ci_upper.toFixed(1)}%`
                      : '—'
                  }
                  valueStyle={{ fontSize: 18 }}
                />
                <Statistic
                  title="I²"
                  value={pooled.I2}
                  precision={1}
                  suffix="%"
                  valueStyle={{
                    color: pooled.I2 >= 75 ? '#cf1322' : pooled.I2 >= 50 ? '#d46b08' : '#389e0d',
                  }}
                />
              </Space>
            </Col>
          </Row>
        </Card>
        <ChartWithSnapshot
          title={`森林图 — ${groupTitle}`}
          token={tokenOf(metaAnalysisData)}
          option={forestOption}
          height={Math.max(280, 60 + studies.length * 32)}
        />
        {funnelOption && (
          <ChartWithSnapshot
            title={`漏斗图 — ${groupTitle}`}
            token={tokenOf(metaAnalysisData)}
            option={funnelOption}
            height={320}
          />
        )}
      </div>
    );
  };

  const metaAnalysisContent = (
    <Spin spinning={metaAnalysisLoading}>
      {!appliedDisease ? (
        <Empty description="请先在上方筛选面板选择疾病后查看证据合成" style={{ padding: '40px 0' }} />
      ) : !metaAnalysisData || metaAnalysisData.groups.length === 0 ? (
        <Empty description="当前筛选无符合质量要求（A+B 级）的研究数据" style={{ padding: '40px 0' }} />
      ) : (
        <>
          <Space style={{ marginBottom: 16 }}>
            <span style={{ fontWeight: 'bold' }}>亚组：</span>
            <Segmented
              options={[
                { label: '整体', value: '' },
                { label: '按省', value: 'province' },
                { label: '按年份', value: 'year' },
                { label: '按年龄段', value: 'age_group' },
              ]}
              value={metaGroupBy}
              onChange={(v) => setMetaGroupBy(v as string)}
            />
          </Space>
          {metaAnalysisData.groups.map((g, i) => renderMetaGroup(g, `${g.group}_${i}`))}
        </>
      )}
    </Spin>
  );

  // ===================== 出生队列内容（热力图 + 队列轨迹折线） =====================
  const birthCohortContent = (
    <Spin spinning={birthCohortLoading}>
      {!appliedDisease ? (
        <Empty description="请先在上方筛选面板选择疾病后查看出生队列" style={{ padding: '40px 0' }} />
      ) : !birthCohortData || birthCohortData.cohorts.length === 0 ? (
        <Empty description="当前筛选无有效数据（无法推算出生年份或被剔除）" style={{ padding: '40px 0' }} />
      ) : (
        <>
          {birthCohortData.disease_note ? (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
              message={birthCohortData.disease_note}
            />
          ) : null}
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="同一颜色斜向带提示队列效应（该代人持续低免疫）"
          />
          <ChartWithSnapshot
            title="出生队列热力图（x=调查年, y=出生年代, 值=加权阳性率）"
            token={tokenOf(birthCohortData)}
            option={birthCohortHeatmapOption(
              '出生队列热力图（x=调查年, y=出生年代, 值=加权阳性率）',
              birthCohortData.matrix,
              birthCohortData.x_years,
              birthCohortData.y_bands,
            )}
            height={Math.max(320, birthCohortData.y_bands.length * 48 + 80)}
          />
          <ChartWithSnapshot
            title="各出生队列阳性率随调查年轨迹"
            token={tokenOf(birthCohortData)}
            option={birthCohortLinesOption(
              '各出生队列阳性率随调查年轨迹',
              birthCohortData.cohorts,
            )}
            height={380}
          />
          <div style={{ marginTop: 12, color: '#888', fontSize: 12 }}>
            数据点：{birthCohortData.meta.n_records}，剔除（无法推算出生年份）：{birthCohortData.meta.dropped}；每格需 ≥
            {birthCohortData.meta.min_cell_points} 个数据点，不足置空。
          </div>
        </>
      )}
    </Spin>
  );

  return (
    <>
      {filterPanel}
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'summary',
            label: '汇总分析',
            children: (
              <>
                {summaryContent}
                {mapDrillSection}
              </>
            ),
          },
          {
            key: 'datapoints',
            label: '数据点可视化',
            children: datapointsContent,
          },
          {
            key: 'coverage',
            label: '数据覆盖度',
            children: coverageContent,
          },
          {
            key: 'ageCurve',
            label: (
              <span>
                <LineChartOutlined />
                年龄曲线
              </span>
            ),
            children: (
              <Spin spinning={ageCurveLoading}>
                {!appliedDisease ? (
                  <Empty description="请先在上方筛选面板选择疾病后查看年龄曲线" style={{ padding: '40px 0' }} />
                ) : (
                  <AgeCurveChart data={ageCurveData} loading={ageCurveLoading} />
                )}
              </Spin>
            ),
          },
          {
            key: 'foi',
            label: (
              <span>
                <ExperimentOutlined />
                FOI感染力分析
              </span>
            ),
            children: foiContent,
          },
          {
            key: 'vaccine',
            label: (
              <span>
                <SafetyCertificateOutlined />
                疫苗效力与接种率
              </span>
            ),
            children: vaccineContent,
          },
          {
            key: 'advanced',
            label: (
              <span>
                <BarChartOutlined />
                高级图表
              </span>
            ),
            children: (
              <AdvancedCharts
                appliedDisease={appliedDisease}
                appliedDataType={appliedDataType}
                appliedProvinces={appliedProvinces}
              />
            ),
          },
          {
            key: 'equity',
            label: (
              <span>
                <FundOutlined />
                公平性分析
              </span>
            ),
            children: equityContent,
          },
          {
            key: 'quality',
            label: (
              <span>
                <CheckCircleOutlined />
                数据质量
              </span>
            ),
            children: qualityContent,
          },
          {
            key: 'goal',
            label: (
              <span>
                <AimOutlined />
                目标达成
              </span>
            ),
            children: goalContent,
          },
          {
            key: 'advancedAnalysis',
            label: (
              <span>
                <ExperimentOutlined />
                高级分析
              </span>
            ),
            children: advancedContent,
          },
          {
            key: 'metaAnalysis',
            label: (
              <span>
                <ExperimentOutlined />
                证据合成
              </span>
            ),
            children: metaAnalysisContent,
          },
          {
            key: 'birthCohort',
            label: (
              <span>
                <LineChartOutlined />
                出生队列
              </span>
            ),
            children: birthCohortContent,
          },
        ]}
      />
    </>
  );
};

export default Analysis;
