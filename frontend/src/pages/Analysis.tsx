import React, { useState, useCallback, useEffect } from 'react';
import { Card, Row, Col, Spin, Empty, message, Button, Tabs, Table, Space, Statistic, Alert, Tag, Collapse, Tooltip } from 'antd';
import { SearchOutlined, WarningOutlined, CheckCircleOutlined, FileSearchOutlined } from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import DiseaseSelector from '../components/DiseaseSelector';
import ProvinceSelector from '../components/ProvinceSelector';
import MapSelector from '../components/MapSelector';
import { getTrend, getRegionCompare, getAgeStratify, getApprovedDataPoints, getDataGapAnalysis } from '../services/map';
import { useFilterStore } from '../store';
import type { TableRowSelection } from 'antd/es/table/interface';
import type { DataGapAnalysisResult, ReviewNeededItem, DataGapItem, ProvinceYearRow } from '../types';
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

  // 获取数据覆盖度分析
  const fetchGapData = useCallback(async () => {
    setGapLoading(true);
    try {
      const params: Record<string, unknown> = {};
      if (appliedDisease) params.disease = appliedDisease;
      const data = await getDataGapAnalysis(Object.keys(params).length > 0 ? params : undefined);
      setGapData(data);
    } catch {
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
    } catch {
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
  }, [activeTab]);

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
    sorter: { field?: string; order?: string | null },
  ) => {
    const page = pagination.current || 1;
    const pageSize = pagination.pageSize || 50;
    setDpPage(page);
    setDpPageSize(pageSize);

    let sortBy: string | undefined;
    let sortOrder: string | undefined;
    if (sorter.order) {
      sortBy = sorter.field as string;
      sortOrder = sorter.order === 'ascend' ? 'asc' : 'desc';
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

  // 热力图单元格背景色（根据数据点数量）
  const getCellBg = (total: number) => {
    if (total === 0) return 'transparent';
    if (total <= 2) return '#fff7e6';
    if (total <= 5) return '#ffe7ba';
    if (total <= 10) return '#ffd591';
    if (total <= 20) return '#ffa940';
    return '#fa541c';
  };

  const reviewColumns = [
    {
      title: '省份', dataIndex: 'province', key: 'province', width: 100,
      sorter: (a: ReviewNeededItem, b: ReviewNeededItem) => a.province.localeCompare(b.province),
    },
    {
      title: '年份', dataIndex: 'year', key: 'year', width: 80,
      sorter: (a: ReviewNeededItem, b: ReviewNeededItem) => (a.year || 0) - (b.year || 0),
      render: (v: number | null) => v || '-',
    },
    {
      title: '疾病', dataIndex: 'disease', key: 'disease', width: 100,
      render: (v: string) => diseaseNameMap[v] || v,
    },
    {
      title: '待审核', dataIndex: 'pending_count', key: 'pending_count', width: 90,
      sorter: (a: ReviewNeededItem, b: ReviewNeededItem) => a.pending_count - b.pending_count,
      defaultSortOrder: 'descend' as const,
      render: (v: number) => <Tag color={v >= 10 ? 'red' : v >= 5 ? 'orange' : 'default'}>{v}</Tag>,
    },
    { title: '已通过', dataIndex: 'approved_count', key: 'approved_count', width: 80 },
    { title: '已驳回', dataIndex: 'rejected_count', key: 'rejected_count', width: 80 },
    { title: '总计', dataIndex: 'total_count', key: 'total_count', width: 80 },
  ];

  // 构建热力图表格列
  const allYears = gapData?.overview.years || [];
  const heatmapColumns = [
    {
      title: '省份',
      dataIndex: 'province',
      key: 'province',
      width: 80,
      fixed: 'left' as const,
      sorter: (a: ProvinceYearRow, b: ProvinceYearRow) => a.province.localeCompare(b.province),
    },
    {
      title: '总计',
      dataIndex: 'total',
      key: 'total',
      width: 60,
      fixed: 'left' as const,
      sorter: (a: ProvinceYearRow, b: ProvinceYearRow) => a.total - b.total,
      render: (v: number) => <strong>{v}</strong>,
    },
    ...allYears.map((year) => ({
      title: String(year),
      key: String(year),
      width: 60,
      align: 'center' as const,
      render: (_: unknown, record: ProvinceYearRow) => {
        const cell = record.years[String(year)];
        if (!cell || cell.total === 0) {
          return <span style={{ color: '#ccc' }}>-</span>;
        }
        const bg = getCellBg(cell.total);
        const hasPending = cell.pending > 0;
        return (
          <Tooltip title={`总计: ${cell.total} | 待审核: ${cell.pending} | 已通过: ${cell.approved}`}>
            <div style={{
              background: bg,
              borderRadius: 3,
              padding: '2px 6px',
              textAlign: 'center',
              cursor: 'pointer',
              border: hasPending ? '1px solid #ff4d4f' : '1px solid transparent',
            }}>
              <span style={{ fontSize: 12, fontWeight: hasPending ? 'bold' : 'normal' }}>
                {cell.total}
              </span>
            </div>
          </Tooltip>
        );
      },
    })),
  ];

  const coverageContent = (
    <Spin spinning={gapLoading}>
      {gapData ? (
        <>
          {/* 概览统计卡片 */}
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={6}>
              <Card>
                <Statistic
                  title="总数据点"
                  value={gapData.overview.total_data_points}
                  prefix={<FileSearchOutlined />}
                />
              </Card>
            </Col>
            <Col span={6}>
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
            <Col span={6}>
              <Card>
                <Statistic
                  title="待审核数据点"
                  value={gapData.overview.pending_count}
                  valueStyle={{ color: gapData.overview.pending_count > 0 ? '#fa541c' : '#52c41a' }}
                  prefix={<WarningOutlined />}
                />
              </Card>
            </Col>
            <Col span={6}>
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

          {/* 年份范围信息 */}
          {gapData.overview.year_range && (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
              message={`数据覆盖年份范围：${gapData.overview.year_range[0]} - ${gapData.overview.year_range[1]}，共 ${gapData.overview.years.length} 个年份，涉及 ${gapData.overview.total_diseases} 种疾病`}
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
            >
              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 12 }}
                message="以下省份和年份的数据点尚未完成审核，请前往文献详情页审核后才能纳入分析统计"
              />
              <Table
                rowKey={(r: ReviewNeededItem) => `${r.province}-${r.year}-${r.disease}`}
                columns={reviewColumns}
                dataSource={gapData.review_needed}
                size="small"
                pagination={{ pageSize: 10, showSizeChanger: true, pageSizeOptions: [10, 20, 50] }}
                scroll={{ x: 600 }}
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

          {/* 数据缺失提醒 */}
          {gapData.data_gaps.length > 0 ? (
            <Card
              title={
                <Space>
                  <WarningOutlined style={{ color: '#fa8c16' }} />
                  <span>数据缺失提醒（按疾病分组）</span>
                </Space>
              }
              style={{ marginBottom: 16 }}
            >
              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 12 }}
                message="以下疾病在部分省份完全没有数据，建议补充相关文献和数据提取"
              />
              <Collapse
                items={gapData.data_gaps.map((g: DataGapItem) => ({
                  key: g.disease,
                  label: (
                    <Space>
                      <span style={{ fontWeight: 'bold' }}>{diseaseNameMap[g.disease] || g.disease}</span>
                      <Tag color="green">已覆盖 {g.covered_count} 省</Tag>
                      <Tag color="red">缺失 {g.missing_count} 省</Tag>
                    </Space>
                  ),
                  children: (
                    <div>
                      <p style={{ marginBottom: 8, color: '#888' }}>
                        建议补充以下 {g.missing_count} 个省份的{diseaseNameMap[g.disease] || g.disease}相关数据：
                      </p>
                      <Space wrap>
                        {g.missing_provinces.map((p) => (
                          <Tag key={p} color="orange" style={{ marginBottom: 4 }}>{p}</Tag>
                        ))}
                      </Space>
                      <div style={{ marginTop: 12 }}>
                        <span style={{ color: '#52c41a', fontSize: 13 }}>已有数据省份：</span>
                        <Space wrap size={[4, 4]} style={{ marginTop: 4 }}>
                          {g.covered_provinces.map((p) => (
                            <Tag key={p} color="blue">{p}</Tag>
                          ))}
                        </Space>
                      </div>
                    </div>
                  ),
                }))}
              />
            </Card>
          ) : (
            <Card style={{ marginBottom: 16 }}>
              <Alert type="success" showIcon message="所有疾病均已覆盖所有省份，无数据缺失" />
            </Card>
          )}

          {/* 省份×年份热力图 */}
          <Card
            title="省份 × 年份数据点分布热力图"
            extra={
              <Space>
                <Tag color="default">无数据</Tag>
                <Tag style={{ background: '#fff7e6', border: '1px solid #ffd591' }}>1-2</Tag>
                <Tag style={{ background: '#ffe7ba', border: '1px solid #ffd591' }}>3-5</Tag>
                <Tag style={{ background: '#ffd591', border: '1px solid #ffa940' }}>6-10</Tag>
                <Tag style={{ background: '#ffa940', border: '1px solid #fa541c' }}>11-20</Tag>
                <Tag style={{ background: '#fa541c', color: '#fff' }}>{'>20'}</Tag>
                <Tag color="red">红框=有待审核</Tag>
              </Space>
            }
          >
            {gapData.province_year_matrix.length > 0 ? (
              <Table
                rowKey="province"
                columns={heatmapColumns}
                dataSource={gapData.province_year_matrix}
                size="small"
                pagination={false}
                scroll={{ x: 80 + 60 + allYears.length * 60 }}
              />
            ) : (
              <Empty description="暂无数据" />
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
        ]}
      />
    </>
  );
};

export default Analysis;
