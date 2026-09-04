import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import {
  Card, Row, Col, Select, Slider, Button, Spin, Empty, Alert, Drawer, Descriptions,
  Tag, Statistic, Space, Divider, message, Input, Tabs, List, Typography, Steps,
  Modal, InputNumber,
} from 'antd';
import {
  ReloadOutlined, ApartmentOutlined, SearchOutlined, NodeIndexOutlined,
  ThunderboltOutlined, MessageOutlined, NumberOutlined,
} from '@ant-design/icons';
import EChart from '../components/EChart';
import LiteraturePicker from '../components/LiteraturePicker';
import {
  getKgOverview, getKgOptions, getKgGraph,
  searchKgEntities, queryKgPath, getKgStats, triggerKgExtraction,
  askKgQuestion,
} from '../services/knowledgeGraph';
import { getTaskStatus } from '../services/system';
import type {
  KgGraphData, KgNode, KgOverviewData, KgOptionsData,
  KgSearchResult, KgPathResult, KgStatsData,
} from '../types';

const { Text, Link: TextLink } = Typography;

// ===== 实体类型元信息（颜色/分类标签/是否为主要维度节点）=====
const ENTITY_META: Record<string, { type: string; label: string; color: string; dimension: boolean }> = {
  survey: { type: 'survey', label: '调查', color: '#8c8c8c', dimension: false },
  pathogen: { type: 'pathogen', label: '病原体', color: '#f5222d', dimension: true },
  geo_area: { type: 'geo_area', label: '地区', color: '#52c41a', dimension: true },
  time_period: { type: 'time_period', label: '时期', color: '#fa8c16', dimension: true },
  host_group: { type: 'host_group', label: '人群', color: '#722ed1', dimension: true },
  lab_assay: { type: 'lab_assay', label: '检测方法', color: '#13c2c2', dimension: true },
  indicator: { type: 'indicator', label: '指标', color: '#eb2f96', dimension: false },
  institution: { type: 'institution', label: '实施单位', color: '#2f54eb', dimension: false },
  author: { type: 'author', label: '作者', color: '#eb2f96', dimension: false },
  sample: { type: 'sample', label: '样本', color: '#a0d911', dimension: false },
  vaccine: { type: 'vaccine', label: '疫苗', color: '#36cfc9', dimension: false },
  data_quality: { type: 'data_quality', label: '数据质量', color: '#faad14', dimension: false },
  publication: { type: 'publication', label: '出版物', color: '#5b8c5a', dimension: false },
};

// ===== 关系类型元信息（配色/线型）=====
const RELATION_META: Record<string, { color: string; width: number; dashed?: boolean; curve?: number }> = {
  surveyed_at: { color: '#bfbfbf', width: 1 },
  covered_time: { color: '#bfbfbf', width: 1 },
  targets_host: { color: '#bfbfbf', width: 1 },
  detects_pathogen: { color: '#bfbfbf', width: 1 },
  uses_assay: { color: '#bfbfbf', width: 1 },
  reports_indicator: { color: '#bfbfbf', width: 1 },
  conducted_by: { color: '#2f54eb', width: 1 },
  authored_by: { color: '#eb2f96', width: 1 },
  affiliated_with: { color: '#2f54eb', width: 1, dashed: true },
  has_sample: { color: '#a0d911', width: 1 },
  vaccinated_with: { color: '#36cfc9', width: 1 },
  has_quality: { color: '#faad14', width: 1 },
  contains_survey: { color: '#5b8c5a', width: 1 },
  same_cohort: { color: '#722ed1', width: 1, dashed: true },
  adjusted_for: { color: '#fa8c16', width: 1 },
  higher_than: { color: '#fa541c', width: 2, dashed: true, curve: 0.2 },
  belongs_to: { color: '#722ed1', width: 1.5, dashed: true },
  influences: { color: '#fa8c16', width: 1.5 },
};

const DATA_TYPE_LABEL: Record<string, string> = { seroprevalence: '阳性率', gmc: '几何平均滴度' };

/** 将实体类型映射到 ECharts 分类索引（与 categories 顺序一致） */
const TYPE_ORDER = [
  'survey', 'pathogen', 'geo_area', 'time_period', 'host_group', 'lab_assay', 'indicator',
  'institution', 'author', 'sample', 'vaccine', 'data_quality', 'publication',
];

const KnowledgeGraph: React.FC = () => {
  // 筛选项
  const [options, setOptions] = useState<KgOptionsData | null>(null);
  const [disease, setDisease] = useState<string | undefined>(undefined);
  const [province, setProvince] = useState<string | undefined>(undefined);
  const [dataType, setDataType] = useState<string | undefined>(undefined);
  const [yearStart, setYearStart] = useState<number | undefined>(undefined);
  const [yearEnd, setYearEnd] = useState<number | undefined>(undefined);
  const [maxNodes, setMaxNodes] = useState(600);
  // 数据
  const [overview, setOverview] = useState<KgOverviewData | null>(null);
  const [graphData, setGraphData] = useState<KgGraphData | null>(null);
  const [loading, setLoading] = useState(false);
  const [detailNode, setDetailNode] = useState<KgNode | null>(null);

  // 持久化统计 + 抽取
  const [kgStats, setKgStats] = useState<KgStatsData | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [extractResult, setExtractResult] = useState<{ processed: number; total_written: number; remaining: number; errors: string[] } | null>(null);
  // 抽取进度提示（"点外卖"模式：提交后原地轮询，按钮显示实时进度）
  const [kgTip, setKgTip] = useState('');
  const kgTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const stopKgPolling = () => { if (kgTimer.current) { clearInterval(kgTimer.current); kgTimer.current = null; } };
  /** 轮询知识图谱抽取任务直到结束，期间更新行内进度提示 */
  const pollKgTask = useCallback((taskId: string, doneCb: () => void, failCb: () => void) => {
    stopKgPolling();
    const tick = async () => {
      try {
        const st = await getTaskStatus(taskId);
        const status = String(st.status || 'running');
        setKgTip(`抽取中…已处理 ${st.processed ?? 0} / ${st.total ?? '-'} 篇`);
        if (status === 'done') {
          stopKgPolling();
          setKgTip('');
          const res = (st.result ?? {}) as { processed?: number; total_written?: number; errors?: string[] };
          const processed = res.processed ?? 0;
          if (processed > 0) {
            message.success(`抽取完成：处理 ${processed} 篇，写入 ${res.total_written ?? 0} 条三元组`);
          } else {
            message.info((res.errors && res.errors.length) ? '抽取全部失败' : '无待处理文献');
          }
          doneCb();
        } else if (status === 'failed') {
          stopKgPolling();
          setKgTip('');
          message.error(`抽取失败: ${String(st.error || '未知错误')}`);
          failCb();
        }
      } catch (e: any) {
        if (e?.response?.status === 404) { stopKgPolling(); setKgTip(''); message.error('抽取任务不存在或已过期'); failCb(); }
      }
    };
    setKgTip('已提交，正在排队...');
    kgTimer.current = setInterval(() => void tick(), 3000);
    void tick();
  }, []);

  useEffect(() => () => stopKgPolling(), []);
  // 定向抽取弹窗状态
  const [directOpen, setDirectOpen] = useState(false);
  const [directIdsText, setDirectIdsText] = useState('');
  const [directLimit, setDirectLimit] = useState<number>(10);
  const [directLoading, setDirectLoading] = useState(false);
  const [directResult, setDirectResult] = useState<{ processed: number; total_written: number; remaining: number; errors: string[] } | null>(null);
  // 文献选择器 + 从列表勾选的文献（定向抽取目标）
  const [pickerOpen, setPickerOpen] = useState(false);
  const [directPicked, setDirectPicked] = useState<string[]>([]);

  // 搜索面板状态
  const [searchQ, setSearchQ] = useState('');
  const [searchType, setSearchType] = useState<string | undefined>(undefined);
  const [searchResults, setSearchResults] = useState<KgSearchResult[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);

  // 路径推理状态
  const [pathFrom, setPathFrom] = useState<string | undefined>(undefined);
  const [pathTo, setPathTo] = useState<string | undefined>(undefined);
  const [pathResult, setPathResult] = useState<KgPathResult | null>(null);
  const [pathLoading, setPathLoading] = useState(false);

  // 咨询问答状态
  const [qaQuestion, setQaQuestion] = useState('');
  const [qaLoading, setQaLoading] = useState(false);
  const [qaHistory, setQaHistory] = useState<Array<{ question: string; answer: string; method: string; result_count: number }>>([]);
  const [qaMethod, setQaMethod] = useState<string>('');

  // 加载筛选选项 + 概览 + 持久化统计
  useEffect(() => {
    getKgOptions().then(setOptions).catch(() => message.error('加载筛选选项失败'));
    getKgOverview().then(setOverview).catch(() => message.error('加载图谱概览失败'));
    getKgStats().then(setKgStats).catch(() => message.error('加载持久化统计失败'));
  }, []);

  // 筛选条件变化时重新构建图谱
  useEffect(() => {
    let cancelled = false;
    const params: Record<string, unknown> = { max_nodes: maxNodes };
    if (disease) params.disease = disease;
    if (province) params.province = province;
    if (dataType) params.data_type = dataType;
    if (yearStart) params.year_start = yearStart;
    if (yearEnd) params.year_end = yearEnd;
    setLoading(true);
    getKgGraph(params)
      .then((data) => {
        if (!cancelled) setGraphData(data);
      })
      .catch(() => {
        if (!cancelled) {
          setGraphData({ survey_count: 0, nodes: [], edges: [], trimmed_nodes: 0 });
          message.error('加载知识图谱失败');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [disease, province, dataType, yearStart, yearEnd, maxNodes]);

  const resetFilters = () => {
    setDisease(undefined);
    setProvince(undefined);
    setDataType(undefined);
    setYearStart(undefined);
    setYearEnd(undefined);
    setMaxNodes(600);
  };

  // 手动触发三元组抽取
  const handleExtract = async () => {
    setExtracting(true);
    setExtractResult(null);
    try {
      const resp = await triggerKgExtraction(5);
      pollKgTask(
        resp.task_id,
        () => { setExtractResult({ processed: 0, total_written: 0, remaining: 0, errors: [] }); getKgStats().then(setKgStats).catch(() => {}); setExtracting(false); },
        () => setExtracting(false),
      );
    } catch {
      setKgTip('');
      setExtracting(false);
      message.error('触发抽取失败，请检查后端 ENABLE_KG_EXTRACTION 配置');
    }
  };

  // 定向三元组抽取（按用户指定文献列表）
  const handleDirectedExtract = async () => {
    // 合并两种来源：文献列表勾选 + 手动粘贴 ID
    const pasted = directIdsText.split(/[\s,]+/).filter((s) => s.trim()).map((s) => s.trim());
    const unique = Array.from(new Set([...directPicked, ...pasted]));
    if (!unique.length) {
      message.warning('请先从文献列表勾选，或输入至少一个文献 ID');
      return;
    }
    setDirectLoading(true);
    setDirectResult(null);
    try {
      const resp = await triggerKgExtraction(directLimit, unique);
      pollKgTask(
        resp.task_id,
        () => { setDirectResult({ processed: 0, total_written: 0, remaining: 0, errors: [] }); getKgStats().then(setKgStats).catch(() => {}); setDirectLoading(false); },
        () => setDirectLoading(false),
      );
    } catch {
      setKgTip('');
      setDirectLoading(false);
      message.error('触发抽取失败，请检查后端 ENABLE_KG_EXTRACTION 配置');
    }
  };

  // 搜索实体
  const handleSearch = async () => {
    if (!searchQ.trim()) {
      message.warning('请输入搜索关键词');
      return;
    }
    setSearchLoading(true);
    try {
      const results = await searchKgEntities(searchQ.trim(), searchType, 20);
      setSearchResults(results);
    } catch {
      message.error('搜索失败');
      setSearchResults([]);
    } finally {
      setSearchLoading(false);
    }
  };

  // 路径推理
  const handlePathQuery = async () => {
    if (!pathFrom || !pathTo) {
      message.warning('请选择起点和终点实体');
      return;
    }
    setPathLoading(true);
    try {
      const result = await queryKgPath(pathFrom, pathTo, 3);
      setPathResult(result);
    } catch {
      message.error('路径查询失败');
      setPathResult(null);
    } finally {
      setPathLoading(false);
    }
  };

  // 咨询问答
  const handleQaAsk = async () => {
    if (!qaQuestion.trim()) {
      message.warning('请输入问题');
      return;
    }
    setQaLoading(true);
    setQaMethod('');
    try {
      const result = await askKgQuestion(qaQuestion.trim());
      setQaHistory((prev) => [
        ...prev,
        {
          question: qaQuestion.trim(),
          answer: result.answer,
          method: result.method,
          result_count: result.result_count,
        },
      ]);
      setQaMethod(result.method);
    } catch {
      message.error('问答请求失败，请检查后端服务');
    } finally {
      setQaLoading(false);
    }
  };

  // 从搜索结果构建路径选择下拉项
  const pathOptions = useMemo(() => {
    return searchResults.map((r) => ({
      value: r.id,
      label: `${r.name} (${ENTITY_META[r.entity_type]?.label || r.entity_type})`,
    }));
  }, [searchResults]);

  // 构建 ECharts 关系图 option
  const chartOption = useMemo(() => {
    if (!graphData || !graphData.nodes.length) return null;
    const categories = TYPE_ORDER.map((t) => ({ name: ENTITY_META[t]?.label || t }));
    const nodes = graphData.nodes.map((n) => {
      const meta = ENTITY_META[n.type] || ENTITY_META.survey;
      const size = meta.dimension
        ? Math.min(14 + Math.log2((n.survey_count || 1) + 1) * 4, 30)
        : n.type === 'indicator'
          ? 10
          : 7;
      return {
        id: n.id,
        name: n.label,
        category: TYPE_ORDER.indexOf(n.type),
        symbolSize: size,
        value: n.survey_count,
        label: { show: meta.dimension, fontSize: 10 },
        itemStyle: { color: meta.color },
        raw: n,
      };
    });
    const edges = graphData.edges.map((e) => {
      const em = RELATION_META[e.type] || { color: '#bfbfbf', width: 1 };
      return {
        source: e.source,
        target: e.target,
        label: {
          show: e.type === 'higher_than' || e.type === 'influences' || e.type === 'belongs_to',
          formatter: e.label,
          fontSize: 9,
          color: em.color,
        },
        lineStyle: {
          color: em.color,
          width: em.width,
          type: em.dashed ? 'dashed' : 'solid',
          curveness: em.curve ?? 0,
          opacity: 0.7,
        },
        raw: e,
      };
    });
    return {
      tooltip: {
        trigger: 'item',
        formatter: (p: any) => {
          if (!p?.data?.raw) return '';
          const n: KgNode = p.data.raw;
          const meta = ENTITY_META[n.type] || ENTITY_META.survey;
          const props = n.props || {};
          const rows = [
            `<b>${n.label}</b>`,
            `类型：${meta.label}`,
            `关联调查：${n.survey_count} 项`,
          ];
          if (props.disease) rows.push(`疾病：${props.disease}`);
          if (props.province) rows.push(`省份：${props.province}`);
          if (props.region) rows.push(`大区：${props.region}`);
          if (props.year) rows.push(`年份：${props.year}`);
          if (props.population) rows.push(`人群：${props.population}`);
          if (props.method) rows.push(`方法：${props.method}`);
          if (props.data_type) rows.push(`指标：${DATA_TYPE_LABEL[props.data_type as string] || props.data_type}`);
          if (props.value != null) rows.push(`值：${props.value}${props.unit || ''}`);
          if (props.sample_size != null) rows.push(`样本量：${props.sample_size}`);
          return rows.join('<br/>');
        },
      },
      legend: {
        top: 0,
        data: categories.map((c) => c.name),
        type: 'scroll',
        textStyle: { fontSize: 11 },
      },
      series: [
        {
          type: 'graph',
          layout: 'force',
          roam: true,
          draggable: true,
          categories,
          data: nodes,
          links: edges,
          force: { repulsion: 140, edgeLength: 90, gravity: 0.12 },
          label: { show: false },
          edgeSymbol: ['none', 'arrow'],
          edgeSymbolSize: 6,
          emphasis: { focus: 'adjacency', lineStyle: { width: 3 } },
          lineStyle: { color: '#bfbfbf', opacity: 0.7 },
        },
      ],
    };
  }, [graphData]);

  const handleChartClick = (params: unknown) => {
    const p = params as { dataType?: string; data?: { raw?: KgNode } };
    if (p?.dataType === 'node' && p.data?.raw) {
      setDetailNode(p.data.raw);
    }
  };

  const selectedNodeType = detailNode ? ENTITY_META[detailNode.type]?.label : '';

  // 路径推理结果渲染
  const pathSteps = useMemo(() => {
    if (!pathResult || !pathResult.found || !pathResult.path.length) return null;
    return pathResult.path.map((step, idx) => ({
      title: step.name || step.id,
      description: idx === 0
        ? '起点'
        : `经由「${step.predicate || '关联'}」到达`,
      status: (idx === pathResult.path.length - 1 ? 'finish' : 'process') as 'finish' | 'process',
    }));
  }, [pathResult]);

  return (
    <Tabs
      defaultActiveKey="graph"
      items={[
        {
          key: 'graph',
          label: <span><ApartmentOutlined />关系图谱</span>,
          children: (
            <>
              {/* 筛选栏 */}
              <Card style={{ marginBottom: 16 }}>
                <Row gutter={[12, 12]} align="middle">
                  <Col>
                    <span>疾病</span>
                    <Select
                      style={{ minWidth: 130, marginLeft: 6 }}
                      placeholder="全部"
                      allowClear
                      showSearch
                      value={disease}
                      onChange={setDisease}
                      options={(options?.diseases ?? []).map((d) => ({ value: d, label: d }))}
                    />
                  </Col>
                  <Col>
                    <span>地区</span>
                    <Select
                      style={{ minWidth: 120, marginLeft: 6 }}
                      placeholder="全部"
                      allowClear
                      showSearch
                      value={province}
                      onChange={setProvince}
                      options={(options?.provinces ?? []).map((p) => ({ value: p, label: p }))}
                    />
                  </Col>
                  <Col>
                    <span>指标类型</span>
                    <Select
                      style={{ minWidth: 130, marginLeft: 6 }}
                      placeholder="全部"
                      allowClear
                      value={dataType}
                      onChange={setDataType}
                      options={(options?.data_types ?? []).map((d) => ({ value: d, label: DATA_TYPE_LABEL[d] || d }))}
                    />
                  </Col>
                  <Col>
                    <span>年份</span>
                    <Select
                      style={{ width: 90, marginLeft: 6 }}
                      placeholder="起始"
                      allowClear
                      value={yearStart}
                      onChange={setYearStart}
                      options={(options?.years ?? []).map((y) => ({ value: y, label: `${y}` }))}
                    />
                    <span style={{ margin: '0 4px' }}>至</span>
                    <Select
                      style={{ width: 90 }}
                      placeholder="结束"
                      allowClear
                      value={yearEnd}
                      onChange={setYearEnd}
                      options={(options?.years ?? []).map((y) => ({ value: y, label: `${y}` }))}
                    />
                  </Col>
                  <Col>
                    <Button icon={<ReloadOutlined />} onClick={resetFilters}>重置</Button>
                  </Col>
                </Row>
                <Row style={{ marginTop: 8 }} align="middle">
                  <Col flex="auto">
                    <Space>
                      <span>节点数上限（超出按样本量优先裁剪调查）：</span>
                      <Slider
                        style={{ width: 220 }}
                        min={50}
                        max={2000}
                        step={50}
                        value={maxNodes}
                        onChange={setMaxNodes}
                      />
                      <Tag color="blue">{maxNodes}</Tag>
                    </Space>
                  </Col>
                </Row>
                {graphData && graphData.trimmed_nodes > 0 && (
                  <Alert
                    style={{ marginTop: 8 }}
                    type="warning"
                    showIcon
                    message={`图谱已裁剪 ${graphData.trimmed_nodes} 个孤立节点（节点数超上限，按样本量优先保留大样本调查）`}
                  />
                )}
              </Card>

              {/* 概览卡片 */}
              <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={6}>
                  <Card><Statistic title="调查总数" value={graphData?.survey_count ?? overview?.survey_count ?? 0} /></Card>
                </Col>
                <Col span={6}>
                  <Card><Statistic title="图谱节点" value={graphData?.nodes.length ?? 0} /></Card>
                </Col>
                <Col span={6}>
                  <Card><Statistic title="关系边" value={graphData?.edges.length ?? 0} /></Card>
                </Col>
                <Col span={6}>
                  <Card><Statistic title="关系类型" value={overview ? Object.values(overview.relation_counts).filter((v) => v > 0).length : 0} /></Card>
                </Col>
              </Row>

              {/* 关系图 */}
              <Spin spinning={loading}>
                <Card
                  title={<Space><ApartmentOutlined />知识图谱（点击节点查看详情）</Space>}
                  extra={
                    <Space size="large">
                      <Tag color="#fa541c">— 高于</Tag>
                      <Tag color="#722ed1">- - 隶属于</Tag>
                      <Tag color="#fa8c16">— 影响</Tag>
                    </Space>
                  }
                >
                  {!chartOption ? (
                    <Empty description="暂无图谱数据（请调整筛选条件或等待审核通过的数据点）" />
                  ) : (
                    <EChart
                      option={chartOption}
                      style={{ height: 640 }}
                      onEvents={{ click: handleChartClick }}
                    />
                  )}
                </Card>
              </Spin>

              {/* 持久化统计 + 手动抽取 */}
              <Card style={{ marginTop: 16 }}>
                <Row gutter={16} align="middle">
                  <Col span={6}>
                    <Statistic title="持久化实体" value={kgStats?.total_entities ?? 0} />
                  </Col>
                  <Col span={6}>
                    <Statistic title="持久化三元组" value={kgStats?.total_triples ?? 0} />
                  </Col>
                  <Col span={6}>
                    <Statistic title="抽取后剩余" value={extractResult?.remaining ?? '-'} />
                  </Col>
                  <Col span={6}>
                    <Button
                      type="primary"
                      icon={<ThunderboltOutlined />}
                      onClick={handleExtract}
                      loading={extracting}
                      size="large"
                      block
                    >
                      {extracting ? '抽取中...' : '手动三元组抽取'}
                    </Button>
                    {extracting && kgTip && (
                      <div style={{ marginTop: 8, textAlign: 'center' }}>
                        <Tag color="processing">{kgTip}</Tag>
                      </div>
                    )}
                    <Button
                      style={{ marginTop: 8 }}
                      icon={<NumberOutlined />}
                      onClick={() => setDirectOpen(true)}
                      size="large"
                      block
                    >
                      定向抽取
                    </Button>
                  </Col>
                </Row>
                {extractResult && (
                  <Alert
                    style={{ marginTop: 12 }}
                    type={extractResult.errors?.length ? 'warning' : 'success'}
                    showIcon
                    message={`处理 ${extractResult.processed} 篇，写入 ${extractResult.total_written} 条三元组，剩余 ${extractResult.remaining} 篇未处理`}
                    description={extractResult.errors?.length ? `错误：${extractResult.errors.join('；')}` : undefined}
                    closable
                    onClose={() => setExtractResult(null)}
                  />
                )}
                {!kgStats && (
                  <Alert style={{ marginTop: 12 }} type="info" showIcon message="持久化统计来自 LLM 抽取写入的实体和三元组，计算式推导的维度实体不计入" />
                )}
              </Card>

              {/* 定向抽取弹窗 */}
              <Modal
                open={directOpen}
                title="定向三元组抽取"
                onCancel={() => setDirectOpen(false)}
                footer={null}
                destroyOnClose
              >
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Text type="secondary">
                    从文献列表勾选需要抽取的文献（推荐），或直接粘贴文献 ID（每行一个，支持下划线/逗号分隔）。仅处理这些文献中已存在缓存文本、且尚未抽取的部分（幂等，已抽取的会被跳过）。
                  </Text>
                  <Space align="center" style={{ width: '100%' }}>
                    <Button icon={<NumberOutlined />} onClick={() => setPickerOpen(true)}>
                      从文献列表选择
                    </Button>
                    {directPicked.length > 0 && (
                      <>
                        <Text type="secondary">已选 {directPicked.length} 篇：</Text>
                        <Button size="small" danger onClick={() => setDirectPicked([])}>清空</Button>
                      </>
                    )}
                  </Space>
                  {directPicked.length > 0 && (
                    <Tag closable onClose={() => setDirectPicked([])}>
                      文献列表已勾选 {directPicked.length} 篇（将用于本次定向抽取）
                    </Tag>
                  )}
                  <Input.TextArea
                    rows={5}
                    placeholder="也可在此粘贴文献 ID（UUID），每行 / 逗号一个——已从列表选择的无需填写"
                    value={directIdsText}
                    onChange={(e) => setDirectIdsText(e.target.value)}
                  />
                  <Space>
                    <span>单次上限：</span>
                    <InputNumber
                      min={1}
                      max={50}
                      value={directLimit}
                      onChange={(v) => setDirectLimit(v ?? 10)}
                    />
                    <span style={{ color: '#999' }}>（最多处理前 N 篇，超出的可在下次继续）</span>
                  </Space>
                  <Button
                    type="primary"
                    block
                    loading={directLoading}
                    onClick={handleDirectedExtract}
                    icon={<ThunderboltOutlined />}
                  >
                    {directLoading ? '定向抽取中...' : '开始定向抽取'}
                  </Button>
                  {directLoading && kgTip && (
                    <div style={{ marginTop: 8, textAlign: 'center' }}>
                      <Tag color="processing">{kgTip}</Tag>
                    </div>
                  )}
                  {directResult && (
                    <Alert
                      type={directResult.errors?.length ? 'warning' : 'success'}
                      showIcon
                      message={`处理 ${directResult.processed} 篇，写入 ${directResult.total_written} 条三元组，剩余 ${directResult.remaining} 篇未处理`}
                      description={directResult.errors?.length ? `错误：${directResult.errors.join('；')}` : undefined}
                    />
                  )}
                </Space>
              </Modal>
              {/* 文献选择器 */}
              <LiteraturePicker
                open={pickerOpen}
                onClose={() => setPickerOpen(false)}
                onConfirm={(ids) => {
                  setDirectPicked((prev) => Array.from(new Set([...prev, ...ids])));
                }}
              />
            </>
          ),
        },
        {
          key: 'search',
          label: <span><SearchOutlined />实体搜索</span>,
          children: (
            <Card title={<Space><SearchOutlined />实体搜索</Space>}>
              <Space style={{ width: '100%', marginBottom: 16 }}>
                <Select
                  style={{ width: 140 }}
                  placeholder="实体类型"
                  allowClear
                  value={searchType}
                  onChange={setSearchType}
                  options={TYPE_ORDER.map((t) => ({ value: t, label: ENTITY_META[t]?.label || t }))}
                />
                <Input
                  style={{ width: 300 }}
                  placeholder="输入关键词搜索实体..."
                  value={searchQ}
                  onChange={(e) => setSearchQ(e.target.value)}
                  onPressEnter={handleSearch}
                  prefix={<SearchOutlined />}
                />
                <Button type="primary" onClick={handleSearch} loading={searchLoading}>搜索</Button>
              </Space>

              <Spin spinning={searchLoading}>
                {searchResults.length === 0 ? (
                  <Empty description="输入关键词搜索知识图谱中的实体" />
                ) : (
                  <List
                    bordered
                    dataSource={searchResults}
                    renderItem={(item) => (
                      <List.Item
                        actions={[
                          <TextLink
                            key="path"
                            onClick={() => {
                              if (!pathFrom) {
                                setPathFrom(item.id);
                                message.success(`已设为起点：${item.name}`);
                              } else if (!pathTo && item.id !== pathFrom) {
                                setPathTo(item.id);
                                message.success(`已设为终点：${item.name}`);
                              } else {
                                setPathFrom(item.id);
                                setPathTo(undefined);
                                setPathResult(null);
                                message.success(`已重置起点：${item.name}`);
                              }
                            }}
                          >
                            设为路径{pathFrom === item.id ? '起点(已选)' : pathTo === item.id ? '终点(已选)' : '起点/终点'}
                          </TextLink>,
                        ]}
                      >
                        <List.Item.Meta
                          avatar={<Tag color={ENTITY_META[item.entity_type]?.color}>{ENTITY_META[item.entity_type]?.label || item.entity_type}</Tag>}
                          title={item.name}
                          description={
                            <Space size="small">
                              <Text type="secondary">关联三元组：{item.triple_count} 条</Text>
                              {item.source && <Tag>{item.source === 'persistent' ? '持久化' : '计算式'}</Tag>}
                            </Space>
                          }
                        />
                      </List.Item>
                    )}
                  />
                )}
              </Spin>

              {searchResults.length > 0 && (
                <Alert
                  style={{ marginTop: 12 }}
                  type="info"
                  showIcon
                  message="提示：点击搜索结果右侧的「设为路径起点/终点」可快速选择路径推理的起止实体，然后切换到「路径推理」标签页查询。"
                />
              )}
            </Card>
          ),
        },
        {
          key: 'path',
          label: <span><NodeIndexOutlined />路径推理</span>,
          children: (
            <Card title={<Space><NodeIndexOutlined />路径推理（BFS 最短路径搜索）</Space>}>
              <Space style={{ width: '100%', marginBottom: 16 }} direction="vertical">
                <Row gutter={12}>
                  <Col>
                    <span>起点实体</span>
                    <Select
                      style={{ minWidth: 280, marginLeft: 6 }}
                      placeholder="选择起点实体（先在搜索页搜索）"
                      showSearch
                      allowClear
                      value={pathFrom}
                      onChange={setPathFrom}
                      options={pathOptions}
                    />
                  </Col>
                  <Col>
                    <span>终点实体</span>
                    <Select
                      style={{ minWidth: 280, marginLeft: 6 }}
                      placeholder="选择终点实体"
                      showSearch
                      allowClear
                      value={pathTo}
                      onChange={setPathTo}
                      options={pathOptions}
                    />
                  </Col>
                  <Col>
                    <Button
                      type="primary"
                      icon={<NodeIndexOutlined />}
                      onClick={handlePathQuery}
                      loading={pathLoading}
                      disabled={!pathFrom || !pathTo}
                    >
                      查询路径
                    </Button>
                  </Col>
                </Row>
              </Space>

              <Spin spinning={pathLoading}>
                {pathResult === null ? (
                  <Empty description="选择起点和终点实体后点击「查询路径」" />
                ) : !pathResult.found ? (
                  <Alert
                    type="warning"
                    showIcon
                    message="未找到路径"
                    description="两个实体之间在当前深度限制（3 层）内无可达路径。可能原因：实体间无直接或间接关联，或深度不足。"
                  />
                ) : (
                  <div>
                    <Alert
                      style={{ marginBottom: 16 }}
                      type="success"
                      showIcon
                      message={`找到路径！共 ${pathResult.depth} 跳`}
                    />
                    <Steps
                      direction="vertical"
                      size="small"
                      current={pathResult.path.length - 1}
                      items={pathSteps || []}
                    />
                  </div>
                )}
              </Spin>
            </Card>
          ),
        },
        {
          key: 'qa',
          label: <span><MessageOutlined />咨询问答</span>,
          children: (
            <Card title={<Space><MessageOutlined />知识图谱咨询问答</Space>}>
              <div style={{ marginBottom: 16 }}>
                <Input.TextArea
                  rows={3}
                  placeholder={`输入问题，例如：\n- 北京麻疹阳性率是多少\n- 北京和上海麻疹阳性率对比\n- 哈尔滨医科大学做过哪些调查\n- 儿童麻疹抗体阳性率`}
                  value={qaQuestion}
                  onChange={(e) => setQaQuestion(e.target.value)}
                  onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); handleQaAsk(); }}}
                />
                <Button
                  type="primary"
                  icon={<MessageOutlined />}
                  onClick={handleQaAsk}
                  loading={qaLoading}
                  style={{ marginTop: 8 }}
                >
                  {qaLoading ? '思考中...' : '提问'}
                </Button>
                <Tag style={{ marginLeft: 8 }} color="blue">{qaMethod === 'template' ? '模板匹配' : qaMethod === 'llm' ? 'AI 回答' : qaMethod || ''}</Tag>
              </div>

              <Spin spinning={qaLoading}>
                {qaHistory.length === 0 ? (
                  <Empty description="输入问题开始咨询知识图谱" />
                ) : (
                  <div style={{ maxHeight: 500, overflow: 'auto' }}>
                    {qaHistory.map((item, idx) => (
                      <div key={idx} style={{ marginBottom: 16 }}>
                        <Alert
                          type="info"
                          showIcon
                          message={<Text strong>{item.question}</Text>}
                          style={{ marginBottom: 4, whiteSpace: 'pre-wrap' }}
                        />
                        <Card
                          size="small"
                          style={{
                            background: '#f6ffed',
                            border: '1px solid #b7eb8f',
                          }}
                        >
                          <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.8 }}>
                            {item.answer.split('\n').map((line, i) => {
                              if (line.startsWith('## ')) {
                                return <Typography.Title key={i} level={5} style={{ marginTop: 8, marginBottom: 4 }}>{line.replace('## ', '')}</Typography.Title>;
                              }
                              if (line.startsWith('**') && line.endsWith('**')) {
                                return <Text key={i} strong style={{ display: 'block' }}>{line.replace(/\*\*/g, '')}</Text>;
                              }
                              return <div key={i}>{line}</div>;
                            })}
                          </div>
                          <Divider style={{ margin: '8px 0' }} />
                          <Space size="small">
                            <Tag color={item.method === 'template' ? 'green' : 'blue'}>{item.method === 'template' ? '模板匹配' : 'AI 回答'}</Tag>
                            {item.result_count > 0 && <Text type="secondary">{item.result_count} 条数据</Text>}
                          </Space>
                        </Card>
                      </div>
                    ))}
                  </div>
                )}
              </Spin>
            </Card>
          ),
        },
      ]}
    >
    </Tabs>
  );
};

export default KnowledgeGraph;
