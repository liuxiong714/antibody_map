import React, { useEffect, useState, useCallback } from 'react';
import { Card, Button, Input, Select, Spin, Empty, message, Tag, Divider, Table, Modal, Space, Tooltip, Tabs, Popconfirm } from 'antd';
import { FileTextOutlined, EyeOutlined, DownloadOutlined, HistoryOutlined, ExperimentOutlined, EditOutlined, SaveOutlined, CloseOutlined, DeleteOutlined, ExclamationCircleOutlined } from '@ant-design/icons';
import AntibodyReportForm from '../components/AntibodyReportForm';
import StrategyReportForm from '../components/StrategyReportForm';
import ReportContentView from '../components/ReportContentView';
import { generateReport, generateVaccinationStrategy, listReports, getDownloadUrl, updateReport, deleteReport, getReport } from '../services/map';
import { ReportData, ReportRecord } from '../types';
import dayjs from 'dayjs';

const Report: React.FC = () => {
  // ---- 抗体分析报告 state ----
  const [disease, setDisease] = useState('');
  const [dataType, setDataType] = useState('');
  const [province, setProvince] = useState('');
  const [language, setLanguage] = useState('zh');
  const [model, setModel] = useState('');
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
      setReports(resp.items || []);
    } catch (err) { console.error('[Report] 加载报告列表失败:', err); message.error('加载报告列表失败'); }
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
      if (model) params.model = model;
      const resp = await generateReport(params);
      setReport(resp);
      message.success('报告生成成功');
      fetchHistory();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || '未知错误';
      console.error('[Report] 抗体报告生成失败:', err);
      message.error(`报告生成失败: ${detail}`);
    }
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
      setReport(resp);
      message.success('疫苗接种策略报告生成成功');
      fetchHistory();
    } catch (err) { console.error('[Report] 策略报告生成失败:', err); message.error('报告生成失败'); }
    finally { setStrategyLoading(false); }
  };

  const handlePreview = async (record: ReportRecord) => {
    if (record.content) {
      setPreviewReport(record);
    } else {
      try {
        const resp = await getReport(record.id);
        const full = { ...record, content: resp.content };
        setPreviewReport(full);
      } catch (err) { console.error('[Report] 加载报告内容失败:', err); message.error('加载报告内容失败'); }
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
    } catch (err) { console.error('[Report] 保存报告失败:', err); message.error('保存失败'); }
    finally { setSaving(false); }
  };

  const handleDelete = async (record: ReportRecord) => {
    setDeleting(true);
    try {
      await deleteReport(record.id);
      message.success('报告已删除');
      if (report?.id === record.id) setReport(null);
      fetchHistory();
    } catch (err) { console.error('[Report] 删除报告失败:', err); message.error('删除失败'); }
    finally { setDeleting(false); }
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
    { title: '模型', dataIndex: 'llm_model', key: 'llm', width: 140, ellipsis: true, render: (v: string) => v ? <Tag>{v}</Tag> : '-' },
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
              <AntibodyReportForm
                disease={disease} dataType={dataType} province={province}
                language={language} title={title} model={model} loading={loading}
                onDiseaseChange={setDisease} onDataTypeChange={setDataType}
                onProvinceChange={setProvince} onLanguageChange={setLanguage}
                onTitleChange={setTitle} onModelChange={setModel}
                onGenerate={handleGenerateAntibody}
              />
            ),
          },
          {
            key: 'strategy',
            label: <span><FileTextOutlined /> 疫苗接种策略报告</span>,
            children: (
              <StrategyReportForm
                taskType={taskType} taskTime={taskTime} taskLocation={taskLocation}
                personnelCount={personnelCount} personnelGender={personnelGender}
                personnelAge={personnelAge} personnelVaccinationHistory={personnelVaccinationHistory}
                strategyTitle={strategyTitle} loading={strategyLoading}
                onTaskTypeChange={setTaskType} onTaskTimeChange={setTaskTime}
                onTaskLocationChange={setTaskLocation} onPersonnelCountChange={setPersonnelCount}
                onPersonnelGenderChange={setPersonnelGender} onPersonnelAgeChange={setPersonnelAge}
                onPersonnelVaccinationHistoryChange={setPersonnelVaccinationHistory}
                onStrategyTitleChange={setStrategyTitle} onGenerate={handleGenerateStrategy}
              />
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
              <Tag>模型: {report.llm_model || '默认'}</Tag>
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
