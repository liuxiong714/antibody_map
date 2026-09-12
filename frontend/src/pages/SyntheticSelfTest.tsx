import React, { useState, useCallback, useEffect, useRef } from 'react';
import {
  Card, Form, Input, InputNumber, Select, Button, Table, Tag, Space, message,
  Row, Col, Statistic, Popconfirm, Tooltip, Alert, ConfigProvider,
} from 'antd';
import {
  PlayCircleOutlined, ExperimentOutlined, AuditOutlined,
  DownloadOutlined, EyeOutlined, ReloadOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import {
  createSynthetic, listSynthetic, triggerExtractSynthetic, getSynthetic,
  assessSynthetic, exportSynthetic, SyntheticTask, SyntheticPerNoise,
} from '../services/synthetic';
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
  const [detail, setDetail] = useState<SyntheticTask | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    buildModelOptions().then(setModelOptions);
    form.setFieldsValue({ disease: '麻疹', n_literatures: 20, points_per_literature: 20, noise_ratio: 0.2, seed: 42 });
  }, [form]);

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
      await createSynthetic({
        disease: values.disease,
        n_literatures: values.n_literatures,
        points_per_literature: values.points_per_literature,
        generator_model: values.generator_model,
        noise_ratio: values.noise_ratio,
        seed: values.seed,
      });
      message.success('自测任务已创建，正在后台生成合成文献');
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
      title: '提取模型 B',
      key: 'extractor',
      width: 180,
      render: (_: unknown, r) => r.extractor_model ? <Tag color="purple">{r.extractor_model}</Tag> : <span style={{ color: '#999' }}>-</span>,
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
      width: 320,
      render: (_: unknown, r) => (
        <Space size={4}>
          <Tooltip title="用提取模型 B 触发提取">
            <Space size={4}>
              <Select
                size="small"
                style={{ width: 160 }}
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
          <Tooltip title="执行评估">
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
        </Space>
      ),
    },
  ];

  const renderReport = (t: SyntheticTask) => {
    const rep = t.report;
    if (!rep) return <Alert type="info" showIcon message="该任务尚未生成评估报告，请先完成提取并执行评估" />;
    const fieldNames: Record<string, string> = {
      disease: '疾病', province: '省份', data_type: '数据类型',
      sample_size: '样本量', collection_year: '年份', value: '数值',
    };
    const prog = t.literature_progress || [];
    const hasPending = prog.some(p => !['done', 'done_no_data', 'failed'].includes(p.extraction_status));
    return (
      <>
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Card size="small"><Statistic title="文献数" value={t.n_literatures} suffix={`因${t.points_per_literature}点`} /></Card>
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

        <Card size="small" title="提取进度 / 逐文献明细">
          <Table
            rowKey="id"
            size="small"
            pagination={false}
            scroll={{ x: 700 }}
            dataSource={prog.map(p => {
              const row = (t.report_by_literature || []).find(r => r.literature_id === p.id);
              return { ...p, clean_total: row?.clean_total ?? 0, clean_matched: row?.clean_matched ?? 0, noise_total: row?.noise_total ?? 0, noise_rejected: row?.noise_rejected ?? 0 };
            })}
            columns={[
              { title: '文献', dataIndex: 'title', ellipsis: true },
              { title: '提取状态', dataIndex: 'extraction_status', width: 110 },
              { title: '清洁/命中', width: 90, render: (_: unknown, r: any) => `${r.clean_matched}/${r.clean_total}` },
              { title: '噪声/拒绝', width: 90, render: (_: unknown, r: any) => `${r.noise_rejected}/${r.noise_total}` },
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
          <Form.Item name="disease" label="疾病" rules={[{ required: true }]}>
            <Input style={{ width: 100 }} />
          </Form.Item>
          <Form.Item name="n_literatures" label="篇数">
            <InputNumber min={1} max={100} style={{ width: 90 }} />
          </Form.Item>
          <Form.Item name="points_per_literature" label="每篇点数">
            <InputNumber min={1} max={50} style={{ width: 90 }} />
          </Form.Item>
          <Form.Item name="generator_model" label="生成模型A" rules={[{ required: true, message: '请选择生成模型' }]}>
            <Select
              style={{ width: 200 }}
              placeholder="生成文献的模型"
              options={modelOptions.map(o => ({ label: o.label, value: o.value }))}
            />
          </Form.Item>
          <Form.Item name="noise_ratio" label="噪声比例">
            <InputNumber min={0} max={1} step={0.1} style={{ width: 90 }} />
          </Form.Item>
          <Form.Item name="seed" label="随机种子">
            <InputNumber style={{ width: 90 }} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" icon={<ExperimentOutlined />} loading={submitting} onClick={handleCreate}>开始生成</Button>
          </Form.Item>
        </Form>
        <Alert
          type="info"
          showIcon
          style={{ marginTop: 12 }}
          message="流程：选择生成模型A 量产含已知答案的合成文献（混入噪声）→ 选择提取模型B 走真实提取链路 → 执行评估比对提取值 vs 真实值。"
        />
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