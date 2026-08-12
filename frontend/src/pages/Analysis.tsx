import React, { useState, useCallback, useEffect } from 'react';
import { Card, Row, Col, Spin, Empty, message, Button, Tabs, Table, Space, Statistic, Alert, Tag, Collapse, Tooltip, Progress, Select } from 'antd';
import { SearchOutlined, WarningOutlined, CheckCircleOutlined, FileSearchOutlined, DownloadOutlined, ExperimentOutlined, SafetyCertificateOutlined } from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import DiseaseSelector from '../components/DiseaseSelector';
import ProvinceSelector from '../components/ProvinceSelector';
import MapSelector from '../components/MapSelector';
import { getTrend, getRegionCompare, getAgeStratify, getApprovedDataPoints, getDataGapAnalysis, getFoiHerdImmunity, getVaccineEffectivenessCoverage } from '../services/map';
import { useFilterStore } from '../store';
import type { TableRowSelection } from 'antd/es/table/interface';
import type { DataGapAnalysisResult, DataGapItem, ProvinceYearRow, FoiHerdImmunityResult, VaccineEffectivenessCoverageResult, FoiProvinceMatrixRow, VaccineProvinceMatrixRow, FoiPerDiseaseResult, VaccinePerDiseaseResult } from '../types';
import { DISEASES } from '../utils/constants';

type DataItem = Record<string, unknown>;

const Analysis: React.FC = () => {
  const { disease: globalDisease, dataType: globalDataType, setDisease, setDataType } = useFilterStore();

  // 本地筛选状态
  const [localDisease, setLocalDisease] = useState(globalDisease);
  const [localDataType, setLocalDataType] = useState(globalDataType);
  const [province, setProvince] = useState('');

  // 实际查询参数
  const [appliedDisease, setAppliedDisease] = useState('');
  const [appliedDataType, setAppliedDataType] = useState('');
  const [appliedProvince, setAppliedProvince] = useState('');

  const [loading, setLoading] = useState(false);
  const [trendData, setTrendData] = useState<DataItem[]>([]);
  const [regionData, setRegionData] = useState<DataItem[]>([]);
  const [ageData, setAgeData] = useState<DataItem[]>([]);

  // 审核通过的数据点
  const [approvedData, setApprovedData] = useState<DataItem[]>([]);
  const [approvedTotal, setApprovedTotal] = useState(0);
  const [approvedLoading, setApprovedLoading] = useState(false);
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [selectedRows, setSelectedRows] = useState<DataItem[]>([]);
  const [activeTab, setActiveTab] = useState('summary');
  const [dpPage, setDpPage] = useState(1);
  const [dpPageSize, setDpPageSize] = useState(50);
  const [dpSortBy, setDpSortBy] = useState<string | undefined>(undefined);
  const [dpSortOrder, setDpSortOrder] = useState<string | undefined>(undefined);

  // 数据覆盖度分析
  const [gapData, setGapData] = useState<DataGapAnalysisResult | null>(null);
  const [gapLoading, setGapLoading] = useState(false);

  // FOI（感染力）+ 群体免疫阈值分析
  const [foiData, setFoiData] = useState<FoiHerdImmunityResult | null>(null);
  const [foiLoading, setFoiLoading] = useState(false);
  const [foiSelectedDisease, setFoiSelectedDisease] = useState<string>('');

  // 疫苗效果 VE + 接种率分析
  const [vaccineData, setVaccineData] = useState<VaccineEffectivenessCoverageResult | null>(null);
  const [vaccineLoading, setVaccineLoading] = useState(false);
  const [vaccineSelectedDisease, setVaccineSelectedDisease] = useState<string>('');

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
    } catch (err) {
      console.error('[Analysis] 数据加载失败:', err);
      message.error('数据加载失败');
    } finally {
      setLoading(false);
    }
  }, [appliedDisease, appliedDataType, appliedProvince]);

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

  // 获取 FOI 感染力 + 群体免疫阈值分析
  const fetchFoiData = useCallback(async () => {
    setFoiLoading(true);
    try {
      const params: Record<string, unknown> = {};
      if (appliedDisease) params.disease = appliedDisease;
      if (appliedProvince) params.province = appliedProvince;
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
  }, [appliedDisease, appliedProvince]);

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
      if (appliedProvince) params.province = appliedProvince;
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
  }, [appliedDisease, appliedProvince]);

  useEffect(() => {
    if (activeTab === 'vaccine') {
      fetchVaccineData();
    }
  }, [activeTab, fetchVaccineData]);

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
      if (appliedProvince) params.province = appliedProvince;
      if (sortBy) { params.sort_by = sortBy; params.sort_order = sortOrder || 'desc'; }

      const res = await getApprovedDataPoints(params);
      const data = res as { items: DataItem[]; total: number };
      setApprovedData(data.items || []);
      setApprovedTotal(data.total || 0);
    } catch (err) {
      console.error('[Analysis] 数据点加载失败:', err);
      message.error('数据点加载失败');
    } finally {
      setApprovedLoading(false);
    }
  }, [appliedDisease, appliedDataType, appliedProvince]);

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
    setAppliedProvince(province);
    // 清除已选数据点
    setSelectedRowKeys([]);
    setSelectedRows([]);
  };

  // ===================== 汇总分析图表 =====================

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
        <Col><ProvinceSelector value={province} onChange={setProvince} /></Col>
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
            if (province) params.set('province', province);
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
            if (province) params.set('province', province);
            window.open(`/api/v1/analysis/dataset-snapshot?${params.toString()}`);
          }}>
            数据集快照
          </Button>
        </Col>
      </Row>
    </Card>
  );

  // ===================== 汇总分析内容 =====================

  const summaryContent = (
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
            <Card>
              {selectedBarOption ? <ReactECharts option={selectedBarOption} style={{ height: 400 }} /> : <Empty description="请先选择数据点" />}
            </Card>
          </Col>
          {scatterOption && (
            <Col span={12}>
              <Card>
                <ReactECharts option={scatterOption} style={{ height: 400 }} />
              </Card>
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
                <Card
                  title={
                    <Space>
                      <span>年龄组 FOI 分析</span>
                      <Tag color="blue">{foiCurrentDisease.foi_by_age_group.length} 个年龄组</Tag>
                    </Space>
                  }
                >
                  {foiAgeOption ? (
                    <ReactECharts option={foiAgeOption} style={{ height: 400 }} />
                  ) : (
                    <Empty description="暂无足够年龄组数据进行FOI分析" />
                  )}
                </Card>
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
              <Card
                title={
                  <Space>
                    <span>接种率双轨分析</span>
                    <Tag color="blue">NIP参考 vs 隐含接种率 vs 阳性率</Tag>
                  </Space>
                }
              >
                {vaccineCoverageBarOption ? (
                  <ReactECharts option={vaccineCoverageBarOption} style={{ height: 380 }} />
                ) : (
                  <Empty description="暂无接种率数据" />
                )}
              </Card>
            </Col>
            {veCompareOption && (
              <Col span={12}>
                <Card
                  title={
                    <Space>
                      <span>亚组VE分析</span>
                      <Tag color="green">已接种 vs 未接种</Tag>
                    </Space>
                  }
                >
                  <ReactECharts option={veCompareOption} style={{ height: 380 }} />
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
                </Card>
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
            children: summaryContent,
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
        ]}
      />
    </>
  );
};

export default Analysis;
