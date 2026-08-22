import React, { useEffect, useState } from 'react';
import {
  Modal, Table, Space, Button, Input, Select, Tag, Popconfirm,
  Form, Switch, message, Card, Row, Col, Empty, Divider,
} from 'antd';
import {
  PlusOutlined, DeleteOutlined, EditOutlined, UpOutlined,
  DownOutlined, SaveOutlined, CloseOutlined,
} from '@ant-design/icons';
import { listTemplates, createTemplate, updateTemplate, deleteTemplate } from '../services/map';
import { ReportTemplate, ReportSection } from '../types';

interface Props {
  visible: boolean;
  reportType: 'antibody_analysis' | 'vaccination_strategy';
  onClose: () => void;
  onSaved: () => void;
}

const SECTION_TYPES = [
  { value: 'kpi', label: '关键指标卡片' },
  { value: 'chart', label: '图表（趋势/地区/年龄）' },
  { value: 'table', label: '数据表格' },
  { value: 'text', label: '文本（LLM生成）' },
] as const;

const CHART_ANALYSIS = [
  { value: 'trend', label: '时间趋势' },
  { value: 'region', label: '地区分布' },
  { value: 'age_curve', label: '年龄分布' },
  { value: 'disease', label: '疾病分布' },
] as const;

const TABLE_DATA = [
  { value: 'province', label: '分省表' },
  { value: 'year', label: '分年表' },
  { value: 'age', label: '分年龄表' },
  { value: 'disease', label: '分疾病表' },
] as const;

const KPI_KEYS = [
  { value: 'literature_count', label: '文献数' },
  { value: 'point_count', label: '数据点' },
  { value: 'province_count', label: '覆盖省份' },
  { value: 'total_samples', label: '样本量' },
  { value: 'weighted_rate', label: '加权阳性率' },
] as const;

const emptySection = (order: number): ReportSection => ({
  title: '新章节',
  type: 'text',
  content_template: '',
  order,
});

const TemplateManager: React.FC<Props> = ({ visible, reportType, onClose, onSaved }) => {
  const [templates, setTemplates] = useState<ReportTemplate[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  // 编辑表单状态
  const [form] = Form.useForm();
  const [sections, setSections] = useState<ReportSection[]>([]);

  const fetchTemplates = async () => {
    setLoading(true);
    try {
      const data = await listTemplates(reportType);
      setTemplates(data);
    } catch (err) {
      console.error('[TemplateManager] 加载模板失败:', err);
      message.error('加载模板失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (visible) {
      fetchTemplates();
      setSelectedId(null);
      setCreating(false);
      setSections([]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, reportType]);

  const selectTemplate = (t: ReportTemplate) => {
    setSelectedId(t.id);
    setCreating(false);
    form.setFieldsValue({ name: t.name, report_type: t.report_type, is_default: t.is_default, desc: t.desc });
    setSections((t.sections || []).map((s, i) => ({ ...s, order: s.order ?? i })));
  };

  const newTemplate = () => {
    setSelectedId(null);
    setCreating(true);
    form.setFieldsValue({ name: '', report_type: reportType, is_default: false, desc: '' });
    setSections([emptySection(0), emptySection(1)]);
  };

  const moveSection = (index: number, dir: -1 | 1) => {
    setSections((prev) => {
      const next = [...prev];
      const target = index + dir;
      if (target < 0 || target >= next.length) return prev;
      [next[index], next[target]] = [next[target], next[index]];
      return next.map((s, i) => ({ ...s, order: i }));
    });
  };

  const removeSection = (index: number) => {
    setSections((prev) => prev.filter((_, i) => i !== index).map((s, i) => ({ ...s, order: i })));
  };

  const addSection = () => {
    setSections((prev) => [...prev, emptySection(prev.length)]);
  };

  const updateSection = (index: number, patch: Partial<ReportSection>) => {
    setSections((prev) => prev.map((s, i) => (i === index ? { ...s, ...patch } : s)));
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    if (sections.length === 0) {
      message.warning('请至少添加一个章节');
      return;
    }
    if (sections.some((s) => !s.title || !s.type)) {
      message.warning('每个章节必须填写标题并选择类型');
      return;
    }
    const payload = {
      name: values.name,
      report_type: values.report_type as ReportTemplate['report_type'],
      is_default: !!values.is_default,
      desc: values.desc,
      sections,
    };
    setSaving(true);
    try {
      if (selectedId) {
        await updateTemplate(selectedId, payload);
        message.success('模板已更新');
      } else {
        await createTemplate(payload);
        message.success('模板已创建');
      }
      await fetchTemplates();
      onSaved();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || '保存失败';
      message.error(`保存失败: ${detail}`);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteTemplate(id);
      message.success('模板已删除');
      if (selectedId === id) {
        setSelectedId(null);
        form.resetFields();
        setSections([]);
      }
      fetchTemplates();
      onSaved();
    } catch (err: any) {
      message.error(`删除失败: ${err?.response?.data?.detail || err?.message}`);
    }
  };

  const columns = [
    { title: '模板名称', dataIndex: 'name', key: 'name' },
    {
      title: '类型', dataIndex: 'report_type', key: 'rt', width: 120,
      render: (v: string) => v === 'vaccination_strategy' ? <Tag color="green">接种策略</Tag> : <Tag color="blue">抗体分析</Tag>,
    },
    { title: '章节数', key: 'sec', width: 80, render: (_: unknown, r: ReportTemplate) => (r.sections || []).length },
    {
      title: '默认', dataIndex: 'is_default', key: 'def', width: 80,
      render: (v: boolean) => v ? <Tag color="orange">默认</Tag> : '-',
    },
    {
      title: '操作', key: 'action', width: 160,
      render: (_: unknown, r: ReportTemplate) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => selectTemplate(r)}>编辑</Button>
          <Popconfirm title="确认删除该模板？" onConfirm={() => handleDelete(r.id)} okButtonProps={{ danger: true }}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const editing = creating || selectedId !== null;

  return (
    <Modal
      title="报告模板管理"
      open={visible}
      onCancel={onClose}
      width={1080}
      footer={[
        <Button key="close" onClick={onClose} icon={<CloseOutlined />}>关闭</Button>,
      ]}
    >
      <Row gutter={16}>
        <Col span={10}>
          <Card size="small" title="模板列表">
            <div style={{ marginBottom: 8 }}>
              <Button size="small" type="primary" icon={<PlusOutlined />} onClick={newTemplate}>新建模板</Button>
            </div>
            <Table
              size="small"
              rowKey="id"
              columns={columns}
              dataSource={templates}
              loading={loading}
              pagination={false}
              locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无模板" /> }}
            />
          </Card>
        </Col>
        <Col span={14}>
          <Card size="small" title={selectedId || form.getFieldValue('name') ? '编辑模板' : '请选择或新建模板'}>
            {!editing ? (
              <Empty description="选择左侧模板进行编辑，或点击“新建模板”" />
            ) : (
              <>
                <Form form={form} layout="vertical">
                  <Row gutter={12}>
                    <Col span={12}>
                      <Form.Item name="name" label="模板名称" rules={[{ required: true, message: '请输入模板名称' }]}>
                        <Input placeholder="模板名称" />
                      </Form.Item>
                    </Col>
                    <Col span={12}>
                      <Form.Item name="desc" label="模板描述">
                        <Input placeholder="模板描述（选填）" />
                      </Form.Item>
                    </Col>
                  </Row>
                  <Row gutter={12}>
                    <Col span={12}>
                      <Form.Item name="report_type" label="报告类型" rules={[{ required: true }]}>
                        <Select
                          options={[
                            { value: 'antibody_analysis', label: '抗体分析' },
                            { value: 'vaccination_strategy', label: '疫苗接种策略' },
                          ]}
                        />
                      </Form.Item>
                    </Col>
                    <Col span={12}>
                      <Form.Item name="is_default" label="设为默认" valuePropName="checked">
                        <Switch checkedChildren="默认" unCheckedChildren="普通" />
                      </Form.Item>
                    </Col>
                  </Row>
                </Form>

                <Divider style={{ margin: '12px 0' }}>章节编排</Divider>

                {sections.map((s, index) => (
                  <Card
                    key={index}
                    size="small"
                    style={{ marginBottom: 8 }}
                    title={
                      <Space>
                        <Tag color="blue">{index + 1}</Tag>
                        <span>{s.title || '未命名章节'}</span>
                      </Space>
                    }
                    extra={
                      <Space>
                        <Button size="small" icon={<UpOutlined />} disabled={index === 0} onClick={() => moveSection(index, -1)} />
                        <Button size="small" icon={<DownOutlined />} disabled={index === sections.length - 1} onClick={() => moveSection(index, 1)} />
                        <Popconfirm title="删除该章节？" onConfirm={() => removeSection(index)}>
                          <Button size="small" danger icon={<DeleteOutlined />} />
                        </Popconfirm>
                      </Space>
                    }
                  >
                    <Space direction="vertical" style={{ width: '100%' }}>
                      <Row gutter={8}>
                        <Col span={14}>
                          <Input
                            placeholder="章节标题"
                            value={s.title}
                            onChange={(e) => updateSection(index, { title: e.target.value })}
                          />
                        </Col>
                        <Col span={10}>
                          <Select
                            style={{ width: '100%' }}
                            value={s.type}
                            onChange={(v) => updateSection(index, { type: v, analysis: undefined, data: undefined, kpi: undefined })}
                            options={SECTION_TYPES.map((o) => ({ ...o })) as any}
                          />
                        </Col>
                      </Row>

                      {s.type === 'chart' && (
                        <Select
                          style={{ width: '100%' }}
                          placeholder="选择分析维度"
                          value={s.analysis}
                          onChange={(v) => updateSection(index, { analysis: v })}
                          options={CHART_ANALYSIS.map((o) => ({ ...o })) as any}
                        />
                      )}

                      {s.type === 'table' && (
                        <Select
                          style={{ width: '100%' }}
                          placeholder="选择数据表"
                          value={s.data}
                          onChange={(v) => updateSection(index, { data: v })}
                          options={TABLE_DATA.map((o) => ({ ...o })) as any}
                        />
                      )}

                      {s.type === 'kpi' && (
                        <Select
                          mode="multiple"
                          style={{ width: '100%' }}
                          placeholder="选择关键指标"
                          value={s.kpi || []}
                          onChange={(v) => updateSection(index, { kpi: v as string[] })}
                          options={KPI_KEYS.map((o) => ({ ...o })) as any}
                        />
                      )}

                      {(s.type === 'text' || s.type === 'chart') && (
                        <Input.TextArea
                          rows={s.type === 'text' ? 3 : 2}
                          placeholder={s.type === 'text' ? '章节内容指引（LLM 按此生成）' : '图表解读说明（选填）'}
                          value={s.content_template}
                          onChange={(e) => updateSection(index, { content_template: e.target.value })}
                        />
                      )}
                    </Space>
                  </Card>
                ))}

                <Button block icon={<PlusOutlined />} onClick={addSection} style={{ marginTop: 4 }}>
                  添加章节
                </Button>
              </>
            )}
          </Card>
        </Col>
      </Row>

      <div style={{ marginTop: 16, textAlign: 'right' }}>
        {editing && (
          <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>
            保存模板
          </Button>
        )}
      </div>
    </Modal>
  );
};

export default TemplateManager;