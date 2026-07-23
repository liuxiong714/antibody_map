import React, { useEffect, useState, useCallback } from 'react';
import { Card, Row, Col, Button, Input, Select, Spin, Empty, message, Tag, Divider, Table, Modal, Space, Tooltip } from 'antd';
import { FileTextOutlined, EyeOutlined, DownloadOutlined, HistoryOutlined } from '@ant-design/icons';
import DiseaseSelector from '../components/DiseaseSelector';
import ProvinceSelector from '../components/ProvinceSelector';
import MapSelector from '../components/MapSelector';
import { generateReport, listReports, getDownloadUrl } from '../services/map';
import { ReportData, ReportRecord } from '../types';
import dayjs from 'dayjs';

const Report: React.FC = () => {
  const [disease, setDisease] = useState('');
  const [dataType, setDataType] = useState('');
  const [province, setProvince] = useState('');
  const [language, setLanguage] = useState('zh');
  const [title, setTitle] = useState('');
  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState<ReportData | null>(null);

  // History
  const [reports, setReports] = useState<ReportRecord[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [previewVisible, setPreviewVisible] = useState(false);
  const [previewReport, setPreviewReport] = useState<ReportRecord | null>(null);

  const fetchHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const resp = await listReports({ page: 1, page_size: 50 });
      setReports(resp.data?.items || []);
    } catch { message.error('加载报告列表失败'); }
    finally { setHistoryLoading(false); }
  }, []);

  useEffect(() => { fetchHistory(); }, [fetchHistory]);

  const handleGenerate = async () => {
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

  const columns = [
    { title: '标题', dataIndex: 'title', key: 'title', ellipsis: true },
    { title: '疾病', dataIndex: 'disease', key: 'disease', width: 80, render: (v: string) => v || '-' },
    { title: '语言', dataIndex: 'language', key: 'language', width: 60, render: (v: string) => v === 'zh' ? '中文' : 'EN' },
    { title: '文献数', dataIndex: 'literature_count', key: 'lc', width: 70 },
    { title: '数据点', dataIndex: 'data_point_count', key: 'dc', width: 70 },
    { title: '生成时间', dataIndex: 'generated_at', key: 'ga', width: 160, render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm') },
    { title: '操作', key: 'action', width: 140,
      render: (_: unknown, record: ReportRecord) => (
        <Space>
          <Tooltip title="预览"><Button size="small" icon={<EyeOutlined />} onClick={() => handlePreview(record)} /></Tooltip>
          <Tooltip title="下载"><Button size="small" icon={<DownloadOutlined />} onClick={() => handleDownload(record)} /></Tooltip>
        </Space>
      ),
    },
  ];

  return (
    <>
      <Card title="报告配置" style={{ marginBottom: 16 }}>
        <Row gutter={[16, 12]}>
          <Col><DiseaseSelector value={disease} onChange={setDisease} /></Col>
          <Col><MapSelector value={dataType} onChange={setDataType} /></Col>
          <Col><ProvinceSelector value={province} onChange={setProvince} /></Col>
          <Col>
            <Select value={language} onChange={setLanguage} style={{ width: 120 }}
              options={[{ value: 'zh', label: '中文' },{ value: 'en', label: 'English' }]} />
          </Col>
          <Col><Input placeholder="自定义报告标题（选填）" value={title} onChange={(e) => setTitle(e.target.value)} style={{ width: 260 }} /></Col>
          <Col><Button type="primary" icon={<FileTextOutlined />} onClick={handleGenerate} loading={loading}>生成报告</Button></Col>
        </Row>
      </Card>

      <Spin spinning={loading} tip="AI 正在生成报告...">
        {!report ? (
          <Empty description="配置筛选条件后点击生成报告" />
        ) : (
          <Card style={{ marginBottom: 16 }}>
            <h2 style={{ marginBottom: 8 }}>{report.title}</h2>
            <div style={{ marginBottom: 16, color: '#888' }}>
              <Tag>文献数: {report.literature_count}</Tag>
              <Tag>数据点数: {report.data_point_count}</Tag>
              <Tag>语言: {report.language === 'zh' ? '中文' : 'English'}</Tag>
              <Tag>生成时间: {dayjs(report.generated_at).format('YYYY-MM-DD HH:mm')}</Tag>
            </div>
            <Divider />
            <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.8, fontSize: 15, background: '#fafafa', padding: 24, borderRadius: 8 }}
              dangerouslySetInnerHTML={{ __html: report.content.replace(/\n/g, '<br/>') }} />
          </Card>
        )}
      </Spin>

      <Card title={<><HistoryOutlined /> 报告历史</>}>
        <Table
          dataSource={reports}
          rowKey="id"
          columns={columns}
          loading={historyLoading}
          pagination={{ pageSize: 20 }}
          size="small"
          locale={{ emptyText: '暂无历史报告' }}
        />
      </Card>

      <Modal
        title={previewReport?.title || '报告预览'}
        open={previewVisible}
        onCancel={() => setPreviewVisible(false)}
        footer={[
          <Button key="download" icon={<DownloadOutlined />}
            onClick={() => { if (previewReport) handleDownload(previewReport); }}>
            下载
          </Button>,
          <Button key="close" onClick={() => setPreviewVisible(false)}>关闭</Button>,
        ]}
        width={900}
      >
        <div style={{ maxHeight: '60vh', overflow: 'auto', whiteSpace: 'pre-wrap', lineHeight: 1.8 }}
          dangerouslySetInnerHTML={{ __html: (previewReport?.content || '').replace(/\n/g, '<br/>') }} />
      </Modal>
    </>
  );
};

export default Report;
