import React, { useEffect, useState, useCallback, useRef } from 'react';
import { Card, Button, Input, Select, Spin, Empty, message, Tag, Divider, Table, Modal, Space, Tooltip, Tabs, Popconfirm, Dropdown } from 'antd';
import { FileTextOutlined, EyeOutlined, DownloadOutlined, HistoryOutlined, ExperimentOutlined, EditOutlined, SaveOutlined, CloseOutlined, DeleteOutlined, ExclamationCircleOutlined, SafetyCertificateOutlined } from '@ant-design/icons';
import AntibodyReportForm from '../components/AntibodyReportForm';
import StrategyReportForm from '../components/StrategyReportForm';
import ReportContentView from '../components/ReportContentView';
import TemplateManager from '../components/TemplateManager';
import { generateReport, generateVaccinationStrategy, generateImmuneBarrier, listReports, updateReport, deleteReport, getReport, listTemplates } from '../services/map';
import { getTaskStatus } from '../services/system';
import { ReportData, ReportRecord, ReportTemplate } from '../types';
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
  const [strategyModel, setStrategyModel] = useState('');
  const [strategyLoading, setStrategyLoading] = useState(false);

  // ---- 免疫屏障评估报告 state（参数与抗体分析一致）----
  const [barrierDisease, setBarrierDisease] = useState('');
  const [barrierDataType, setBarrierDataType] = useState('');
  const [barrierProvince, setBarrierProvince] = useState('');
  const [barrierLanguage, setBarrierLanguage] = useState('zh');
  const [barrierTitle, setBarrierTitle] = useState('');
  const [barrierModel, setBarrierModel] = useState('');
  const [barrierLoading, setBarrierLoading] = useState(false);

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

  // ---- 模板相关 state ----
  const [templates, setTemplates] = useState<ReportTemplate[]>([]);
  const [templateId, setTemplateId] = useState<string | undefined>(undefined);
  const [templateManagerVisible, setTemplateManagerVisible] = useState(false);
  const [isAdminFlag, setIsAdminFlag] = useState(false);

  useEffect(() => {
    setIsAdminFlag(
      localStorage.getItem('is_admin') === 'true' || sessionStorage.getItem('is_admin') === 'true'
    );
  }, []);

  const fetchTemplates = useCallback(async (type: 'antibody_analysis' | 'vaccination_strategy' | 'immune_barrier_assessment') => {
    try {
      const data = await listTemplates(type);
      setTemplates(data);
      // 若当前已选模板不匹配当前类型，重置
      if (templateId && !data.some((t) => t.id === templateId)) setTemplateId(undefined);
    } catch (err) {
      console.error('[Report] 加载模板失败:', err);
    }
  }, [templateId]);

  useEffect(() => {
    // 切换 Tab 时刷新对应类型模板
    fetchTemplates(getTabReportType(activeTab));
  }, [activeTab, fetchTemplates]);

  const templateOptions = templates.map((t) => ({
    value: t.id,
    label: (t.is_default ? '★ ' : '') + t.name,
  }));

  const getTabReportType = (tab: string): 'antibody_analysis' | 'vaccination_strategy' | 'immune_barrier_assessment' => {
    if (tab === 'strategy') return 'vaccination_strategy';
    if (tab === 'barrier') return 'immune_barrier_assessment';
    return 'antibody_analysis';
  };

  const handleFetchTemplates = () => {
    fetchTemplates(getTabReportType(activeTab));
  };

  const fetchHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const resp = await listReports({ page: 1, page_size: 50 });
      setReports(resp.items || []);
    } catch (err) { console.error('[Report] 加载报告列表失败:', err); message.error('加载报告列表失败'); }
    finally { setHistoryLoading(false); }
  }, []);

  useEffect(() => { fetchHistory(); }, [fetchHistory]);

  // ---- 报告后台异步"点外卖"模式：提交后原地轮询任务状态，完成后自动展示报告 ----
  const [genTip, setGenTip] = useState('AI 正在生成报告...');
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = () => {
    if (pollTimer.current) { clearInterval(pollTimer.current); pollTimer.current = null; }
  };

  /** 轮询单任务直到 done/failed，自动解析历史并展示生成报告（沿用原同步拉起 ReportContentView 的行为） */
  const pollReportTask = useCallback(async (taskId: string): Promise<void> => {
    return new Promise<void>((resolve) => {
      stopPolling();
      const tick = async () => {
        try {
          const st = await getTaskStatus(taskId);
          const status = String(st.status || 'running');
          const progress = String(st.progress || '');
          if (progress) setGenTip(`AI 正在生成报告…${progress}`);
          if (status === 'done') {
            stopPolling();
            const rid = (st.result as { report_id?: string } | undefined)?.report_id;
            if (rid) {
              try {
                const data = await getReport(rid);
                // 详情接口返回 ReportRecord（content 可空）；生成报告必有内容，转成内容视图所需的 ReportData
                setReport({
                  id: data.id,
                  title: data.title,
                  content: data.content || '',
                  report_type: data.report_type || 'antibody_analysis',
                  literature_count: 0,
                  data_point_count: 0,
                  language: data.language || 'zh',
                  llm_model: data.llm_model,
                  generated_at: data.generated_at || new Date().toISOString(),
                });
              } catch (e) { console.error('[Report] 加载生成报告失败:', e); }
            }
            message.success('报告生成成功');
            fetchHistory();
            resolve();
          } else if (status === 'failed') {
            stopPolling();
            message.error(`报告生成失败: ${String(st.error || '未知错误')}`);
            resolve();
          }
          // running/queued: 继续轮询
        } catch (e: any) {
          // 任务可能刚结束尚未写入 Redis，或后端暂时不可达：稍后重试
          const st = e?.response?.status;
          if (st === 404) { stopPolling(); message.error('报告任务不存在或已过期'); resolve(); }
        }
      };
      pollTimer.current = setInterval(() => void tick(), 3000);
      void tick();
    });
  }, [fetchHistory]);

  useEffect(() => () => stopPolling(), []);

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
      if (templateId) params.template_id = templateId;
      const resp = await generateReport(params);
      await pollReportTask(resp.task_id);
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
      if (templateId) body.template_id = templateId;
      if (strategyModel) body.model = strategyModel;
      const resp = await generateVaccinationStrategy(body);
      await pollReportTask(resp.task_id);
      message.success('疫苗接种策略报告生成成功');
      fetchHistory();
    } catch (err) { console.error('[Report] 策略报告生成失败:', err); message.error('报告生成失败'); }
    finally { setStrategyLoading(false); }
  };

  const handleGenerateBarrier = async () => {
    setBarrierLoading(true);
    setReport(null);
    try {
      const params: Record<string, unknown> = { language: barrierLanguage };
      if (barrierDisease) params.disease = barrierDisease;
      if (barrierDataType) params.data_type = barrierDataType;
      if (barrierProvince) params.province = barrierProvince;
      if (barrierTitle) params.title = barrierTitle;
      if (barrierModel) params.model = barrierModel;
      if (templateId) params.template_id = templateId;
      const resp = await generateImmuneBarrier(params);
      await pollReportTask(resp.task_id);
      message.success('免疫屏障评估报告生成成功');
      fetchHistory();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || '未知错误';
      console.error('[Report] 免疫屏障评估报告生成失败:', err);
      message.error(`报告生成失败: ${detail}`);
    }
    finally { setBarrierLoading(false); }
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

  /** 下载报告（format: md/docx/pdf）：下载端点位于受保护路由，需携带 JWT；故用 fetch 带
   *  Authorization 头拉取，再以 blob+<a download> 触发浏览器原生保存对话框（可选择保存位置、可拖动）。
   *  原 window.open(url) 因不带鉴权头返回 401，且新开页面易被当作弹窗拦截而"没反应"。 */
  const handleDownload = async (record: ReportRecord, format: 'md' | 'docx' | 'pdf' = 'md') => {
    const token = localStorage.getItem('token') || sessionStorage.getItem('token');
    try {
      const resp = await fetch(`/api/v1/reports/${record.id}/download?format=${format}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => null);
        throw new Error(body?.detail || `下载失败（${resp.status}）`);
      }
      const blob = await resp.blob();
      let filename = `${record.title || '报告'}.${format}`;
      const cd = resp.headers.get('Content-Disposition');
      if (cd) {
        const m = cd.match(/filename\*=UTF-8''([^;]+)/i) || cd.match(/filename="?([^";]+)"?/i);
        if (m?.[1]) {
          try { filename = decodeURIComponent(m[1]); } catch { filename = m[1]; }
        }
      }
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err: any) {
      console.error('[Report] 下载报告失败:', err);
      message.error(err?.message || '下载失败');
    }
  };

  /** 下载下拉：提供 Markdown/Word/PDF 三种格式选择 */
  const DownloadDropdown: React.FC<{ record: ReportRecord; compact?: boolean }> = ({ record, compact }) => (
    <Dropdown
      menu={{
        items: [
          { key: 'md', label: 'Markdown (.md)' },
          { key: 'docx', label: 'Word (.docx)' },
          { key: 'pdf', label: 'PDF (.pdf)' },
        ],
        onClick: ({ key }) => { void handleDownload(record, key as 'md' | 'docx' | 'pdf'); },
      }}
    >
      {compact
        ? <Button size="small" icon={<DownloadOutlined />}>下载</Button>
        : <Button icon={<DownloadOutlined />}>下载</Button>}
    </Dropdown>
  );

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
        : v === 'immune_barrier_assessment'
          ? <Tag color="purple">免疫屏障</Tag>
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
          <DownloadDropdown record={record} compact />
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

  const isGenerating = loading || strategyLoading || barrierLoading;

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
                templateId={templateId} templates={templateOptions} isAdmin={isAdminFlag}
                onDiseaseChange={setDisease} onDataTypeChange={setDataType}
                onProvinceChange={setProvince} onLanguageChange={setLanguage}
                onTitleChange={setTitle} onModelChange={setModel}
                onTemplateChange={(v) => setTemplateId(v || undefined)}
                onManageTemplates={() => setTemplateManagerVisible(true)}
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
                strategyTitle={strategyTitle} model={strategyModel} loading={strategyLoading}
                templateId={templateId} templates={templateOptions} isAdmin={isAdminFlag}
                onTaskTypeChange={setTaskType} onTaskTimeChange={setTaskTime}
                onTaskLocationChange={setTaskLocation} onPersonnelCountChange={setPersonnelCount}
                onPersonnelGenderChange={setPersonnelGender} onPersonnelAgeChange={setPersonnelAge}
                onPersonnelVaccinationHistoryChange={setPersonnelVaccinationHistory}
                onStrategyTitleChange={setStrategyTitle}
                onModelChange={setStrategyModel}
                onTemplateChange={(v) => setTemplateId(v || undefined)}
                onManageTemplates={() => setTemplateManagerVisible(true)}
                onGenerate={handleGenerateStrategy}
              />
            ),
          },
          {
            key: 'barrier',
            label: <span><SafetyCertificateOutlined /> 免疫屏障评估报告</span>,
            children: (
              <AntibodyReportForm
                disease={barrierDisease} dataType={barrierDataType} province={barrierProvince}
                language={barrierLanguage} title={barrierTitle} model={barrierModel} loading={barrierLoading}
                templateId={templateId} templates={templateOptions} isAdmin={isAdminFlag}
                onDiseaseChange={setBarrierDisease} onDataTypeChange={setBarrierDataType}
                onProvinceChange={setBarrierProvince} onLanguageChange={setBarrierLanguage}
                onTitleChange={setBarrierTitle} onModelChange={setBarrierModel}
                onTemplateChange={(v) => setTemplateId(v || undefined)}
                onManageTemplates={() => setTemplateManagerVisible(true)}
                onGenerate={handleGenerateBarrier}
              />
            ),
          },
        ]}
      />

      <Spin spinning={isGenerating} tip={genTip}>
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
                      <DownloadDropdown record={{ id: report.id, title: report.title } as ReportRecord} />
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
              <Tag color={report.report_type === 'vaccination_strategy' ? 'green' : report.report_type === 'immune_barrier_assessment' ? 'purple' : 'blue'}>
                {report.report_type === 'vaccination_strategy' ? '疫苗接种策略' : report.report_type === 'immune_barrier_assessment' ? '免疫屏障评估' : '抗体分析'}
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
          previewReport ? <DownloadDropdown key="download" record={previewReport} /> : null,
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

      <TemplateManager
        visible={templateManagerVisible}
        reportType={getTabReportType(activeTab)}
        onClose={() => setTemplateManagerVisible(false)}
        onSaved={handleFetchTemplates}
      />
    </>
  );
};

export default Report;
