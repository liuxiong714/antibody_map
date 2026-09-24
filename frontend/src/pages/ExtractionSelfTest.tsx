import React, { useState, useCallback, useEffect, useRef } from 'react';
import {
  Card, Form, Input, InputNumber, Select, Button, Table, Tag, Space, message,
  Row, Col, Statistic, Popconfirm, Tooltip, Alert, ConfigProvider, Checkbox, Modal, Radio,
} from 'antd';
import {
  PlayCircleOutlined, ExperimentOutlined, AuditOutlined,
  DownloadOutlined, EyeOutlined, ReloadOutlined, DeleteOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import api from '../services/api';
import {
  createSynthetic, listSynthetic, triggerExtractSynthetic, getSynthetic,
  assessSynthetic, exportSynthetic, deleteSynthetic, SyntheticTask,
  SyntheticPerNoise, SyntheticPoint, SyntheticLitRow, SyntheticMultiModel, SyntheticMultiLitModelInfo, SyntheticMultiLitRow,
  SyntheticRun, SyntheticComparisonItem,
} from '../services/synthetic';
import { listLiterature, listTags, TagItem } from '../services/literature';
import type { Literature } from '../types';
import { buildModelOptions, ExtendedModelOption } from '../utils/modelOptions';

const STATUS_MAP: Record<string, { color: string; text: string }> = {
  queued: { color: 'default', text: '排队中' },
  generating: { color: 'processing', text: '生成中' },
  ready: { color: 'blue', text: '待提取' },
  extracting: { color: 'processing', text: '提取中' },
  assessed: { color: 'success', text: '已评估' },
  failed: { color: 'error', text: '失败' },
};

const NOISE_LABEL: Record<string, string> = {
  out_of_range: '数值越界',
  missing_field: '缺关键字段',
  format_variant: '格式变异',
  wrong_value: '完全错误值',
};

const ExtractionSelfTest: React.FC = () => {
  const [form] = Form.useForm();
  const [tasks, setTasks] = useState<SyntheticTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [modelOptions, setModelOptions] = useState<ExtendedModelOption[]>([]);
  const [activeExtract, setActiveExtract] = useState<Record<string, string>>({});
  const [activeAssess, setActiveAssess] = useState<Record<string, boolean>>({});
  const [activeDelete, setActiveDelete] = useState<Record<string, boolean>>({});
  const [detail, setDetail] = useState<SyntheticTask | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 文献来源（generated / existing）
  const [litSource, setLitSource] = useState<'generated' | 'existing'>('generated');
  // existing 来源：已选文献列表（用于展示选中数）
  const [selectedLits, setSelectedLits] = useState<Array<{ id: string; title: string }>>([]);
  // 文献选择弹窗
  const [litModalOpen, setLitModalOpen] = useState(false);
  const [litOptions, setLitOptions] = useState<Literature[]>([]);
  const [litLoading, setLitLoading] = useState(false);
  const [litKeyword, setLitKeyword] = useState('');
  // 每行多模型对比选中
  const [activeModels, setActiveModels] = useState<Record<string, string[]>>({});
  // existing 来源：按编组选择（推荐）
  const [tagOptions, setTagOptions] = useState<TagItem[]>([]);
  const [selectedTagId, setSelectedTagId] = useState<string | undefined>();
  const [tagLitCount, setTagLitCount] = useState<number | null>(null);
  // 创建任务后待自动触发的批量评测（等 GT 就绪后串行跑多模型）
  const pendingRunRef = useRef<{ id: string; models: string[] } | null>(null);
  const autoTriggeredRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    buildModelOptions().then(setModelOptions);
    listTags().then(setTagOptions).catch(() => setTagOptions([]));
    form.setFieldsValue({ disease: '麻疹', n_literatures: 20, points_per_literature: 20, noise_ratio: 0.2, seed: 42, output_format: 'text', include_table: true });
  }, [form]);

  const openLitPicker = async () => {
    setLitModalOpen(true);
    setLitLoading(true);
    setLitKeyword('');
    setLitOptions([]);
    try {
      const { items } = await listLiterature({ page: 1, page_size: 100, keyword: '', has_abstract: true });
      setLitOptions(items || []);
    } catch {
      message.error('加载文献列表失败');
    } finally {
      setLitLoading(false);
    }
  };

  const fetchTasks = useCallback(async (silent = true) => {
    if (!silent) setLoading(true);
    try {
      const data = await listSynthetic();
      setTasks(data);
    } catch {
      if (!silent) message.error('加载自测任务失败');
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => { fetchTasks(false); }, [fetchTasks]);

  // 创建任务并选定模型后：等参考基准(GT)就绪（status=ready）即自动触发串行多模型批量评测
  useEffect(() => {
    const pending = pendingRunRef.current;
    if (!pending) return;
    const t = tasks.find(x => x.id === pending.id);
    if (!t) return;
    if (t.status === 'failed') {
      pendingRunRef.current = null;
      return;
    }
    if (t.status === 'ready' && !autoTriggeredRef.current.has(pending.id)) {
      autoTriggeredRef.current.add(pending.id);
      triggerExtractSynthetic(pending.id, null, pending.models)
        .then(() => message.success(`已开始串行批量评测：${pending.models.length} 个模型将依次跑完全部文献`))
        .catch((e: any) => message.error(e?.response?.data?.detail || '批量评测触发失败'))
        .finally(() => { pendingRunRef.current = null; fetchTasks(false); });
    }
  }, [tasks, fetchTasks]);

  // 轮询：存在 排队/生成/提取 状态时每 4 秒刷新一次
  useEffect(() => {
    const busy = tasks.some(t => ['queued', 'generating', 'extracting'].includes(t.status));
    if (busy && !pollRef.current) {
      pollRef.current = setInterval(() => { fetchTasks(); }, 4000);
    } else if (!busy && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  }, [tasks, fetchTasks]);

  const handleCreate = async () => {
    const values = await form.validateFields();
    setSubmitting(true);
    try {
      if (litSource === 'existing') {
        if (!selectedTagId && selectedLits.length === 0) {
          message.warning('请先选择文献编组（推荐）或手动选择已有文献');
          return;
        }
        if (!values.reference_model) {
          message.warning('请选择参考模型（用于产出基准GT）');
          return;
        }
        const models: string[] = values.extract_models || [];
        const created = await createSynthetic({
          disease: values.disease,
          n_literatures: selectedTagId ? (tagLitCount ?? 0) : selectedLits.length,
          points_per_literature: values.points_per_literature ?? 20,
          // existing 模式表单未渲染生成模型A，用参考模型兜底（existing 不真正生成文献，仅占位）
          generator_model: values.reference_model,
          noise_ratio: values.noise_ratio || 0,
          seed: values.seed ?? 42,
          output_format: 'text',
          include_table: true,
          literature_source: 'existing',
          literature_ids: selectedTagId ? undefined : selectedLits.map(l => l.id),
          tag_id: selectedTagId,
          reference_model: values.reference_model,
        });
        if (models.length > 0) {
          pendingRunRef.current = { id: created.id, models };
          message.success(`自测任务已创建，正在产出基准(GT)，就绪后将自动用 ${models.length} 个模型串行批量评测`);
        } else {
          message.success('自测任务已创建，正在用参考模型产出基准(GT)');
        }
      } else {
        await createSynthetic({
          disease: values.disease,
          n_literatures: values.n_literatures,
          points_per_literature: values.points_per_literature,
          generator_model: values.generator_model,
          noise_ratio: values.noise_ratio,
          seed: values.seed,
          output_format: values.output_format,
          include_table: values.include_table !== undefined ? values.include_table : true,
          literature_source: 'generated',
        });
        message.success('自测任务已创建，正在后台生成合成文献');
      }
      fetchTasks(false);
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '创建失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleExtract = async (task: SyntheticTask) => {
    const model = activeExtract[task.id];
    if (!model) {
      message.warning('请先选择提取模型 B');
      return;
    }
    try {
      await triggerExtractSynthetic(task.id, model);
      message.success('已触发提取，正在后台执行');
      fetchTasks(false);
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '触发提取失败');
    }
  };

  const handleMultiExtract = async (task: SyntheticTask) => {
    const models = activeModels[task.id];
    if (!models || models.length === 0) {
      message.warning('请至少选择多个提取模型');
      return;
    }
    try {
      await triggerExtractSynthetic(task.id, null, models);
      message.success(`已触发 ${models.length} 个模型对比提取，正在后台执行`);
      fetchTasks(false);
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '多模型提取触发失败');
    }
  };

  const handleAssess = async (task: SyntheticTask) => {
    setActiveAssess(prev => ({ ...prev, [task.id]: true }));
    try {
      await assessSynthetic(task.id);
      message.success('评估完成');
      fetchTasks(false);
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '评估失败');
    } finally {
      setActiveAssess(prev => ({ ...prev, [task.id]: false }));
    }
  };

  const handleExport = async (task: SyntheticTask) => {
    try {
      const blob = await exportSynthetic(task.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `synthetic_assessment_${task.disease}_${task.id}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      message.error('导出失败');
    }
  };

  const handleDelete = async (task: SyntheticTask) => {
    setActiveDelete((p) => ({ ...p, [task.id]: true }));
    try {
      await deleteSynthetic(task.id);
      message.success('已删除失败任务');
      if (pendingRunRef.current?.id === task.id) pendingRunRef.current = null;
      autoTriggeredRef.current.delete(task.id);
      await fetchTasks(false);
      if (detail?.id === task.id) setDetailOpen(false);
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '删除失败');
    } finally {
      setActiveDelete((p) => ({ ...p, [task.id]: false }));
    }
  };

  const handleViewDetail = async (task: SyntheticTask) => {
    setDetailOpen(true);
    setDetailLoading(true);
    setDetail(task);
    try {
      const d = await getSynthetic(task.id);
      setDetail(d);
    } catch {
      message.error('加载详情失败');
    } finally {
      setDetailLoading(false);
    }
  };

  const columns: ColumnsType<SyntheticTask> = [
    {
      title: '疾病',
      dataIndex: 'disease',
      key: 'disease',
      width: 80,
    },
    {
      title: '来源',
      key: 'source',
      width: 80,
      render: (_: unknown, r) => (
        r.literature_source === 'existing'
          ? <Tag color="orange">已有文献</Tag>
          : <Tag color="geekblue">生成</Tag>
      ),
    },
    {
      title: '文献/点数',
      key: 'dim',
      width: 110,
      render: (_: unknown, r) => `${r.n_literatures}篇 × ${r.points_per_literature}点`,
    },
    {
      title: '生成模型 A',
      dataIndex: 'generator_model',
      key: 'generator_model',
      width: 140,
      ellipsis: true,
      render: (v: string) => <Tag color="geekblue">{v}</Tag>,
    },
    {
      title: '提取模型',
      key: 'extractor',
      width: 190,
      render: (_: unknown, r) => {
        if (r.models && r.models.length) {
          return (
            <Space size={2} wrap>
              {r.models.map(m => <Tag key={m} color="purple">{m}</Tag>)}
            </Space>
          );
        }
        return r.extractor_model ? <Tag color="purple">{r.extractor_model}</Tag> : <span style={{ color: '#999' }}>-</span>;
      },
    },
    {
      title: '载体/表格',
      key: 'format',
      width: 110,
      render: (_: unknown, r) => (
        <Space size={4}>
          <Tag color={r.output_format === 'pdf' ? 'orange' : 'green'}>{r.output_format === 'pdf' ? 'PDF' : '文本'}</Tag>
          {r.include_table ? <Tag color="cyan">含表</Tag> : <span style={{ color: '#999' }}>无表</span>}
        </Space>
      ),
    },
    {
      title: '噪声比例',
      dataIndex: 'noise_ratio',
      key: 'noise_ratio',
      width: 90,
      render: (v: number) => `${Math.round(v * 100)}%`,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (v: string) => {
        const tag = STATUS_MAP[v] || { color: 'default', text: v };
        return <Tag color={tag.color}>{tag.text}</Tag>;
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 130,
      render: (v: string | null) => v ? dayjs(v).format('MM-DD HH:mm') : '-',
    },
    {
      title: '摘要指标',
      key: 'report',
      width: 130,
      render: (_: unknown, r) => {
        if (!r.report) return <span style={{ color: '#999' }}>-</span>;
        return (
          <Tooltip title={`提取召回 ${(r.report.clean_recall * 100).toFixed(1)}% | 噪声拒绝 ${(r.report.noise_rejection_rate * 100).toFixed(1)}%`}>
            <Space size={4}>
              <Tag>召回{(r.report.clean_recall * 100).toFixed(0)}%</Tag>
              <Tag>拒噪{(r.report.noise_rejection_rate * 100).toFixed(0)}%</Tag>
            </Space>
          </Tooltip>
        );
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 420,
      render: (_: unknown, r) => (
        <Space size={4} wrap>
          <Tooltip title="单模型：用提取模型 B 走真实提取链路写库">
            <Space size={4}>
              <Select
                size="small"
                style={{ width: 150 }}
                placeholder="提取模型B"
                allowClear
                value={activeExtract[r.id]}
                onChange={(v) => setActiveExtract(prev => ({ ...prev, [r.id]: v }))}
                options={modelOptions.map(o => ({ label: o.label, value: o.value }))}
              />
              <Button
                size="small"
                type="primary"
                icon={<PlayCircleOutlined />}
                disabled={!['ready', 'assessed', 'failed'].includes(r.status)}
                onClick={() => handleExtract(r)}
              />
            </Space>
          </Tooltip>
          <Tooltip title="多模型对比：选择多个模型对同批文献依次纯抽取并横向对比">
            <Space size={4}>
              <Select
                size="small"
                mode="multiple"
                maxTagCount="responsive"
                style={{ width: 180 }}
                placeholder="多模型对比"
                value={activeModels[r.id]}
                onChange={(v) => setActiveModels(prev => ({ ...prev, [r.id]: v }))}
                options={modelOptions.map(o => ({ label: o.label, value: o.value }))}
              />
              <Button
                size="small"
                type="default"
                icon={<ExperimentOutlined />}
                disabled={!['ready', 'assessed', 'extracting', 'failed'].includes(r.status)}
                onClick={() => handleMultiExtract(r)}
              />
            </Space>
          </Tooltip>
          <Tooltip title="执行评估（多模型任务产出多模型横向对比）">
            <Button
              size="small"
              icon={<AuditOutlined />}
              loading={!!activeAssess[r.id]}
              disabled={r.status !== 'extracting' && r.status !== 'assessed'}
              onClick={() => handleAssess(r)}
            />
          </Tooltip>
          <Tooltip title="查看报告">
            <Button size="small" icon={<EyeOutlined />} onClick={() => handleViewDetail(r)} />
          </Tooltip>
          <Popconfirm title="导出评估 CSV？" onConfirm={() => handleExport(r)} disabled={!r.report}>
            <Tooltip title="导出 CSV">
              <Button size="small" icon={<DownloadOutlined />} disabled={!r.report} />
            </Tooltip>
          </Popconfirm>
          <Popconfirm title="删除该失败任务及其合成文献？" onConfirm={() => handleDelete(r)} disabled={r.status !== 'failed'}>
            <Tooltip title="删除失败任务">
              <Button size="small" danger icon={<DeleteOutlined />} disabled={r.status !== 'failed'} loading={!!activeDelete[r.id]} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const renderMultiReport = (t: SyntheticTask) => {
    const multi = t.multi_model as SyntheticMultiModel | undefined;
    const fmtDur = (sec?: number | null) => {
      if (sec == null || Number.isNaN(sec)) return '—';
      const s = Math.round(sec);
      return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m${s % 60}s`;
    };
    const typeLabel = (dt?: string) => (dt === 'seroprevalence' ? '血清阳性率' : dt === 'gmc' ? '中和抗体' : (dt || '—'));
    const fmtVal = (p: SyntheticPoint) => `${p.value ?? '—'}${p.unit ?? ''}`;
    const collect = (r?: SyntheticPoint) => (r && r.collection_year != null) ? r.collection_year : '—';
    const comp = multi?.comparison || [];
    const byLit = multi?.by_literature || [];

    const modelColors = ['blue', 'purple', 'cyan', 'green', 'orange', 'magenta'];

    const renderLit = (row: SyntheticMultiLitRow, idx: number) => {
      const gts = row.gt_points || [];
      const models = row.models || {};
      const entries = Object.entries(models) as Array<[string, SyntheticMultiLitModelInfo]>;
      const gtCols = [
        { title: '#', dataIndex: 'idx', width: 40, render: (v: number) => v + 1 },
        { title: '数据类型', dataIndex: 'data_type', width: 92, render: typeLabel },
        { title: '真实值', dataIndex: '__v', width: 105, render: (_: unknown, r: SyntheticPoint) => fmtVal(r) },
        { title: '样本量', dataIndex: 'sample_size', width: 66, render: (v?: number | null) => v ?? '—' },
        { title: '省份', dataIndex: 'province', ellipsis: true },
        { title: '年份', dataIndex: 'collection_year', width: 56, render: collect },
        { title: '命中', dataIndex: 'matched', width: 80, render: (m?: boolean) => (m ? <Tag color="green">已命中</Tag> : <Tag color="red">未命中</Tag>) },
      ] as any;
      const exCols = (showInfo?: boolean) => [
        { title: '#', dataIndex: 'idx', width: 40, render: (v: number) => v + 1 },
        { title: '数据类型', dataIndex: 'data_type', width: 92, render: typeLabel },
        { title: '识别值', dataIndex: '__v', width: 100, render: (_: unknown, r: SyntheticPoint) => fmtVal(r) },
        { title: '省份', dataIndex: 'province', ellipsis: true },
        { title: '样本量', dataIndex: 'sample_size', width: 64, render: (v?: number | null) => v ?? '—' },
        { title: '年份', dataIndex: 'collection_year', width: 56, render: collect },
        { title: '比对', dataIndex: 'gt_idx', width: 92, render: (gi?: number | null) => (gi == null
            ? <Tag color="purple">额外识别</Tag>
            : <Tag color="green">对应GT#{gi + 1}</Tag>) },
      ] as any;
      return (
        <Row gutter={16}>
          <Col span={12}>
            <Card size="small" title={`真实数据点（GT）· 共 ${gts.length}`} style={{ marginBottom: 8 }}>
              <Table rowKey={(r: SyntheticPoint) => `g${r.idx}`} size="small" pagination={false}
                     dataSource={gts} columns={gtCols} scroll={{ x: 640 }} />
            </Card>
          </Col>
          <Col span={12}>
            {entries.map(([m, info], mi) => (
              <Card key={m} size="small"
                    title={<Space size={4}><Tag color={modelColors[mi % modelColors.length]}>{m}</Tag>
                      <span style={{ fontWeight: 'normal', fontSize: 12, color: '#888' }}>命中 {info.clean_matched}/{info.clean_total} · 拒噪 {info.noise_rejected}/{info.noise_total}</span></Space>}
                    style={{ marginBottom: 8 }}>
                <Table rowKey={(r: SyntheticPoint) => `e${mi}-${r.idx}`} size="small" pagination={false}
                       dataSource={info.extracted_points || []} columns={exCols()} scroll={{ x: 620 }} />
              </Card>
            ))}
          </Col>
        </Row>
      );
    };

    const runs = (t.runs || []) as SyntheticRun[];
    const stability = multi?.stability || [];
    const pct = (v?: number | null) => (v == null ? '—' : `${(v * 100).toFixed(1)}%`);
    const num = (v?: number | null, digits = 1) => (v == null ? '—' : Number(v).toFixed(digits));
    const gtSourceLabel = multi?.gt_source === 'reference_model'
      ? `参考模型一致性（GT=${t.reference_model || '参考模型'}）`
      : '程序植入真值（严格口径）';

    return (
      <>
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Card size="small">
              <Statistic title="测试文献" value={`${t.literature_count} 篇`} />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic title="对比模型（运行数）" value={comp.length} suffix="次" />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic title="GT 口径" value={gtSourceLabel} valueStyle={{ fontSize: 12 }} />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small"><Statistic title="总耗时" value={fmtDur(t.total_seconds)} /></Card>
          </Col>
        </Row>

        {runs.length > 0 && (
          <Card size="small" title="运行进度（每个模型跑完全部文献后再切换下一个）" style={{ marginBottom: 12 }}>
            <Table
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={runs}
              expandable={{
                expandedRowRender: (r: SyntheticRun) => (
                  <Table
                    rowKey={(x: any) => x.literature_id}
                    size="small"
                    pagination={false}
                    dataSource={r.items || []}
                    columns={[
                      { title: '文献', dataIndex: 'title', ellipsis: true },
                      { title: '状态', dataIndex: 'status', width: 90 },
                      { title: '数据点', dataIndex: 'points_count', width: 70 },
                      { title: '耗时(s)', width: 80, render: (_: any, x: any) => (x.duration_ms == null ? '—' : (x.duration_ms / 1000).toFixed(1)) },
                      { title: 'JSON', dataIndex: 'json_ok', width: 70, render: (v?: boolean | null) => (v == null ? '—' : v ? <Tag color="green">合法</Tag> : <Tag color="red">失败</Tag>) },
                      { title: '错误', dataIndex: 'error', ellipsis: true, render: (v?: string | null) => v || '—' },
                    ]}
                  />
                ),
              }}
              columns={[
                { title: '#', dataIndex: 'run_index', width: 46 },
                { title: '模型', dataIndex: 'model', render: (m: string, r: SyntheticRun) => <Tag color={modelColors[(r.run_index - 1) % modelColors.length]}>{m}</Tag> },
                {
                  title: '状态', dataIndex: 'status', width: 90,
                  render: (v: string) => {
                    const map: Record<string, { color: string; text: string }> = {
                      pending: { color: 'default', text: '待运行' },
                      running: { color: 'processing', text: '运行中' },
                      done: { color: 'success', text: '已完成' },
                      partial: { color: 'warning', text: '部分失败' },
                      failed: { color: 'error', text: '失败' },
                    };
                    const s = map[v] || { color: 'default', text: v };
                    return <Tag color={s.color}>{s.text}</Tag>;
                  },
                },
                { title: '进度', width: 100, render: (_: any, r: SyntheticRun) => `${r.literatures_done}/${r.literatures_total}${r.literatures_failed ? ` · 失败${r.literatures_failed}` : ''}` },
                { title: '数据点', width: 80, render: (_: any, r: SyntheticRun) => r.summary?.total_points ?? '—' },
                { title: '耗时', width: 90, render: (_: any, r: SyntheticRun) => fmtDur(r.duration_seconds) },
              ]}
              scroll={{ x: 700 }}
            />
            <Alert
              style={{ marginTop: 8 }}
              type={runs.every(r => ['done', 'failed', 'partial'].includes(r.status)) ? 'success' : 'info'}
              showIcon
              message={
                runs.every(r => ['done', 'failed', 'partial'].includes(r.status))
                  ? '全部模型运行结束，可执行评估生成指标'
                  : '仍有模型在串行运行中，评估可能不完整'
              }
            />
          </Card>
        )}

        <Card size="small" title="效率指标（每个模型每次运行）" style={{ marginBottom: 12 }}>
          <Table
            rowKey="model"
            size="small"
            pagination={false}
            dataSource={comp}
            columns={[
              { title: '模型(运行)', dataIndex: 'model', render: (m: string, r: SyntheticComparisonItem) => <Tag color={modelColors[(r.run_index ?? 1) % modelColors.length]}>{m}</Tag> },
              { title: '成功率', width: 100, render: (_: any, r: SyntheticComparisonItem) => `${pct(r.success_rate)}（${r.success ?? 0}成功/${r.no_data ?? 0}无数据/${r.failed ?? 0}失败）` },
              { title: '总数据点', dataIndex: 'total_points', width: 84 },
              { title: '均值/篇', dataIndex: 'avg_points_per_literature', width: 84 },
              { title: '单篇均耗时(s)', dataIndex: 'avg_duration_s', width: 110 },
              { title: '首token延迟(ms)', dataIndex: 'avg_first_token_ms', width: 120 },
              { title: '生成速度(t/s)', dataIndex: 'avg_tokens_per_sec', width: 110 },
              { title: '峰值显存(MB)', dataIndex: 'peak_vram_mb', width: 110 },
              { title: '运行耗时', width: 90, render: (_: any, r: SyntheticComparisonItem) => fmtDur(r.run_seconds) },
            ]}
            scroll={{ x: 1000 }}
          />
        </Card>

        <Card size="small" title="准确度指标（每个模型每次运行）" style={{ marginBottom: 12 }}>
          <Table
            rowKey="model"
            size="small"
            pagination={false}
            dataSource={comp}
            columns={[
              { title: '模型(运行)', dataIndex: 'model', render: (m: string, r: SyntheticComparisonItem) => <Tag color={modelColors[(r.run_index ?? 1) % modelColors.length]}>{m}</Tag> },
              { title: '字段P(宏)', width: 90, render: (_: any, r: SyntheticComparisonItem) => pct(r.field_prf_macro?.precision) },
              { title: '字段R(宏)', width: 90, render: (_: any, r: SyntheticComparisonItem) => pct(r.field_prf_macro?.recall) },
              { title: '字段F1(宏)', width: 90, render: (_: any, r: SyntheticComparisonItem) => pct(r.field_prf_macro?.f1) },
              { title: '值级准确度', width: 100, render: (_: any, r: SyntheticComparisonItem) => pct(r.value_accuracy) },
              { title: '清洁点召回', width: 100, render: (_: any, r: SyntheticComparisonItem) => `${pct(r.clean_recall)}（${r.clean_matched}/${r.clean_total}）` },
              { title: '噪声拒绝率', width: 100, render: (_: any, r: SyntheticComparisonItem) => pct(r.noise_rejection_rate) },
              { title: '幻觉率', width: 90, render: (_: any, r: SyntheticComparisonItem) => pct(r.hallucination_rate) },
              { title: '额外识别率', width: 100, render: (_: any, r: SyntheticComparisonItem) => pct(r.extra_rate) },
              { title: 'JSON合法率', width: 100, render: (_: any, r: SyntheticComparisonItem) => pct(r.json_ok_rate) },
            ]}
            scroll={{ x: 1000 }}
          />
          <div style={{ marginTop: 8, fontSize: 12, color: '#888' }}>
            幻觉率=产出点中原文无法溯源的比例（1 - 可溯源率）；额外识别率=产出点中未对应任何 GT 点的比例；字段 P/R/F1 为宏平均（P=正确数/产出点数，R=正确数/GT 清洁点数）。
          </div>
        </Card>

        {stability.length > 0 && (
          <Card size="small" title="同一模型多次运行稳定性（均值 ± 标准差）" style={{ marginBottom: 12 }}>
            <Table
              rowKey={(r: any) => r.model}
              size="small"
              pagination={false}
              dataSource={stability}
              columns={[
                { title: '模型', dataIndex: 'model', width: 200, render: (m: string) => <Tag>{m}</Tag> },
                { title: '运行次数', dataIndex: 'runs', width: 90 },
                { title: '字段F1(宏)', width: 140, render: (_: any, r: any) => `${pct(r.metrics?.field_f1_macro?.mean)} ± ${num(r.metrics?.field_f1_macro?.std, 3)}` },
                { title: '清洁点召回', width: 140, render: (_: any, r: any) => `${pct(r.metrics?.clean_recall?.mean)} ± ${num(r.metrics?.clean_recall?.std, 3)}` },
                { title: '幻觉率', width: 130, render: (_: any, r: any) => `${pct(r.metrics?.hallucination_rate?.mean)} ± ${num(r.metrics?.hallucination_rate?.std, 3)}` },
                { title: '单篇均耗时(s)', width: 130, render: (_: any, r: any) => `${num(r.metrics?.avg_duration_s?.mean)} ± ${num(r.metrics?.avg_duration_s?.std)}` },
                { title: '生成速度(t/s)', width: 130, render: (_: any, r: any) => `${num(r.metrics?.avg_tokens_per_sec?.mean, 2)} ± ${num(r.metrics?.avg_tokens_per_sec?.std, 2)}` },
              ]}
              scroll={{ x: 900 }}
            />
          </Card>
        )}

        <Card size="small" title="逐文献 · 多模型对比（点击行展开查看 GT 与各模型识别点）">
          <Table
            rowKey="literature_id"
            size="small"
            pagination={false}
            expandable={{ expandedRowRender: renderLit }}
            scroll={{ x: 700 }}
            dataSource={byLit.map((r) => ({
              literature_id: r.literature_id,
              title: r.title,
              gt_points: r.gt_points || [],
              models: r.models || {},
            }))}
            columns={[
              { title: '文献', dataIndex: 'title', ellipsis: true },
              ...(comp.map((c, i) => ({
                title: <Tag color={modelColors[i % modelColors.length]}>{c.model}</Tag>,
                key: c.model,
                width: 120,
                render: (_: any, r: any) => {
                  const info = (r.models as Record<string, SyntheticMultiLitModelInfo>)[c.model];
                  return info ? `${info.clean_matched}/${info.clean_total} · 拒${info.noise_rejected}/${info.noise_total}` : '-';
                },
              }))),
            ]}
          />
        </Card>
      </>
    );
  };

  const renderReport = (t: SyntheticTask) => {
    if (t.multi_model) return renderMultiReport(t);
    const rep = t.report;
    if (!rep) return <Alert type="info" showIcon message="该任务尚未生成评估报告，请先完成提取并执行评估" />;
    const fieldNames: Record<string, string> = {
      disease: '疾病', province: '省份', data_type: '数据类型',
      sample_size: '样本量', collection_year: '年份', value: '数值',
    };
    const fmtDur = (sec?: number | null) => {
      if (sec == null || Number.isNaN(sec)) return '—';
      const s = Math.round(sec);
      return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m${s % 60}s`;
    };
    const typeLabel = (dt?: string) => (dt === 'seroprevalence' ? '血清阳性率' : dt === 'gmc' ? '中和抗体' : (dt || '—'));
    const fmtVal = (p: SyntheticPoint) => `${p.value ?? '—'}${p.unit ?? ''}`;
    const prog = t.literature_progress || [];
    // existing 来源的单模型任务：get 返回 multi_progress 而非 literature_progress，
    // 用 report_by_literature 直接兜底渲染逐文献明细
    const litRows: SyntheticLitRow[] = prog.length > 0
      ? prog.map(p => {
          const row = (t.report_by_literature || []).find(r => r.literature_id === p.id);
          return {
            literature_id: p.id,
            title: row?.title || p.title,
            extraction_status: p.extraction_status,
            clean_total: row?.clean_total ?? 0,
            clean_matched: row?.clean_matched ?? 0,
            noise_total: row?.noise_total ?? 0,
            noise_rejected: row?.noise_rejected ?? 0,
            gt_points: row?.gt_points || [],
            extracted_points: row?.extracted_points || [],
          };
        })
      : (t.report_by_literature || []);
    const hasPending = prog.length > 0 && prog.some(p => !['done', 'done_no_data', 'failed'].includes(p.extraction_status));
    const totalPoints = t.n_literatures * t.points_per_literature;

    // 逐篇展开：左侧 GT 真实数据点表，右侧提取模型识别点表，以「命中/对应GT」高亮对比
    const renderLitPoints = (row: SyntheticLitRow) => {
      const gts = row.gt_points || [];
      const exs = row.extracted_points || [];
      const collect = (r?: SyntheticPoint) => (r && r.collection_year != null) ? r.collection_year : '—';
      const gtCols = [
        { title: '#', dataIndex: 'idx', width: 40, render: (v: number) => v + 1 },
        { title: '数据类型', dataIndex: 'data_type', width: 92, render: typeLabel },
        { title: '真实值', dataIndex: '__v', width: 105, render: (_: unknown, r: SyntheticPoint) => fmtVal(r) },
        { title: '样本量', dataIndex: 'sample_size', width: 66, render: (v?: number | null) => v ?? '—' },
        { title: '省份', dataIndex: 'province', ellipsis: true },
        { title: '年份', dataIndex: 'collection_year', width: 56, render: collect },
        { title: '噪声', dataIndex: 'noise_kind', width: 86, render: (k?: string) => (k ? <Tag color="orange">{NOISE_LABEL[k] || k}</Tag> : '-') },
        { title: '命中', dataIndex: 'matched', width: 84, render: (m?: boolean, r?: SyntheticPoint) => {
            if (r?.noise_kind) {
              return m ? <Tag color="red">被误采</Tag> : <Tag color="green">正确拒绝</Tag>;
            }
            return m ? <Tag color="green">已命中</Tag> : <Tag color="red">未命中</Tag>;
        } },
      ] as any;
      const exCols = [
        { title: '#', dataIndex: 'idx', width: 40, render: (v: number) => v + 1 },
        { title: '数据类型', dataIndex: 'data_type', width: 92, render: typeLabel },
        { title: '识别值', dataIndex: '__v', width: 105, render: (_: unknown, r: SyntheticPoint) => fmtVal(r) },
        { title: '省份', dataIndex: 'province', ellipsis: true },
        { title: '城市', dataIndex: 'city', width: 76, render: (v?: string | null) => v || '—' },
        { title: '样本量', dataIndex: 'sample_size', width: 66, render: (v?: number | null) => v ?? '—' },
        { title: '年份', dataIndex: 'collection_year', width: 56, render: collect },
        { title: '比对', dataIndex: 'gt_idx', width: 96, render: (gi?: number | null) => (gi == null
            ? <Tag color="purple">额外识别</Tag>
            : <Tag color="green">对应GT#{gi + 1}</Tag>) },
      ] as any;
      const openFile = async () => {
        try {
          const resp = await api.get(`/literatures/${row.literature_id}/file`, { responseType: 'blob' });
          const url = URL.createObjectURL(resp.data);
          window.open(url, '_blank');
        } catch { message.error('文献文件加载失败'); }
      };
      return (
        <>
          <div style={{ marginBottom: 8 }}>
            <Space>
              <Button size="small" onClick={openFile} icon={<EyeOutlined />}>
                查看生成的文献{t.output_format === 'pdf' ? '（PDF）' : '（文本）'}
              </Button>
            </Space>
          </div>
          <Row gutter={16}>
            <Col span={12}>
              <Card size="small" title={`真实数据点 · 共 ${gts.length} 个`} style={{ marginBottom: 8 }}>
                <Table rowKey={(r: SyntheticPoint) => `g${r.idx}`} size="small" pagination={false}
                       dataSource={gts} columns={gtCols} scroll={{ x: 720 }} />
              </Card>
            </Col>
            <Col span={12}>
              <Card size="small" title={`提取识别点 · 共 ${exs.length} 个`} style={{ marginBottom: 8 }}>
                <Table rowKey={(r: SyntheticPoint) => `e${r.idx}`} size="small" pagination={false}
                       dataSource={exs} columns={exCols} scroll={{ x: 720 }} />
              </Card>
            </Col>
          </Row>
        </>
      );
    };

    return (
      <>
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Card size="small">
              <Statistic title="文献规模" value={`${t.n_literatures} 篇`}
                suffix={`× ${t.points_per_literature} 点/篇 = ${totalPoints} 数据点`} />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small"><Statistic title="清洁点召回" value={rep.clean_recall} precision={2} suffix={`(${rep.clean_matched}/${rep.clean_total}点)`} /></Card>
          </Col>
          <Col span={6}>
            <Card size="small"><Statistic title="精确值率" value={rep.value_exact_rate} precision={2} /></Card>
          </Col>
          <Col span={6}>
            <Card size="small"><Statistic title="噪声拒绝率" value={rep.noise_rejection_rate} precision={2} suffix={`(${rep.noise_rejected}/${rep.noise_total})`} valueStyle={{ color: '#52c41a' }} /></Card>
          </Col>
        </Row>

        {(t.generation_seconds != null || t.extraction_seconds != null || t.total_seconds != null) && (
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={8}><Card size="small"><Statistic title="生成耗时" value={fmtDur(t.generation_seconds)} /></Card></Col>
            <Col span={8}><Card size="small"><Statistic title="提取耗时" value={fmtDur(t.extraction_seconds)} /></Card></Col>
            <Col span={8}><Card size="small"><Statistic title="总耗时" value={fmtDur(t.total_seconds)} /></Card></Col>
          </Row>
        )}

        {prog.length > 0 && (
          <Alert
            style={{ marginBottom: 12 }}
            type={hasPending ? 'info' : 'success'}
            showIcon
            message={hasPending ? '仍有文献正在提取，评估可能不完整' : '全部文献提取完成'}
          />
        )}

        <ConfigProvider renderEmpty={() => <span>-</span>}>
          <Row gutter={16}>
            <Col span={12}>
              <Card size="small" title="字段级准确度" style={{ marginBottom: 12 }}>
                <Table
                  rowKey="field"
                  size="small"
                  pagination={false}
                  dataSource={Object.entries(rep.field_accuracy || {}).map(([f, v]) => ({ field: f, name: fieldNames[f] || f, v }))}
                  columns={[
                    { title: '字段', dataIndex: 'name', width: 100 },
                    { title: '准确率', dataIndex: 'v', render: (v: number) => `${(v * 100).toFixed(0)}%` },
                  ]}
                />
              </Card>
            </Col>
            <Col span={12}>
              <Card size="small" title="分噪声类型拒绝率">
                <Table
                  rowKey="kind"
                  size="small"
                  pagination={false}
                  dataSource={Object.entries(rep.per_noise_type || {}).map(([k, v]) => ({ kind: k, ...v }))}
                  columns={[
                    { title: '噪声类型', dataIndex: 'kind', render: (k: string) => NOISE_LABEL[k] || k },
                    { title: '点数', dataIndex: 'total', width: 60 },
                    { title: '拒绝', dataIndex: 'rejected', width: 60 },
                    { title: '拒绝率', dataIndex: 'rejection_rate', width: 80, render: (v: number) => `${(v * 100).toFixed(0)}%` },
                  ]}
                />
              </Card>
            </Col>
          </Row>
        </ConfigProvider>

        <Card size="small" title="提取进度 / 逐文献明细（点击行展开查看真实与识别数据点比对）">
          <Table
            rowKey={(r: SyntheticLitRow) => r.literature_id}
            size="small"
            pagination={false}
            expandable={{ expandedRowRender: renderLitPoints }}
            scroll={{ x: 700 }}
            dataSource={litRows}
            columns={[
              { title: '文献', dataIndex: 'title', ellipsis: true },
              { title: '提取状态', dataIndex: 'extraction_status', width: 110 },
              { title: '清洁/命中', width: 90, render: (_: unknown, r: SyntheticLitRow) => `${r.clean_matched}/${r.clean_total}` },
              { title: '噪声/拒绝', width: 90, render: (_: unknown, r: SyntheticLitRow) => `${r.noise_rejected}/${r.noise_total}` },
            ]}
          />
        </Card>
      </>
    );
  };

  return (
    <div>
      <Card title="AI 提取准确度自测" style={{ marginBottom: 16 }}>
        <Form form={form} layout="inline" style={{ rowGap: 12 }}>
          <Form.Item label="文献来源">
            <Radio.Group
              value={litSource}
              onChange={(e) => setLitSource(e.target.value)}
              options={[
                { value: 'generated', label: '生成模型模拟' },
                { value: 'existing', label: '数据库已有文献' },
              ]}
              optionType="button"
              buttonStyle="solid"
            />
          </Form.Item>
          <Form.Item name="disease" label="疾病" rules={[{ required: true }]}>
            <Input style={{ width: 100 }} />
          </Form.Item>

          {litSource === 'generated' ? (
            <>
              <Form.Item name="n_literatures" label="篇数">
                <InputNumber min={1} max={100} style={{ width: 90 }} />
              </Form.Item>
              <Form.Item name="points_per_literature" label="每篇点数">
                <InputNumber min={1} max={50} style={{ width: 90 }} />
              </Form.Item>
            </>
          ) : (
            <>
              <Form.Item label="文献编组" tooltip="推荐：按编组取该编组下全部文献（不受分页限制）">
                <Space size={4}>
                  <Select
                    allowClear
                    style={{ width: 180 }}
                    placeholder="选择编组（推荐）"
                    value={selectedTagId}
                    onChange={(v) => {
                      setSelectedTagId(v);
                      setSelectedLits([]);
                      setTagLitCount(null);
                      if (v) {
                        listLiterature({ page: 1, page_size: 1, tag_id: v })
                          .then(({ total }) => setTagLitCount(total ?? 0))
                          .catch(() => setTagLitCount(null));
                      }
                    }}
                    options={tagOptions.map(t => ({ label: t.name, value: t.id }))}
                  />
                  {selectedTagId && <Tag color="green">{tagLitCount == null ? '统计中…' : `${tagLitCount} 篇`}</Tag>}
                </Space>
              </Form.Item>
              <Form.Item label="或手动选文献">
                <Space size={4}>
                  <Button onClick={openLitPicker} icon={<EyeOutlined />} disabled={!!selectedTagId}>选择文献</Button>
                  <Tag color={selectedLits.length ? 'green' : 'default'}>{selectedLits.length} 篇</Tag>
                </Space>
              </Form.Item>
            </>
          )}

          {litSource === 'generated' ? (
            <Form.Item name="generator_model" label="生成模型A" rules={[{ required: true, message: '请选择生成模型' }]}>
              <Select
                style={{ width: 190 }}
                placeholder="生成文献的模型"
                options={modelOptions.map(o => ({ label: o.label, value: o.value }))}
              />
            </Form.Item>
          ) : (
            <>
              <Form.Item name="reference_model" label="参考模型" rules={[{ required: true, message: '请选择参考模型' }]}>
                <Select
                  style={{ width: 190 }}
                  placeholder="产出基准GT的模型"
                  options={modelOptions.map(o => ({ label: o.label, value: o.value }))}
                />
              </Form.Item>
              <Form.Item
                name="extract_models"
                label="对比模型（可多选）"
                tooltip="选定后：创建任务 → 参考基准(GT)就绪 → 自动按顺序逐个模型跑完全部文献（每篇均跳过缓存取新结果，各次运行分别留存）"
              >
                <Select
                  mode="multiple"
                  maxTagCount="responsive"
                  style={{ width: 280 }}
                  placeholder="选择多个提取模型（留空则稍后手动触发）"
                  options={modelOptions.map(o => ({ label: o.label, value: o.value }))}
                />
              </Form.Item>
            </>
          )}

          {litSource === 'generated' && (
            <>
              <Form.Item name="noise_ratio" label="噪声比例">
                <InputNumber min={0} max={1} step={0.1} style={{ width: 90 }} />
              </Form.Item>
              <Form.Item name="seed" label="随机种子">
                <InputNumber style={{ width: 90 }} />
              </Form.Item>
              <Form.Item name="output_format" label="文献载体">
                <Select style={{ width: 110 }} options={[
                  { value: 'text', label: '纯文本全文' },
                  { value: 'pdf', label: 'PDF文件' },
                ]} />
              </Form.Item>
              <Form.Item name="include_table" valuePropName="checked" tooltip="结果部分是否包含表格（text=Markdown 表格 / pdf=PDF 表格）">
                <Checkbox>含表格</Checkbox>
              </Form.Item>
            </>
          )}

          <Form.Item>
            <Button type="primary" icon={<ExperimentOutlined />} loading={submitting} onClick={handleCreate}>
              {litSource === 'existing' ? '创建并开始批量评测' : '开始生成'}
            </Button>
          </Form.Item>
        </Form>
        <Alert
          type="info"
          showIcon
          style={{ marginTop: 12 }}
          message={
            litSource === 'existing'
              ? '流程（推荐用编组）：选择编组（如 beijing20）→ 用参考模型产出基准GT → 选定多个对比模型 → 系统先让第 1 个模型跑完编组内全部文献（跳过缓存取新结果），再切换下一个模型，依次完成 → 逐模型产出效率指标（首token延迟/生成速度/单篇耗时/峰值显存/成功率）与准确度指标（字段级P/R/F1/值级准确度/幻觉率/JSON合法率）。'
              : '流程：选择生成模型A 量产含已知答案的合成文献（混入噪声）→ 选择提取模型 走真实提取链路 → 执行评估比对提取值 vs 真实值。'
          }
        />
        <Modal
          title="选择测试文献"
          open={litModalOpen}
          onCancel={() => setLitModalOpen(false)}
          onOk={() => setLitModalOpen(false)}
          width={780}
          footer={<Button type="primary" onClick={() => setLitModalOpen(false)}>完成选择（{selectedLits.length} 篇）</Button>}
        >
          <Input.Search
            allowClear
            placeholder="输入关键词即时筛选；回车搜索数据库（上限100篇）"
            value={litKeyword}
            onChange={(e) => setLitKeyword(e.target.value)}
            onSearch={(kw) => {
              setLitLoading(true);
              listLiterature({ page: 1, page_size: 100, keyword: kw || '', has_abstract: true })
                .then(({ items }) => setLitOptions(items || []))
                .catch(() => message.error('搜索文献失败'))
                .finally(() => setLitLoading(false));
            }}
            style={{ marginBottom: 12 }}
          />
          <div style={{ maxHeight: 480, overflowY: 'auto', border: '1px solid #f0f0f0', borderRadius: 8 }}>
            <Table<Literature>
              size="small"
              loading={litLoading}
              rowKey={(r) => r.id}
              dataSource={litOptions.filter(l => !litKeyword || ['title', 'province', 'source'].some(k =>
                String((l as any)[k] || '').toLowerCase().includes(litKeyword.toLowerCase())))}
              rowSelection={{
                selectedRowKeys: selectedLits.map(l => l.id),
                // 用全量 litOptions 反查选中标题，跨页搜索时只更新选中集合，不丢已选项
                onChange: (keys) =>
                  setSelectedLits(litOptions.filter(l => (keys as (string)[]).includes(l.id)).map(l => ({ id: l.id, title: l.title }))),
              }}
              pagination={{ pageSize: 10, showSizeChanger: true, showTotal: (t) => `共 ${t} 篇` }}
              locale={{ emptyText: '暂无文献' }}
              columns={[
                { title: '标题', dataIndex: 'title', ellipsis: true },
                { title: '省份', dataIndex: 'province', width: 80, render: (v?: string | null) => v || '-' },
                { title: '年份', dataIndex: 'pub_year', width: 70, render: (v?: number | null) => v || '-' },
                { title: '状态', dataIndex: 'extraction_status', width: 90 },
              ]}
            />
          </div>
        </Modal>
      </Card>

      <Table
        rowKey="id"
        columns={columns}
        dataSource={tasks}
        loading={loading}
        size="small"
        pagination={{ pageSize: 10, showSizeChanger: true }}
        locale={{ emptyText: <span style={{ color: '#999' }}>暂无自测任务</span> }}
        scroll={{ x: 1300 }}
      />

      <Button icon={<ReloadOutlined />} style={{ marginTop: 8 }} onClick={() => fetchTasks(false)}>刷新</Button>

      {/* 详情 / 报告 Drawer */}
      <Card
        title={detail ? `评估报告 - ${detail.disease}（${detail.generator_model} 生成）` : '评估报告'}
        style={{
          marginTop: 16,
          display: detailOpen && detail ? 'block' : 'none',
        }}
        loading={detailLoading}
        extra={
          <Space>
            {detail && ['extracting', 'assessed'].includes(detail.status) && (
              <Button size="small" icon={<AuditOutlined />} onClick={() => handleAssess(detail)}>重新评估</Button>
            )}
            {detail?.status === 'failed' && (
              <Popconfirm title="删除该失败任务及其合成文献？" onConfirm={() => detail && handleDelete(detail)}>
                <Button size="small" danger icon={<DeleteOutlined />} loading={!!(detail && activeDelete[detail.id])}>删除任务</Button>
              </Popconfirm>
            )}
            <Button size="small" type="primary" icon={<DownloadOutlined />} disabled={!detail?.report} onClick={() => detail && handleExport(detail)}>导出CSV</Button>
            <Button size="small" onClick={() => setDetailOpen(false)}>关闭</Button>
          </Space>
        }
      >
        {detail && renderReport(detail)}
      </Card>
    </div>
  );
};

export default ExtractionSelfTest;
