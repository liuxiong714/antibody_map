import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Card, Row, Col, Select, Slider, Button, Spin, Empty, Alert, Drawer, Descriptions,
  Tag, Statistic, Space, Divider, message, Input, Tabs, List, Typography, Steps,
  Modal, InputNumber, Switch, Checkbox,
} from 'antd';
import {
  ReloadOutlined, ApartmentOutlined, SearchOutlined, NodeIndexOutlined,
  ThunderboltOutlined, MessageOutlined, NumberOutlined, MergeOutlined,
  DownloadOutlined, ShareAltOutlined, AuditOutlined,
} from '@ant-design/icons';
import EChart from '../components/EChart';
import LiteraturePicker from '../components/LiteraturePicker';
import {
  getKgOverview, getKgOptions, getKgGraph,
  searchKgEntities, queryKgPath, getKgStats, triggerKgExtraction,
  askKgQuestion, getKgMergeCandidates, mergeKgEntities, feedbackKgQa,
  getKgReviewSample, reviewKgTriples, deleteKgTriples,
  type KgTripleReviewItem,
} from '../services/knowledgeGraph';
import { getTaskStatus } from '../services/system';
import { buildModelOptions, ExtendedModelOption } from '../utils/modelOptions';
import type {
  KgGraphData, KgNode, KgOverviewData, KgOptionsData,
  KgSearchResult, KgPathResult, KgStatsData, KgEvidence,
} from '../types';

const { Text, Link: TextLink } = Typography;

// 多轮对话：判断问题是否已自带疾病/指标词，避免重复拼装
const DISEASE_TERM_HINTS = [
  '麻疹', '风疹', '水痘', '腮腺炎', '乙肝', '甲肝', '丙肝', '破伤风', '白喉',
  '百日咳', '脊灰', '脊髓灰质炎', '新冠', '流感', '脑膜炎', '手足口', '乙脑',
  '疫苗', 'gmc', 'gmt', '几何平均', '抗体', '阳性率',
];

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
  const navigate = useNavigate();
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
  // 分层聚焦：默认仅主维度节点；showAll 显示全部
  const [showAll, setShowAll] = useState(false);
  const [focusNode, setFocusNode] = useState<KgNode | null>(null);
  // 统计下钻：实体/关系列表抽屉
  const [drillOpen, setDrillOpen] = useState(false);
  const [drillTitle, setDrillTitle] = useState('');
  const [drillKind, setDrillKind] = useState<'entities' | 'edges'>('entities');
  const [drillSource, setDrillSource] = useState<'all' | 'view'>('view');

  // 持久化统计 + 抽取
  const [kgStats, setKgStats] = useState<KgStatsData | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [kgModelOptions, setKgModelOptions] = useState<ExtendedModelOption[]>([]);
  const [kgModel, setKgModel] = useState<string>();
  const [extractResult, setExtractResult] = useState<{ processed: number; total_written: number; remaining: number; errors: string[] } | null>(null);
  // 抽取进度提示（"点外卖"模式：提交后原地轮询，按钮显示实时进度）
  const [kgTip, setKgTip] = useState('');
  const kgTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  // 连续 404 计数：Celery worker 登记 Redis 有延迟，任务刚提交时前几次轮询可能返回
  // 404（"任务不存在"），只有连续多次仍未登记才视为任务彻底过期，避免瞬时竞态误报。
  const kgMissingCount = useRef(0);
  const stopKgPolling = () => { if (kgTimer.current) { clearInterval(kgTimer.current); kgTimer.current = null; } };
  /** 轮询知识图谱抽取任务直到结束，期间更新行内进度提示 */
  const pollKgTask = useCallback((taskId: string, doneCb: () => void, failCb: () => void) => {
    stopKgPolling();
    kgMissingCount.current = 0;
    const tick = async () => {
      try {
        const st = await getTaskStatus(taskId);
        kgMissingCount.current = 0;
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
        if (e?.response?.status === 404) {
          kgMissingCount.current += 1;
          // 允许临时缺失几次（worker 登记延迟），连续多次仍 404 才当作任务过期终止
          if (kgMissingCount.current >= 4) {
            stopKgPolling(); setKgTip(''); message.error('抽取任务不存在或已过期'); failCb();
          }
        }
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
  const [qaHistory, setQaHistory] = useState<Array<{ question: string; answer: string; method: string; result_count: number; evidence: KgEvidence[]; slots: Record<string, string> | null; log_id: string | null; feedback: 'up' | 'down' | null }>>([]);
  const [qaMethod, setQaMethod] = useState<string>('');

  // 实体合并工作流（管理员）
  const [mergeCandidates, setMergeCandidates] = useState<Array<{
    entity_type: string; reason: string;
    members: Array<{ id: string; name: string; entity_type: string; attributes: Record<string, unknown>; source_literature_id: string | null; triple_count: number }>;
  }>>([]);
  const [mergeOpen, setMergeOpen] = useState(false);
  const [mergeLoading, setMergeLoading] = useState(false);

  // 抽取质量评估（管理员）
  const [qualityOpen, setQualityOpen] = useState(false);
  const [qualityItems, setQualityItems] = useState<KgTripleReviewItem[]>([]);
  const [qualityLoading, setQualityLoading] = useState(false);
  const [qualitySelected, setQualitySelected] = useState<string[]>([]);

  // 加载筛选选项 + 概览 + 持久化统计
  useEffect(() => {
    getKgOptions().then(setOptions).catch(() => message.error('加载筛选选项失败'));
    getKgOverview().then(setOverview).catch(() => message.error('加载图谱概览失败'));
    getKgStats().then(setKgStats).catch(() => message.error('加载持久化统计失败'));
    buildModelOptions().then(setKgModelOptions).catch(() => {});
  }, []);

  // 分享链接：从 URL 参数恢复筛选条件
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    const num = (k: string) => {
      const v = Number(p.get(k));
      return Number.isFinite(v) && v > 0 ? v : undefined;
    };
    if (p.get('disease')) setDisease(p.get('disease')!);
    if (p.get('province')) setProvince(p.get('province')!);
    if (p.get('data_type')) setDataType(p.get('data_type')!);
    if (num('year_start')) setYearStart(num('year_start'));
    if (num('year_end')) setYearEnd(num('year_end'));
    if (num('max_nodes')) setMaxNodes(num('max_nodes')!);
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
      const resp = await triggerKgExtraction(5, undefined, kgModel);
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
      const resp = await triggerKgExtraction(directLimit, unique, kgModel);
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
      // 多轮对话：省略疾病/地区时用上一轮槽位补全（如「北京麻疹阳性率→上海呢」）
      const prev = qaHistory.length ? qaHistory[qaHistory.length - 1] : null;
      let q = qaQuestion.trim();
      const hasDiseaseTerm = DISEASE_TERM_HINTS.some((t) => q.toLowerCase().includes(t.toLowerCase()));
      if (!hasDiseaseTerm && prev?.slots?.disease) {
        q = `${q.replace(/[呢吗啊]?\s*$/, '')} ${prev.slots.disease}阳性率是多少`;
      }
      const result = await askKgQuestion(q, prev?.slots ?? null);
      setQaHistory((prevHist) => [
        ...prevHist,
        {
          question: q,
          answer: result.answer,
          method: result.method,
          result_count: result.result_count,
          evidence: result.evidence || [],
          slots: result.slots || null,
          log_id: result.log_id || null,
          feedback: null,
        },
      ]);
      setQaMethod(result.method);
    } catch {
      message.error('问答请求失败，请检查后端服务');
    } finally {
      setQaLoading(false);
    }
  };

  // 问答反馈（点赞/点踩）
  const handleQaFeedback = async (idx: number, fb: 'up' | 'down') => {
    const item = qaHistory[idx];
    if (!item || !item.log_id) {
      message.info('该问答暂无反馈记录');
      return;
    }
    try {
      await feedbackKgQa(item.log_id, fb);
      setQaHistory((prev) => prev.map((it, i) => (i === idx ? { ...it, feedback: fb } : it)));
      message.success(fb === 'up' ? '已点赞' : '已点踩，感谢反馈');
    } catch {
      message.error('提交反馈失败');
    }
  };

  // 抽取质量评估：抽样加载与批量处理
  const loadQualitySample = async () => {
    setQualityLoading(true);
    setQualitySelected([]);
    try {
      const items = await getKgReviewSample(30);
      setQualityItems(items || []);
      setQualityOpen(true);
    } catch {
      message.error('加载校验样本失败（需管理员权限）');
    } finally {
      setQualityLoading(false);
    }
  };
  const handleQualityReview = async (status: 'approved' | 'rejected') => {
    if (!qualitySelected.length) {
      message.warning('请先勾选要校验的三元组');
      return;
    }
    try {
      const res = await reviewKgTriples(qualitySelected, status);
      setQualityItems((prev) => prev.filter((t) => !qualitySelected.includes(t.id)));
      setQualitySelected([]);
      message.success(`已标记 ${res.updated} 条为${status === 'approved' ? '正确' : '错误'}`);
    } catch {
      message.error('标记失败（需管理员权限）');
    }
  };
  const handleQualityDelete = async () => {
    if (!qualitySelected.length) {
      message.warning('请先勾选要删除的三元组');
      return;
    }
    try {
      const res = await deleteKgTriples(qualitySelected);
      setQualityItems((prev) => prev.filter((t) => !qualitySelected.includes(t.id)));
      setQualitySelected([]);
      message.success(`已删除 ${res.deleted} 条错误三元组`);
    } catch {
      message.error('删除失败（需管理员权限）');
    }
  };

  // 实体合并候选加载与执行
  const loadMergeCandidates = async () => {
    setMergeLoading(true);
    try {
      const data = await getKgMergeCandidates(30);
      setMergeCandidates(data || []);
      setMergeOpen(true);
    } catch {
      message.error('加载合并候选失败（需管理员权限）');
    } finally {
      setMergeLoading(false);
    }
  };

  const handleMergeGroup = async (group: typeof mergeCandidates[number]) => {
    const keep = group.members[0];
    const mergeIds = group.members.slice(1).map((m) => m.id);
    try {
      const res = await mergeKgEntities(keep.id, mergeIds);
      message.success(`已合并 ${res.merged} 个实体，迁移 ${res.moved_triples} 条关系`);
      setMergeCandidates((prev) => prev.filter((g) => g !== group));
    } catch {
      message.error('合并失败（需管理员权限）');
    }
  };

  // 从搜索结果构建路径选择下拉项
  const pathOptions = useMemo(() => {
    return searchResults.map((r) => ({
      value: r.id,
      label: `${r.name} (${ENTITY_META[r.entity_type]?.label || r.entity_type})`,
    }));
  }, [searchResults]);

  // 分层聚焦：默认只保留主维度节点（及其两端均在的边），showAll 时显示全部
  const filteredGraph = useMemo(() => {
    if (!graphData || !graphData.nodes.length) return null;
    if (showAll) return graphData;
    const keep = new Set(
      graphData.nodes.filter((n) => ENTITY_META[n.type]?.dimension).map((n) => n.id),
    );
    return {
      nodes: graphData.nodes.filter((n) => keep.has(n.id)),
      edges: graphData.edges.filter((e) => keep.has(e.source) && keep.has(e.target)),
    };
  }, [graphData, showAll]);

  // 中心节点的一跳邻居（含主维度节点本身），用于展开查看
  const neighborsOf = useMemo(() => {
    if (!graphData || !focusNode) return null;
    const nids = new Set([focusNode.id]);
    const edges = graphData.edges.filter(
      (e) => e.source === focusNode.id || e.target === focusNode.id,
    );
    edges.forEach((e) => {
      nids.add(e.source);
      nids.add(e.target);
    });
    return {
      nodes: graphData.nodes.filter((n) => nids.has(n.id)),
      edges,
    };
  }, [graphData, focusNode]);

  // 构建 ECharts 关系图 option
  const chartOption = useMemo(() => {
    if (!filteredGraph || !filteredGraph.nodes.length) return null;
    const categories = TYPE_ORDER.map((t) => ({ name: ENTITY_META[t]?.label || t, itemStyle: { color: ENTITY_META[t]?.color } }));
    const nodes = filteredGraph.nodes.map((n) => {
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
    const edges = filteredGraph.edges.map((e) => {
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
  }, [filteredGraph]);

  // 子图导出与分享（P2-⑧）
  const chartRef = useRef<any>(null);
  const exportGraphImage = () => {
    const inst = chartRef.current?.getEchartsInstance?.();
    if (!inst) { message.warning('图表尚未就绪，请稍后再试'); return; }
    const url = inst.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#fff' });
    const a = document.createElement('a');
    a.href = url;
    a.download = `knowledge-graph-${Date.now()}.png`;
    a.click();
  };
  const exportGraphJson = () => {
    const data = filteredGraph;
    if (!data) return;
    const blob = new Blob(
      [JSON.stringify({ nodes: data.nodes, edges: data.edges, exported_at: new Date().toISOString() }, null, 2)],
      { type: 'application/json' },
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `knowledge-graph-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };
  const shareGraph = async () => {
    const p = new URLSearchParams();
    if (disease) p.set('disease', disease);
    if (province) p.set('province', province);
    if (dataType) p.set('data_type', dataType);
    if (yearStart != null) p.set('year_start', String(yearStart));
    if (yearEnd != null) p.set('year_end', String(yearEnd));
    p.set('max_nodes', String(maxNodes));
    const url = `${window.location.origin}${window.location.pathname}?${p.toString()}`;
    try {
      await navigator.clipboard.writeText(url);
      message.success('分享链接已复制到剪贴板');
    } catch {
      message.info(url);
    }
  };

  const handleChartClick = (params: unknown) => {
    const p = params as { dataType?: string; data?: { raw?: KgNode } };
    if (p?.dataType === 'node' && p.data?.raw) {
      const node = p.data.raw;
      // 主维度视图：点击主维度节点 → 打开邻居展开 Modal
      if (!showAll && ENTITY_META[node.type]?.dimension) {
        setFocusNode(node);
        return;
      }
      const props = (node.props || {}) as Record<string, unknown>;
      if (props.literature_id) {
        navigate(`/literature/${props.literature_id}`);
      } else {
        const info = [
          props.disease ? `疾病：${props.disease}` : '',
          props.year ? `${props.year}年` : '',
          props.province ? `地区：${props.province}` : '',
          props.sample_size ? `样本量：${props.sample_size}` : '',
        ].filter(Boolean).join('；');
        message.info(`${node.label}${info ? `（${info}）` : ''}`);
      }
    }
  };

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
    <>
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
                  <Col>
                    <Space>
                      <span>显示全部节点</span>
                      <Switch
                        checked={showAll}
                        onChange={(v) => setShowAll(v)}
                        checkedChildren="全部"
                        unCheckedChildren="主维度"
                      />
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
                  <Card hoverable style={{ cursor: 'pointer' }} onClick={() => {
                    if (!graphData?.nodes.length) return;
                    setDrillKind('entities');
                    setDrillSource('all');
                    setDrillTitle(`调查实体（${graphData.nodes.length}）`);
                    setDrillOpen(true);
                  }}><Statistic title="调查总数" value={graphData?.survey_count ?? overview?.survey_count ?? 0} /></Card>
                </Col>
                <Col span={6}>
                  <Card hoverable style={{ cursor: 'pointer' }} onClick={() => {
                    if (!filteredGraph?.nodes.length) return;
                    setDrillKind('entities');
                    setDrillSource('view');
                    setDrillTitle(`当前视图实体（${filteredGraph.nodes.length}）`);
                    setDrillOpen(true);
                  }}><Statistic title="图谱节点" value={graphData?.nodes.length ?? 0} /></Card>
                </Col>
                <Col span={6}>
                  <Card hoverable style={{ cursor: 'pointer' }} onClick={() => {
                    if (!filteredGraph?.edges.length) return;
                    setDrillKind('edges');
                    setDrillTitle(`当前视图关系（${filteredGraph.edges.length}）`);
                    setDrillOpen(true);
                  }}><Statistic title="关系边" value={graphData?.edges.length ?? 0} /></Card>
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
                      <Divider type="vertical" />
                      <Button size="small" icon={<DownloadOutlined />} onClick={exportGraphImage}>导出图片</Button>
                      <Button size="small" icon={<NumberOutlined />} onClick={exportGraphJson}>导出JSON</Button>
                      <Button size="small" icon={<ShareAltOutlined />} onClick={shareGraph}>分享</Button>
                    </Space>
                  }
                >
                  {!chartOption ? (
                    <Empty description="暂无图谱数据（请调整筛选条件或等待审核通过的数据点）" />
                  ) : (
                    <EChart
                      ref={chartRef}
                      option={chartOption}
                      style={{ height: 640 }}
                      onEvents={{ click: handleChartClick }}
                    />
                  )}
                </Card>
              </Spin>

              {/* 分层聚焦：中心节点邻居展开 */}
              <Modal
                open={!!focusNode}
                title={focusNode ? `「${focusNode.label}」的关联节点` : ''}
                footer={null}
                width={560}
                onCancel={() => setFocusNode(null)}
              >
                {focusNode && (
                  <List
                    size="small"
                    dataSource={neighborsOf?.nodes ?? []}
                    renderItem={(n) => {
                      const meta = ENTITY_META[n.type] || ENTITY_META.survey;
                      const props = (n.props || {}) as Record<string, unknown>;
                      return (
                        <List.Item
                          actions={[
                            props.literature_id ? (
                              <TextLink
                                key="lit"
                                onClick={() => { setFocusNode(null); navigate(`/literature/${props.literature_id}`); }}
                              >
                                查看文献
                              </TextLink>
                            ) : null,
                          ].filter(Boolean)}
                        >
                          <Tag color={meta.color}>{meta.label}</Tag>
                          <span style={{ fontWeight: n.id === focusNode.id ? 600 : 400 }}>{n.label}</span>
                          <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                            {props.year ? `${props.year}年` : ''}
                            {props.disease ? ` · ${props.disease}` : ''}
                            {props.value != null ? ` · ${props.value}${props.unit || ''}` : ''}
                          </Text>
                        </List.Item>
                      );
                    }}
                  />
                )}
              </Modal>

              {/* 统计下钻：实体/关系列表抽屉 */}
              <Drawer
                open={drillOpen}
                title={drillTitle}
                width={480}
                onClose={() => setDrillOpen(false)}
              >
                {drillKind === 'entities' ? (
                  <List
                    size="small"
                    dataSource={(drillSource === 'all' ? graphData?.nodes : filteredGraph?.nodes) ?? []}
                    renderItem={(n) => {
                      const meta = ENTITY_META[n.type] || ENTITY_META.survey;
                      const props = (n.props || {}) as Record<string, unknown>;
                      return (
                        <List.Item
                          actions={[
                            props.literature_id ? (
                              <TextLink key="lit" onClick={() => { setDrillOpen(false); navigate(`/literature/${props.literature_id}`); }}>
                                查看文献
                              </TextLink>
                            ) : null,
                          ].filter(Boolean)}
                        >
                          <Tag color={meta.color}>{meta.label}</Tag>
                          <span>{n.label}</span>
                          <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                            {n.survey_count ? `关联 ${n.survey_count} 项调查` : ''}
                            {props.year ? ` · ${props.year}年` : ''}
                            {props.disease ? ` · ${props.disease}` : ''}
                            {props.value != null ? ` · ${props.value}${props.unit || ''}` : ''}
                          </Text>
                        </List.Item>
                      );
                    }}
                  />
                ) : (
                  <List
                    size="small"
                    dataSource={filteredGraph?.edges ?? []}
                    renderItem={(e) => {
                      const src = filteredGraph?.nodes.find((n) => n.id === e.source);
                      const tgt = filteredGraph?.nodes.find((n) => n.id === e.target);
                      const em = RELATION_META[e.type] || { color: '#bfbfbf' };
                      return (
                        <List.Item>
                          <Tag color={em.color}>{e.type}</Tag>
                          <Text>{src?.label ?? e.source}</Text>
                          <Text type="secondary" style={{ margin: '0 6px' }}>→</Text>
                          <Text>{tgt?.label ?? e.target}</Text>
                        </List.Item>
                      );
                    }}
                  />
                )}
              </Drawer>

              {/* 持久化统计 + 手动抽取 */}
              <Card style={{ marginTop: 16 }}>
                <div style={{ marginBottom: 8 }}>
                  <Text type="secondary">抽取模型：</Text>
                  <Select
                    style={{ width: '100%' }}
                    value={kgModel}
                    placeholder="使用后端默认配置的模型"
                    allowClear
                    onChange={(v) => setKgModel(v || undefined)}
                    options={[
                      { value: '', label: '默认配置（后端 LLM_MODEL）' },
                      ...kgModelOptions.filter((o) => o.value !== 'ollama:custom').map((o) => ({ value: o.value, label: o.label })),
                    ]}
                  />
                  <Text type="secondary" style={{ fontSize: 12 }}>手动/定向抽取使用的 LLM 模型，默认取后端配置，可在此选择本地或远程已配置模型。</Text>
                </div>
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
                <Button icon={<MergeOutlined />} onClick={loadMergeCandidates} loading={mergeLoading}>合并候选</Button>
                <Button icon={<AuditOutlined />} onClick={loadQualitySample} loading={qualityLoading}>质量评估</Button>
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
                            <Divider type="vertical" />
                            <Button
                              size="small"
                              type={item.feedback === 'up' ? 'primary' : 'text'}
                              disabled={!!item.feedback}
                              onClick={() => handleQaFeedback(idx, 'up')}
                            >
                              有用
                            </Button>
                            <Button
                              size="small"
                              type={item.feedback === 'down' ? 'primary' : 'text'}
                              danger={item.feedback === 'down'}
                              disabled={!!item.feedback}
                              onClick={() => handleQaFeedback(idx, 'down')}
                            >
                              没用
                            </Button>
                          </Space>
                          {item.evidence.length > 0 && (
                            <div style={{ marginTop: 8 }}>
                              <Text type="secondary" style={{ fontSize: 12 }}>证据溯源（{item.evidence.length} 条）</Text>
                              <div style={{ maxHeight: 180, overflow: 'auto', marginTop: 4 }}>
                                {item.evidence.map((ev, i) => (
                                  <div key={i} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '4px 0', borderBottom: '1px dashed #f0f0f0' }}>
                                    <Text style={{ fontSize: 12, flex: 1 }}>
                                      {ev.title || (ev.province ? `${ev.province}${ev.city ? ev.city : ''}` : '未知来源')}
                                      {ev.year ? `（${ev.year}年）` : ''}
                                    </Text>
                                    <Space size={4} style={{ flexShrink: 0 }}>
                                      {ev.value != null && <Text type="secondary" style={{ fontSize: 12 }}>{ev.value}{ev.unit || '%'}</Text>}
                                      {ev.literature_id && (
                                        <TextLink
                                          style={{ fontSize: 12 }}
                                          onClick={(e) => { e.stopPropagation(); navigate(`/literature/${ev.literature_id}`); }}
                                        >
                                          查看文献
                                        </TextLink>
                                      )}
                                    </Space>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
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

      <Modal
        title="实体合并候选"
        open={mergeOpen}
        onCancel={() => setMergeOpen(false)}
        footer={null}
        width={720}
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          疑似重复实体（同名 / 高相似度）。每组保留第一个（蓝色）实体，其余合并到它名下（关系一并迁移）。合并需管理员权限。
        </Typography.Paragraph>
        {mergeCandidates.length === 0 ? (
          <Empty description="暂无疑似重复实体" />
        ) : (
          <List
            dataSource={mergeCandidates}
            renderItem={(g) => (
              <List.Item
                actions={[
                  g.members.length > 1 && (
                    <Button key="merge" size="small" type="primary" onClick={() => handleMergeGroup(g)}>合并</Button>
                  ),
                ]}
              >
                <div>
                  <Space size={8}>
                    <Tag color={ENTITY_META[g.entity_type]?.color}>{ENTITY_META[g.entity_type]?.label || g.entity_type}</Tag>
                    <Text type="secondary">{g.reason}</Text>
                  </Space>
                  <div style={{ marginTop: 4 }}>
                    {g.members.map((m, i) => (
                      <Tag key={m.id} color={i === 0 ? 'blue' : 'default'}>{m.name}（{m.triple_count} 边）</Tag>
                    ))}
                  </div>
                </div>
              </List.Item>
            )}
          />
        )}
      </Modal>

      <Modal
        title="抽取质量评估（抽样待校验三元组）"
        open={qualityOpen}
        onCancel={() => setQualityOpen(false)}
        footer={null}
        width={860}
      >
        <Space style={{ marginBottom: 12 }} wrap>
          <Text type="secondary">
            勾选后批量标记：正确 → 记入通过样本；错误 → 记入剔除样本；删除 → 直接从图谱移除。
          </Text>
          <Button size="small" type="primary" onClick={() => handleQualityReview('approved')}>标记为正确</Button>
          <Button size="small" danger onClick={() => handleQualityReview('rejected')}>标记为错误</Button>
          <Button size="small" type="primary" danger onClick={handleQualityDelete}>删除选中</Button>
        </Space>
        {qualityItems.length === 0 ? (
          <Empty description="暂无待校验的三元组（可先触发抽取生成数据）" />
        ) : (
          <List
            size="small"
            dataSource={qualityItems}
            renderItem={(t) => {
              const checked = qualitySelected.includes(t.id);
              const toggle = () => setQualitySelected((prev) => (checked ? prev.filter((x) => x !== t.id) : [...prev, t.id]));
              return (
                <List.Item
                  onClick={toggle}
                  style={{ cursor: 'pointer', paddingLeft: 4 }}
                  extra={<Checkbox checked={checked} onClick={(e) => e.stopPropagation()} onChange={toggle} />}
                >
                  <div style={{ flex: 1 }}>
                    <Space size={4} wrap>
                      <Tag color={ENTITY_META[t.subject_type]?.color || 'default'}>{t.subject}</Tag>
                      <Text type="secondary">—{t.predicate}→</Text>
                      <Tag color={ENTITY_META[t.object_type]?.color || 'default'}>{t.object}</Tag>
                      <Tag>{t.confidence < 0.8 ? `低置信 ${t.confidence.toFixed(2)}` : `置信 ${t.confidence.toFixed(2)}`}</Tag>
                    </Space>
                    <div style={{ marginTop: 2 }}>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        来源：{t.literature_title || '未知'}
                        {t.literature_id && (
                          <TextLink style={{ marginLeft: 8 }} onClick={(e) => { e.stopPropagation(); navigate(`/literature/${t.literature_id}`); }}>
                            查看文献
                          </TextLink>
                        )}
                      </Text>
                    </div>
                    {t.source_context && (
                      <Typography.Paragraph
                        type="secondary"
                        style={{ fontSize: 12, margin: '2px 0 0', maxHeight: 44, overflow: 'hidden' }}
                        ellipsis={{ rows: 2, expandable: true, symbol: '展开' }}
                      >
                        {t.source_context}
                      </Typography.Paragraph>
                    )}
                  </div>
                </List.Item>
              );
            }}
          />
        )}
      </Modal>
    </>
  );
};

export default KnowledgeGraph;
