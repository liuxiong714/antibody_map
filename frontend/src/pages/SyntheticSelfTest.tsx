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
} from '../services/synthetic';
import { listLiterature } from '../services/literature';
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

const SyntheticSelfTest: React.FC = () => {
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

  useEffect(() => {
    buildModelOptions().then(setModelOptions);
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
        if (selectedLits.length === 0) {
          message.warning('请先选择已有文献');
          return;
        }
        if (!values.reference_model) {
          message.warning('请选择参考模型（用于产出基准GT）');
          return;
        }
        await createSynthetic({
          disease: values.disease,
          n_literatures: selectedLits.length,
          points_per_literature: values.points_per_literature ?? 20,
          // existing 模式表单未渲染生成模型A，用参考模型兜底（existing 不真正生成文献，仅占位）
          generator_model: values.reference_model,
          noise_ratio: values.noise_ratio || 0,
          seed: values.seed ?? 42,
          output_format: 'text',
          include_table: true,
          literature_source: 'existing',
          literature_ids: selectedLits.map(l => l.id),
          reference_model: values.reference_model,
        });
        message.success('自测任务已创建，正在用参考模型产出基准(GT)');
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

    return (
      <>
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Card size="small">
              <Statistic title="测试文献" value={`${t.literature_count} 篇`} />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small"><Statistic title="对比模型" value={comp.length} suffix="个" /></Card>
          </Col>
          <Col span={6}>
            <Card size="small"><Statistic title="参考模型(GT)" value={t.reference_model || '—'} valueStyle={{ fontSize: 14 }} /></Card>
          </Col>
          <Col span={6}>
            <Card size="small"><Statistic title="总耗时" value={fmtDur(t.total_seconds)} /></Card>
          </Col>
        </Row>

        <Card size="small" title="多模型横向指标对比" style={{ marginBottom: 12 }}>
          <Table
            rowKey="model"
            size="small"
            pagination={false}
            dataSource={comp.map((c, i) => ({ ...c, __color: modelColors[i % modelColors.length] }))}
            columns={[
              { title: '模型', dataIndex: 'model', render: (m: string, r: any) => <Tag color={r.__color}>{m}</Tag> },
              { title: '清洁点', dataIndex: 'clean_total', width: 70 },
              { title: '命中', dataIndex: 'clean_matched', width: 70 },
              { title: '召回率', dataIndex: 'clean_recall', width: 90, render: (v: number) => `${(v * 100).toFixed(1)}%` },
              { title: '精确值率', dataIndex: 'value_exact_rate', width: 90, render: (v: number) => `${(v * 100).toFixed(1)}%` },
              { title: '噪声点', dataIndex: 'noise_total', width: 70 },
              { title: '拒噪', dataIndex: 'noise_rejected', width: 70 },
              { title: '噪声拒绝率', dataIndex: 'noise_rejection_rate', width: 100, render: (v: number) => `${(v * 100).toFixed(1)}%` },
            ]}
            scroll={{ x: 700 }}
          />
        </Card>

        {t.multi_progress && t.multi_progress.length > 0 && (
          <Alert
            style={{ marginBottom: 12 }}
            type={t.multi_progress.some(p => p.status !== 'done') ? 'info' : 'success'}
            showIcon
            message={t.multi_progress.some(p => p.status !== 'done') ? '部分模型/文献仍在提取，评估可能不完整' : '全部模型提取完成'}
          />
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
            <Form.Item label="所选文献">
              <Space size={4}>
                <Button onClick={openLitPicker} icon={<EyeOutlined />}>选择文献</Button>
                <Tag color={selectedLits.length ? 'green' : 'default'}>{selectedLits.length} 篇</Tag>
              </Space>
            </Form.Item>
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
            <Form.Item name="reference_model" label="参考模型" rules={[{ required: true, message: '请选择参考模型' }]}>
              <Select
                style={{ width: 190 }}
                placeholder="产出基准GT的模型"
                options={modelOptions.map(o => ({ label: o.label, value: o.value }))}
              />
            </Form.Item>
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
              {litSource === 'existing' ? '创建自测任务' : '开始生成'}
            </Button>
          </Form.Item>
        </Form>
        <Alert
          type="info"
          showIcon
          style={{ marginTop: 12 }}
          message={
            litSource === 'existing'
              ? '流程：从数据库已有文献中手动选择 → 用参考模型对所选文献纯抽取产出基准GT → 选择多个提取模型批量对比抽取 → 执行评估横向比较各模型准确度。'
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

export default SyntheticSelfTest;