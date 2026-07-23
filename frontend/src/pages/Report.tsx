import React, { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import { Card, Row, Col, Button, Input, Select, Spin, Empty, message, Tag, Divider, Table, Modal, Space, Tooltip, Tabs, InputNumber, Popconfirm } from 'antd';
import { FileTextOutlined, EyeOutlined, DownloadOutlined, HistoryOutlined, ExperimentOutlined, EditOutlined, SaveOutlined, CloseOutlined, DeleteOutlined, ExclamationCircleOutlined, MenuOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import DiseaseSelector from '../components/DiseaseSelector';
import ProvinceSelector from '../components/ProvinceSelector';
import MapSelector from '../components/MapSelector';
import { generateReport, generateVaccinationStrategy, listReports, getDownloadUrl, updateReport, deleteReport } from '../services/map';
import { ReportData, ReportRecord } from '../types';
import dayjs from 'dayjs';

// ── 类型 ──
interface TocItem {
  id: string;
  text: string;
  level: number;
}

// ── 从 Markdown 解析目录 ──
function parseToc(markdown: string): TocItem[] {
  const headingRegex = /^(#{2,3})\s+(.+)$/gm;
  const items: TocItem[] = [];
  let match: RegExpExecArray | null;
  while ((match = headingRegex.exec(markdown)) !== null) {
    const level = match[1].length;
    const text = match[2].trim();
    const id = text.replace(/\s+/g, '-').replace(/[^\w\u4e00-\u9fff-]/g, '');
    items.push({ id, text, level });
  }
  return items;
}

// ── Markdown 预览样式 ──
const markdownStyle: React.CSSProperties = {
  fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", "Microsoft YaHei", sans-serif',
  fontSize: 15,
  lineHeight: 1.8,
  color: '#333',
  padding: '24px 32px',
};

// ── TOC 侧栏宽度 ──
const TOC_WIDTH = 220;

// ── 报告内容区组件（TOC + 内容） ──
const ReportContentView: React.FC<{
  content: string;
  editable?: boolean;
  reportId?: string;
  onSaved?: (newContent: string) => void;
}> = ({ content, editable = false, reportId, onSaved }) => {
  const toc = useMemo(() => parseToc(content), [content]);
  const [editing2, setEditing2] = useState(false);
  const [editContent, setEditContent] = useState(content);
  const [saving2, setSaving2] = useState(false);

  // 当外部 content 变化时同步 editContent（如：关闭 Modal 后重新打开另一报告）
  useEffect(() => {
    setEditContent(content);
    setEditing2(false);
  }, [content]);

  const handleScrollTo = (id: string) => {
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const handleSave = async () => {
    if (!reportId) return;
    setSaving2(true);
    try {
      await updateReport(reportId, { content: editContent });
      setEditing2(false);
      message.success('报告已保存');
      onSaved?.(editContent);
    } catch {
      message.error('保存失败');
    } finally {
      setSaving2(false);
    }
  };

  return (
    <div style={{ display: 'flex', gap: 0, minHeight: 400 }}>
      {/* TOC 侧栏 */}
      <div style={{
        width: TOC_WIDTH,
        minWidth: TOC_WIDTH,
        borderRight: '1px solid #f0f0f0',
        padding: '12px 0',
        display: 'flex',
        flexDirection: 'column',
      }}>
        <div style={{ padding: '0 12px 8px', fontWeight: 600, fontSize: 14, color: '#666', display: 'flex', alignItems: 'center', gap: 6 }}>
          <MenuOutlined /> 目录
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px' }}>
          {toc.length === 0 ? (
            <div style={{ padding: '8px 4px', color: '#999', fontSize: 13 }}>无标题</div>
          ) : (
            toc.map((item) => (
              <div
                key={item.id}
                onClick={() => handleScrollTo(item.id)}
                style={{
                  padding: '4px 8px',
                  paddingLeft: (item.level - 1) * 16 + 4,
                  fontSize: 13,
                  color: '#1890ff',
                  cursor: 'pointer',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  borderRadius: 4,
                  transition: 'background 0.2s',
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = '#f0f5ff')}
                onMouseLeave={(e) => (e.currentTarget.style.background = '')}
              >
                {item.text}
              </div>
            ))
          )}
        </div>
        {/* Modal 编辑/保存按钮 */}
        {editable && (
          <div style={{ padding: '12px', borderTop: '1px solid #f0f0f0' }}>
            {editing2 ? (
              <Space direction="vertical" style={{ width: '100%' }}>
                <Button icon={<SaveOutlined />} type="primary" block onClick={handleSave} loading={saving2}>保存</Button>
                <Button icon={<CloseOutlined />} block onClick={() => { setEditing2(false); setEditContent(content); }}>取消</Button>
              </Space>
            ) : (
              <Button icon={<EditOutlined />} block onClick={() => { setEditContent(content); setEditing2(true); }}>
                编辑
              </Button>
            )}
          </div>
        )}
      </div>

      {/* 内容区 */}
      <div style={{ flex: 1, overflow: 'auto' }}>
        {editing2 ? (
          <Input.TextArea
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
            style={{
              fontFamily: 'Consolas, Monaco, "Courier New", monospace',
              fontSize: 14,
              lineHeight: 1.6,
              border: 'none',
              resize: 'none',
              minHeight: 400,
            }}
            autoSize={{ minRows: 20 }}
          />
        ) : (
          <div className="markdown-preview" style={markdownStyle}>
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                h2: ({ children, ...props }) => {
                  const text = String(children);
                  const id = text.replace(/\s+/g, '-').replace(/[^\w\u4e00-\u9fff-]/g, '');
                  return <h2 id={id} {...props}>{children}</h2>;
                },
                h3: ({ children, ...props }) => {
                  const text = String(children);
                  const id = text.replace(/\s+/g, '-').replace(/[^\w\u4e00-\u9fff-]/g, '');
                  return <h3 id={id} {...props}>{children}</h3>;
                },
              }}
            >
              {content}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
};

const Report: React.FC = () => {
  // ---- 抗体分析报告 state ----
  const [disease, setDisease] = useState('');
  const [dataType, setDataType] = useState('');
  const [province, setProvince] = useState('');
  const [language, setLanguage] = useState('zh');
  const [title, setTitle] = useState('');
  const [loading, setLoading] = useState(false);

  // ---- 疫苗接种策略报告 state ----
  const [taskType, setTaskType] = useState('');
  const [taskTime, setTaskTime] = useState('');
  const [taskLocation, setTaskLocation] = useState('');
  const [personnelCount, setPersonnelCount] = useState<number | null>(null);
  const [personnelGender, setPersonnelGender] = useState('');
  const [personnelAge, setPersonnelAge] = useState('');
  const [personnelVaccinationHistory, setPersonnelVaccinationHistory] = useState('');
  const [strategyTitle, setStrategyTitle] = useState('');
  const [strategyLoading, setStrategyLoading] = useState(false);

  // ---- 通用 state ----
  const [report, setReport] = useState<ReportData | null>(null);
  const [activeTab, setActiveTab] = useState('antibody');

  // History
  const [reports, setReports] = useState<ReportRecord[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [previewVisible, setPreviewVisible] = useState(false);
  const [previewReport, setPreviewReport] = useState<ReportRecord | null>(null);

  // Edit state
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState('');
  const [editTitle, setEditTitle] = useState('');
  const [saving, setSaving] = useState(false);

  // Delete state
  const [deleting, setDeleting] = useState(false);

  const fetchHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const resp = await listReports({ page: 1, page_size: 50 });
      setReports(resp.data?.items || []);
    } catch { message.error('加载报告列表失败'); }
    finally { setHistoryLoading(false); }
  }, []);

  useEffect(() => { fetchHistory(); }, [fetchHistory]);

  const handleGenerateAntibody = async () => {
    setLoading(true);
    setReport(null);
    try {
      const params: Record<string, unknown> = { language };
      if (disease) params.disease = disease;
      if (dataType) params.data_type = dataType;
      if (province) params.province = province;
      if (title) params.title = title;
      const resp = await generateReport(params);
      setReport(resp.data);
      message.success('报告生成成功');
      fetchHistory();
    } catch { message.error('报告生成失败'); }
    finally { setLoading(false); }
  };

  const handleGenerateStrategy = async () => {
    if (!taskType || !taskTime || !taskLocation || !personnelCount) {
      message.warning('请填写任务类型、任务时间、任务地点和人员人数');
      return;
    }
    setStrategyLoading(true);
    setReport(null);
    try {
      const body: Record<string, unknown> = {
        task_type: taskType,
        task_time: taskTime,
        task_location: taskLocation,
        personnel_count: personnelCount,
        personnel_gender: personnelGender,
        personnel_age: personnelAge,
        personnel_vaccination_history: personnelVaccinationHistory,
      };
      if (strategyTitle) body.title = strategyTitle;
      const resp = await generateVaccinationStrategy(body);
      setReport(resp.data);
      message.success('疫苗接种策略报告生成成功');
      fetchHistory();
    } catch { message.error('报告生成失败'); }
    finally { setStrategyLoading(false); }
  };

  const handlePreview = async (record: ReportRecord) => {
    if (record.content) {
      setPreviewReport(record);
    } else {
      const { getReport } = await import('../services/map');
      try {
        const resp = await getReport(record.id);
        const full = { ...record, content: resp.data?.content };
        setPreviewReport(full);
      } catch { message.error('加载报告内容失败'); }
    }
    setPreviewVisible(true);
  };

  const handleDownload = (record: ReportRecord) => {
    window.open(getDownloadUrl(record.id), '_blank');
  };

  const handleStartEdit = () => {
    if (!report) return;
    setEditTitle(report.title);
    setEditContent(report.content);
    setEditing(true);
  };

  const handleCancelEdit = () => {
    setEditing(false);
    setEditContent('');
    setEditTitle('');
  };

  const handleSaveEdit = async () => {
    if (!report?.id) return;
    setSaving(true);
    try {
      await updateReport(report.id, { title: editTitle, content: editContent });
      setReport({ ...report, title: editTitle, content: editContent });
      setEditing(false);
      message.success('报告已保存');
      fetchHistory();
    } catch {
      message.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (record: ReportRecord) => {
    setDeleting(true);
    try {
      await deleteReport(record.id);
      message.success('报告已删除');
      if (report?.id === record.id) setReport(null);
      fetchHistory();
    } catch {
      message.error('删除失败');
    } finally {
      setDeleting(false);
    }
  };

  const historyColumns = [
    { title: '类型', dataIndex: 'report_type', key: 'rt', width: 100,
      render: (v: string) => v === 'vaccination_strategy'
        ? <Tag color="green">接种策略</Tag>
        : <Tag color="blue">抗体分析</Tag>,
    },
    { title: '标题', dataIndex: 'title', key: 'title', ellipsis: true,
      render: (v: string, record: ReportRecord) => (
        <a onClick={() => handlePreview(record)} style={{ cursor: 'pointer' }}>{v}</a>
      ),
    },
    { title: '疾病', dataIndex: 'disease', key: 'disease', width: 80, render: (v: string) => v || '-' },
    { title: '任务地点', dataIndex: 'task_location', key: 'tl', width: 100, ellipsis: true, render: (v: string) => v || '-' },
    { title: '人数', dataIndex: 'personnel_count', key: 'pc', width: 60, render: (v: number) => v || '-' },
    { title: '语言', dataIndex: 'language', key: 'language', width: 60, render: (v: string) => v === 'zh' ? '中文' : 'EN' },
    { title: '文献数', dataIndex: 'literature_count', key: 'lc', width: 70 },
    { title: '数据点', dataIndex: 'data_point_count', key: 'dc', width: 70 },
    { title: '生成时间', dataIndex: 'generated_at', key: 'ga', width: 160, render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm') },
    { title: '操作', key: 'action', width: 180,
      render: (_: unknown, record: ReportRecord) => (
        <Space>
          <Tooltip title="预览"><Button size="small" icon={<EyeOutlined />} onClick={() => handlePreview(record)} /></Tooltip>
          <Popconfirm
            title="确认下载" description="确定要下载该报告吗？"
            onConfirm={() => handleDownload(record)}
            okText="确认下载" cancelText="取消"
          >
            <Tooltip title="下载"><Button size="small" icon={<DownloadOutlined />} /></Tooltip>
          </Popconfirm>
          <Popconfirm
            title="确认删除" description="删除后不可恢复，确定要删除该报告吗？"
            onConfirm={() => handleDelete(record)}
            okText="确认删除" cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Tooltip title="删除"><Button size="small" danger icon={<DeleteOutlined />} loading={deleting} /></Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const isGenerating = loading || strategyLoading;

  return (
    <>
      <Tabs
        activeKey={activeTab}
        onChange={(k) => { setActiveTab(k); setReport(null); }}
        items={[
          {
            key: 'antibody',
            label: <span><ExperimentOutlined /> 抗体分析报告</span>,
            children: (
              <Card style={{ marginBottom: 16 }}>
                <Row gutter={[16, 12]} align="middle">
                  <Col><DiseaseSelector value={disease} onChange={setDisease} /></Col>
                  <Col><MapSelector value={dataType} onChange={setDataType} /></Col>
                  <Col><ProvinceSelector value={province} onChange={setProvince} /></Col>
                  <Col>
                    <Select value={language} onChange={setLanguage} style={{ width: 120 }}
                      options={[{ value: 'zh', label: '中文' }, { value: 'en', label: 'English' }]} />
                  </Col>
                  <Col><Input placeholder="自定义报告标题（选填）" value={title} onChange={(e) => setTitle(e.target.value)} style={{ width: 260 }} /></Col>
                  <Col><Button type="primary" icon={<FileTextOutlined />} onClick={handleGenerateAntibody} loading={loading}>生成报告</Button></Col>
                </Row>
              </Card>
            ),
          },
          {
            key: 'strategy',
            label: <span><FileTextOutlined /> 疫苗接种策略报告</span>,
            children: (
              <Card title="任务信息配置" style={{ marginBottom: 16 }}>
                <Row gutter={[16, 12]}>
                  <Col span={8}>
                    <div style={{ marginBottom: 4, fontWeight: 500 }}>任务类型 <span style={{ color: 'red' }}>*</span></div>
                    <Select value={taskType || undefined} onChange={setTaskType} placeholder="选择任务类型" style={{ width: '100%' }}
                      options={[
                        { value: '维和行动', label: '维和行动' }, { value: '抗震救灾', label: '抗震救灾' },
                        { value: '抗洪抢险', label: '抗洪抢险' }, { value: '国际救援', label: '国际救援' },
                        { value: '野外驻训', label: '野外驻训' }, { value: '军事演习', label: '军事演习' },
                        { value: '海外护航', label: '海外护航' }, { value: '联合国任务', label: '联合国任务' },
                        { value: '疫情防控', label: '疫情防控' }, { value: '其他', label: '其他' },
                      ]} />
                  </Col>
                  <Col span={8}>
                    <div style={{ marginBottom: 4, fontWeight: 500 }}>任务时间 <span style={{ color: 'red' }}>*</span></div>
                    <Input placeholder="如：2026年8-10月" value={taskTime} onChange={(e) => setTaskTime(e.target.value)} />
                  </Col>
                  <Col span={8}>
                    <div style={{ marginBottom: 4, fontWeight: 500 }}>任务地点 <span style={{ color: 'red' }}>*</span></div>
                    <ProvinceSelector value={taskLocation} onChange={setTaskLocation} />
                  </Col>
                </Row>
                <Divider />
                <Row gutter={[16, 12]}>
                  <Col span={6}>
                    <div style={{ marginBottom: 4, fontWeight: 500 }}>人员人数 <span style={{ color: 'red' }}>*</span></div>
                    <InputNumber min={1} max={100000} value={personnelCount} onChange={(v) => setPersonnelCount(v)} placeholder="人数" style={{ width: '100%' }} />
                  </Col>
                  <Col span={6}>
                    <div style={{ marginBottom: 4, fontWeight: 500 }}>人员性别分布</div>
                    <Input placeholder="如：男性80人，女性20人" value={personnelGender} onChange={(e) => setPersonnelGender(e.target.value)} />
                  </Col>
                  <Col span={6}>
                    <div style={{ marginBottom: 4, fontWeight: 500 }}>人员年龄范围</div>
                    <Input placeholder="如：18-35岁" value={personnelAge} onChange={(e) => setPersonnelAge(e.target.value)} />
                  </Col>
                  <Col span={6}>
                    <div style={{ marginBottom: 4, fontWeight: 500 }}>自定义标题（选填）</div>
                    <Input placeholder="报告标题" value={strategyTitle} onChange={(e) => setStrategyTitle(e.target.value)} />
                  </Col>
                </Row>
                <Row style={{ marginTop: 12 }}>
                  <Col span={24}>
                    <div style={{ marginBottom: 4, fontWeight: 500 }}>人员疫苗接种史</div>
                    <Input.TextArea rows={3} placeholder="如：已完成基础免疫，近2年未接种流感疫苗，乙肝表面抗体阳性..." value={personnelVaccinationHistory} onChange={(e) => setPersonnelVaccinationHistory(e.target.value)} />
                  </Col>
                </Row>
                <Row style={{ marginTop: 16 }}>
                  <Col>
                    <Button type="primary" icon={<FileTextOutlined />} onClick={handleGenerateStrategy} loading={strategyLoading}>生成疫苗接种策略报告</Button>
                  </Col>
                </Row>
              </Card>
            ),
          },
        ]}
      />

      <Spin spinning={isGenerating} tip="AI 正在生成报告...">
        {!report ? (
          <Empty description="配置条件后点击生成报告" style={{ marginBottom: 16 }} />
        ) : (
          <Card style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8, gap: 16 }}>
              {editing ? (
                <Input value={editTitle} onChange={(e) => setEditTitle(e.target.value)}
                  style={{ fontSize: 18, fontWeight: 600, flex: 1, minWidth: 0 }} placeholder="报告标题" />
              ) : (
                <h2 style={{ marginBottom: 0, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{report.title}</h2>
              )}
              <div style={{ flexShrink: 0 }}>
                <Space>
                  {editing ? (
                    <>
                      <Button icon={<SaveOutlined />} type="primary" onClick={handleSaveEdit} loading={saving}>保存</Button>
                      <Button icon={<CloseOutlined />} onClick={handleCancelEdit}>取消</Button>
                    </>
                  ) : (
                    <>
                      <Button icon={<EditOutlined />} onClick={handleStartEdit}>编辑</Button>
                      <Popconfirm
                        title="确认下载" description="确定要下载该报告吗？"
                        onConfirm={() => { if (report?.id) handleDownload({ id: report.id, title: report.title } as ReportRecord); }}
                        okText="确认下载" cancelText="取消"
                      >
                        <Button icon={<DownloadOutlined />}>下载</Button>
                      </Popconfirm>
                      <Popconfirm
                        title="确认删除" description="删除后不可恢复，确定要删除该报告吗？"
                        onConfirm={() => { if (report?.id) handleDelete({ id: report.id, title: report.title } as ReportRecord); }}
                        okText="确认删除" cancelText="取消"
                        okButtonProps={{ danger: true }}
                        icon={<ExclamationCircleOutlined style={{ color: 'red' }} />}
                      >
                        <Button icon={<DeleteOutlined />} danger>删除</Button>
                      </Popconfirm>
                    </>
                  )}
                </Space>
              </div>
            </div>
            <div style={{ marginBottom: 16, color: '#888' }}>
              <Tag color={report.report_type === 'vaccination_strategy' ? 'green' : 'blue'}>
                {report.report_type === 'vaccination_strategy' ? '疫苗接种策略' : '抗体分析'}
              </Tag>
              {report.literature_count > 0 && <Tag>文献数: {report.literature_count}</Tag>}
              {report.data_point_count > 0 && <Tag>数据点数: {report.data_point_count}</Tag>}
              {report.task_type && <Tag>任务类型: {report.task_type}</Tag>}
              {report.task_location && <Tag>任务地点: {report.task_location}</Tag>}
              {report.personnel_count && <Tag>人员: {report.personnel_count}人</Tag>}
              {report.language && <Tag>语言: {report.language === 'zh' ? '中文' : 'English'}</Tag>}
              <Tag>生成时间: {dayjs(report.generated_at).format('YYYY-MM-DD HH:mm')}</Tag>
            </div>
            <Divider />
            {editing ? (
              <Input.TextArea value={editContent} onChange={(e) => setEditContent(e.target.value)} rows={25}
                style={{ fontFamily: 'Consolas, Monaco, "Courier New", monospace', fontSize: 14, lineHeight: 1.6 }} />
            ) : (
              <ReportContentView content={report.content} />
            )}
          </Card>
        )}
      </Spin>

      <Card title={<><HistoryOutlined /> 报告历史</>}>
        <Table dataSource={reports} rowKey="id" columns={historyColumns} loading={historyLoading}
          pagination={{ pageSize: 20 }} size="small" scroll={{ x: 1300 }} locale={{ emptyText: '暂无历史报告' }} />
      </Card>

      <Modal
        title={previewReport?.title || '报告预览'}
        open={previewVisible}
        onCancel={() => setPreviewVisible(false)}
        footer={[
          <Popconfirm key="download" title="确认下载" description="确定要下载该报告吗？"
            onConfirm={() => { if (previewReport) handleDownload(previewReport); }}
            okText="确认下载" cancelText="取消"
          >
            <Button icon={<DownloadOutlined />}>下载</Button>
          </Popconfirm>,
          <Button key="close" onClick={() => setPreviewVisible(false)}>关闭</Button>,
        ]}
        width={1100}
        styles={{ body: { padding: 0 } }}
      >
        <ReportContentView
          content={previewReport?.content || ''}
          editable
          reportId={previewReport?.id}
          onSaved={(newContent) => {
            if (previewReport) setPreviewReport({ ...previewReport, content: newContent });
            fetchHistory();
          }}
        />
      </Modal>
    </>
  );
};

export default Report;
