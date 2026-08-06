import React, { useCallback, useEffect, useState } from 'react';
import {
  Card, Table, Button, Input, InputNumber, Space, Modal, Upload, Form, Select, message, Popconfirm, Tag, Tooltip, Progress, Collapse, Typography, Checkbox,
} from 'antd';
import { UploadOutlined, SearchOutlined, DeleteOutlined, ExperimentOutlined, PlusOutlined, RobotOutlined, ReloadOutlined, EyeOutlined, DownloadOutlined, CopyOutlined, ExportOutlined, LinkOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useNavigate } from 'react-router-dom';
import DiseaseSelector from '../components/DiseaseSelector';
import StatusBadge from '../components/StatusBadge';
import PdfPreviewModal from '../components/PdfPreviewModal';
import MergeDialog from '../components/MergeDialog';
import DuplicateScanPanel from '../components/DuplicateScanPanel';
import { listLiterature, deleteLiterature, uploadLiterature, triggerExtraction, checkDuplicate, createLiteratureFromUrl } from '../services/literature';
import { Literature, DuplicateMatchItem } from '../types';
import { MODEL_OPTIONS, VENDOR_INFO } from '../utils/constants';
import { formatAuthors, truncate } from '../utils/format';
import dayjs from 'dayjs';

const { Text } = Typography;

// ===== 默认模型持久化（localStorage）=====
const DEFAULT_MODEL_KEY = 'antibody-default-model';

interface SavedModelConfig {
  model: string;
  apiKey?: string;
  baseUrl?: string;
  customModel?: string;
}

function loadSavedDefaultModel(): SavedModelConfig | null {
  try {
    const raw = localStorage.getItem(DEFAULT_MODEL_KEY);
    return raw ? JSON.parse(raw) as SavedModelConfig : null;
  } catch { return null; }
}

function saveDefaultModel(config: SavedModelConfig) {
  try {
    localStorage.setItem(DEFAULT_MODEL_KEY, JSON.stringify(config));
  } catch { /* ignore */ }
}

function clearDefaultModel() {
  try {
    localStorage.removeItem(DEFAULT_MODEL_KEY);
  } catch { /* ignore */ }
}

// 保存/恢复列表状态的 sessionStorage key
const LIST_STATE_KEY = 'literature_list_back_state';

const LiteraturePage: React.FC = () => {
  // lazy initializer：从 sessionStorage 一次性读取并解析上次离开列表页时的状态
  const _cachedState = React.useMemo(() => {
    try {
      const raw = sessionStorage.getItem(LIST_STATE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as Record<string, unknown>;
        console.log('[文献列表] 读取备份状态:', parsed);
        return parsed;
      }
      console.log('[文献列表] sessionStorage 无备份状态（非详情页返回，按默认值加载）');
    } catch (e) {
      console.warn('[文献列表] 读取备份状态失败:', e);
    }
    return null;
  }, []);

  const [items, setItems] = useState<Literature[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(() => (_cachedState?.page as number) || 1);
  const [pageSize, setPageSize] = useState(() => (_cachedState?.pageSize as number) || 20);
  const [keyword, setKeyword] = useState(() => (_cachedState?.keyword as string) || '');
  const [disease, setDisease] = useState(() => (_cachedState?.disease as string) || '');
  const [province, setProvince] = useState(() => (_cachedState?.province as string) || '');
  const [yearStart, setYearStart] = useState<number | undefined>(() => _cachedState?.yearStart as number | undefined);
  const [yearEnd, setYearEnd] = useState<number | undefined>(() => _cachedState?.yearEnd as number | undefined);
  const [journal, setJournal] = useState(() => (_cachedState?.journal as string) || '');
  const [sortBy, setSortBy] = useState(() => (_cachedState?.sortBy as string) || 'created');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>(() => (_cachedState?.sortOrder as 'asc' | 'desc') || 'desc');
  const [reviewStatus, setReviewStatus] = useState<string>(() => (_cachedState?.reviewStatus as string) || '');
  const [sortInfo, setSortInfo] = useState<{ field: string | null; order: 'ascend' | 'descend' | null }>(() => (
    _cachedState?.sortInfo as { field: string | null; order: 'ascend' | 'descend' | null }
  ) || { field: 'created_at', order: 'descend' });
  const [loading, setLoading] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [batchProgress, setBatchProgress] = useState({ current: 0, total: 0, fileName: '' });
  const [form] = Form.useForm();
  const navigate = useNavigate();

  // 清除备份状态（成功挂载后不再需要）
  useEffect(() => {
    console.log('[文献列表] 列表页挂载完成，本次恢复: 页码=', page, '每页=', pageSize, '排序=', sortBy, sortOrder, '筛选=', { keyword, disease, province, yearStart, yearEnd, journal, reviewStatus });
    sessionStorage.removeItem(LIST_STATE_KEY);
  }, []);

  /** 跳转到文献详情前，保存当前列表状态，以便返回时恢复 */
  const saveStateAndNavigate = (litId: string) => {
    const payload = {
      sortBy, sortOrder, sortInfo, page, pageSize,
      keyword, disease, province, yearStart, yearEnd, journal, reviewStatus,
    };
    console.log('[文献列表] 进入详情页前保存状态:', payload);
    try {
      sessionStorage.setItem(LIST_STATE_KEY, JSON.stringify(payload));
    } catch (err) { console.error('[Literature] 保存列表状态失败:', err); /* ignore */ }
    navigate(`/literature/${litId}`);
  };

  // 模型选择提取
  const [extractModalOpen, setExtractModalOpen] = useState(false);
  const [extractModel, setExtractModel] = useState<string | undefined>(undefined);
  const [extractLitId, setExtractLitId] = useState<string | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [extractApiKey, setExtractApiKey] = useState('');
  const [extractBaseUrl, setExtractBaseUrl] = useState('');
  const [extractCustomModel, setExtractCustomModel] = useState('');
  // 是否将当前选择的模型保存为默认
  const [saveAsDefault, setSaveAsDefault] = useState(false);
  // 当前已保存的默认模型（用于显示提示）
  const [savedDefault, setSavedDefault] = useState<SavedModelConfig | null>(() => loadSavedDefaultModel());

  // PDF 预览
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewLitId, setPreviewLitId] = useState<string | null>(null);
  const [previewLitTitle, setPreviewLitTitle] = useState('');

  // 查重与合并
  const [dupWarningOpen, setDupWarningOpen] = useState(false);
  const [dupWarnings, setDupWarnings] = useState<{ litId: string; litTitle: string; duplicates: DuplicateMatchItem[] }[]>([]);
  const [scanOpen, setScanOpen] = useState(false);
  const [mergeState, setMergeState] = useState<{ open: boolean; sourceId: string; targetId: string; sourceTitle: string; targetTitle: string }>({
    open: false, sourceId: '', targetId: '', sourceTitle: '', targetTitle: '',
  });

  // URL 导入
  const [urlModalOpen, setUrlModalOpen] = useState(false);
  const [urlInput, setUrlInput] = useState('');
  const [urlTitle, setUrlTitle] = useState('');
  const [urlProvince, setUrlProvince] = useState('');
  const [urlImporting, setUrlImporting] = useState(false);

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, unknown> = { page, page_size: pageSize };
      if (keyword) params.keyword = keyword;
      if (disease) params.disease = disease;
      if (province) params.province = province;
      if (yearStart) params.year_start = yearStart;
      if (yearEnd) params.year_end = yearEnd;
      if (journal) params.journal = journal;
      if (sortBy) params.sort_by = sortBy;
      if (sortOrder) params.sort_order = sortOrder;
      if (reviewStatus) params.review_status = reviewStatus;
      const resp = await listLiterature(params);
      setItems(resp.items);
      setTotal(resp.total);
    } catch (err) {
      console.error('[Literature] 加载文献列表失败:', err);
      message.error('加载文献列表失败');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, keyword, disease, province, yearStart, yearEnd, journal, sortBy, sortOrder, reviewStatus]);

  useEffect(() => { fetchList(); }, [fetchList]);

  const handleDelete = async (id: string) => {
    try {
      await deleteLiterature(id);
      message.success('删除成功');
      fetchList();
    } catch (err) {
      console.error('[Literature] 删除文献失败:', err);
      message.error('删除失败');
    }
  };

  const handleUpload = async () => {
    const values = await form.validateFields();
    const files: File[] = (values.file || [])
      .map((f: any) => f.originFileObj)
      .filter((f: File | undefined): f is File => !!f);

    if (files.length === 0) { message.error('请选择文件'); return; }

    setUploading(true);
    setBatchProgress({ current: 0, total: files.length, fileName: '' });

    let successCount = 0;
    let failCount = 0;
    let model = values.model;
    const apiKey = values.apiKey || undefined;
    const baseUrl = values.baseUrl || undefined;
    // 处理自定义 Ollama 模型名称
    if (model === 'ollama:custom') {
      if (values.customModel && values.customModel.trim()) {
        model = values.customModel.trim();
      } else {
        model = ''; // 未填写自定义模型名，回退到默认配置
      }
    } else if (model && model.startsWith('ollama:')) {
      // ollama: 前缀的模型去掉前缀后传递给后端
      model = model.substring('ollama:'.length);
    }

    // 保存为默认模型
    if (saveAsDefault) {
      const configToSave: SavedModelConfig = {
        model: values.model || '',
        apiKey: apiKey,
        baseUrl: baseUrl,
        customModel: values.customModel || '',
      };
      saveDefaultModel(configToSave);
      setSavedDefault(configToSave);
      message.info(`已将「${MODEL_OPTIONS.find((o) => o.value === values.model)?.label || '自定义模型'}」设为默认模型`);
    }
    const autoExtract = values.autoExtract !== false; // 默认 true
    const dupResults: { litId: string; litTitle: string; duplicates: DuplicateMatchItem[] }[] = [];

    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      setBatchProgress({ current: i + 1, total: files.length, fileName: file.name });

      try {
        const fd = new FormData();
        fd.append('file', file);
        // 单文件时使用用户自定义标题，批量时使用文件名
        if (files.length === 1 && values.title) fd.append('title', values.title);
        if (files.length === 1 && values.doi) fd.append('doi', values.doi);
        if (files.length === 1 && values.province) fd.append('province', values.province);

        const resp = await uploadLiterature(fd);

        if (resp?.id) {
          if (autoExtract) {
            if (model && model !== '') {
              await triggerExtraction(resp.id, { model, apiKey, baseUrl });
            } else {
              await triggerExtraction(resp.id);
            }
          }
          // 上传后查重
          try {
            const dup = await checkDuplicate({ literature_id: resp.id });
            if (dup.total > 0) {
              dupResults.push({ litId: resp.id, litTitle: resp.title || file.name, duplicates: dup.duplicates });
            }
          } catch (err) { console.error('[Literature] 查重失败:', err); /* 查重失败不阻塞 */ }
        }
        successCount++;
      } catch (err) {
        console.error('[Literature] 上传文件失败:', err);
        failCount++;
      }
    }

    setUploading(false);

    // 如果发现重复，弹出警告
    if (dupResults.length > 0) {
      setDupWarnings(dupResults);
      setDupWarningOpen(true);
    }

    if (files.length === 1) {
      if (successCount === 1) {
        message.success(autoExtract ? '上传成功，已启动 AI 提取' : '上传成功（未启动 AI 提取，可后续手动提取）');
      } else {
        message.error('上传失败');
      }
    } else {
      const msg = `批量上传完成：成功 ${successCount} 个`;
      if (failCount > 0) {
        message.warning(`${msg}，失败 ${failCount} 个`);
      } else {
        message.success(autoExtract ? `${msg}，已全部启动 AI 提取` : `${msg}（未启动 AI 提取，可后续手动提取）`);
      }
    }

    setUploadOpen(false);
    setBatchProgress({ current: 0, total: 0, fileName: '' });
    form.resetFields();
    fetchList();
  };

  const handleExtract = (id: string) => {
    setExtractLitId(id);
    // 预填充已保存的默认模型
    const saved = loadSavedDefaultModel();
    if (saved && saved.model) {
      setExtractModel(saved.model);
      const vendor = MODEL_OPTIONS.find((o) => o.value === saved.model)?.vendor || '';
      setExtractBaseUrl(saved.baseUrl || VENDOR_INFO[vendor]?.defaultBaseUrl || '');
      setExtractApiKey(saved.apiKey || '');
      setExtractCustomModel(saved.customModel || '');
    } else {
      setExtractModel(undefined);
      setExtractApiKey('');
      setExtractBaseUrl('');
      setExtractCustomModel('');
    }
    setExtractModalOpen(true);
  };

  const confirmExtract = async () => {
    if (!extractLitId) return;
    setExtracting(true);
    try {
      let model = extractModel;
      // 处理自定义 Ollama 模型名称
      if (model === 'ollama:custom') {
        if (extractCustomModel && extractCustomModel.trim()) {
          model = extractCustomModel.trim();
        } else {
          model = ''; // 未填写自定义模型名，回退到默认配置
        }
      } else if (model && model.startsWith('ollama:')) {
        // ollama: 前缀的模型去掉前缀后传递给后端
        model = model.substring('ollama:'.length);
      }

      // 保存为默认模型
      if (saveAsDefault) {
        const configToSave: SavedModelConfig = {
          model: extractModel || '',
          apiKey: extractApiKey || undefined,
          baseUrl: extractBaseUrl || undefined,
          customModel: extractCustomModel || '',
        };
        saveDefaultModel(configToSave);
        setSavedDefault(configToSave);
        message.info(`已将「${MODEL_OPTIONS.find((o) => o.value === extractModel)?.label || '自定义模型'}」设为默认模型`);
      }

      if (model && model !== '') {
        await triggerExtraction(extractLitId, {
          model,
          apiKey: extractApiKey || undefined,
          baseUrl: extractBaseUrl || undefined,
        });
      } else {
        await triggerExtraction(extractLitId);
      }
      const modelLabel = MODEL_OPTIONS.find((o) => o.value === extractModel)?.label
        || (extractCustomModel ? `Ollama:${extractCustomModel}` : '默认模型');
      message.success(`已使用 ${modelLabel} 启动 AI 提取`);
      setExtractModalOpen(false);
      setExtractCustomModel('');
      setSaveAsDefault(false);
      fetchList();
    } catch (err) {
      console.error('[Literature] 提取失败:', err);
      message.error('提取失败，请检查后端服务是否正常');
    } finally {
      setExtracting(false);
    }
  };

  const handleTableChange = (pagination: any, _filters: unknown, sorter: any) => {
    // 处理分页变更
    if (pagination.current !== page || pagination.pageSize !== pageSize) {
      setPage(pagination.current);
      setPageSize(pagination.pageSize);
    }
    // 处理排序变更
    const s = Array.isArray(sorter) ? sorter[0] : sorter;
    if (s && s.field) {
      const fieldMap: Record<string, string> = {
        title: 'title',
        authors: 'authors',
        journal: 'journal',
        pub_year: 'year',
        province: 'province',
        created_at: 'created',
        extraction_status: 'status',
      };
      const backendField = fieldMap[s.field as string] || (s.field as string);
      const order = s.order as 'ascend' | 'descend' | null;
      const backendOrder = order === 'ascend' ? 'asc' : 'desc';
      setSortInfo({ field: order ? (s.field as string) : null, order });
      setSortBy(order ? backendField : 'created');
      setSortOrder(backendOrder);
    }
  };

  const columns: ColumnsType<Literature> = [
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      width: 280,
      sorter: true,
      sortOrder: sortInfo.field === 'title' ? sortInfo.order : null,
      render: (t: string, r: Literature) => (
        <a onClick={() => saveStateAndNavigate(r.id)}>{truncate(t, 40)}</a>
      ),
    },
    {
      title: '作者',
      dataIndex: 'authors',
      key: 'authors',
      width: 140,
      sorter: true,
      sortOrder: sortInfo.field === 'authors' ? sortInfo.order : null,
      render: (v: string) => formatAuthors(v),
    },
    {
      title: '期刊',
      dataIndex: 'journal',
      key: 'journal',
      width: 140,
      sorter: true,
      sortOrder: sortInfo.field === 'journal' ? sortInfo.order : null,
      render: (v: string) => v || '-',
    },
    {
      title: '年份',
      dataIndex: 'pub_year',
      key: 'year',
      width: 70,
      sorter: true,
      sortOrder: sortInfo.field === 'pub_year' ? sortInfo.order : null,
      render: (v: number | null) => v || '-',
    },
    {
      title: '省份',
      dataIndex: 'province',
      key: 'province',
      width: 80,
      sorter: true,
      sortOrder: sortInfo.field === 'province' ? sortInfo.order : null,
      render: (v: string) => v || '-',
    },
    {
      title: '提取状态',
      dataIndex: 'extraction_status',
      key: 'status',
      width: 90,
      sorter: true,
      sortOrder: sortInfo.field === 'extraction_status' ? sortInfo.order : null,
      render: (s: string) => <StatusBadge status={s} />,
    },
    {
      title: '审核状态',
      key: 'review_status',
      width: 140,
      render: (_: unknown, r: Literature) => {
        const total = r.extracted_count || 0;
        const approved = r.approved_count || 0;
        if (total === 0) {
          return <Tag color="default">无数据</Tag>;
        }
        const percent = Math.round((approved / total) * 100);
        if (approved === total) {
          return (
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <Tag color="green">已完成</Tag>
              <span style={{ fontSize: 12 }}>{approved}/{total}</span>
            </div>
          );
        }
        if (approved === 0) {
          return (
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <Tag color="red">未审核</Tag>
              <span style={{ fontSize: 12 }}>0/{total}</span>
            </div>
          );
        }
        return (
          <Tooltip title={`${approved} / ${total} 已审核`}>
            <Progress
              percent={percent}
              size="small"
              style={{ width: 100 }}
              strokeColor={percent >= 50 ? '#52c41a' : '#faad14'}
            />
          </Tooltip>
        );
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created',
      width: 110,
      sorter: true,
      sortOrder: sortInfo.field === 'created_at' ? sortInfo.order : null,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 270,
      render: (_: unknown, r: Literature) => (
        <Space size="small">
          <Tooltip title="AI 提取">
            <Button
              size="small"
              icon={<ExperimentOutlined />}
              onClick={() => handleExtract(r.id)}
              loading={r.extraction_status === 'processing'}
              disabled={r.extraction_status === 'processing'}
            />
          </Tooltip>
          <Tooltip title="预览">
            <Button
              size="small"
              icon={<EyeOutlined />}
              onClick={() => {
                // HTML 文件直接在浏览器新标签页打开（浏览器原生渲染）
                const ext = r.file_path ? r.file_path.split('.').pop()?.toLowerCase() : '';
                if (ext === 'html' || ext === 'htm') {
                  window.open(`/api/v1/literatures/${r.id}/file`, '_blank');
                } else {
                  setPreviewLitId(r.id);
                  setPreviewLitTitle(r.title);
                  setPreviewOpen(true);
                }
              }}
            />
          </Tooltip>
          <Tooltip title="下载并用本地阅读器打开">
            <Button
              size="small"
              icon={<DownloadOutlined />}
              onClick={() => window.open(`/api/v1/literatures/${r.id}/download`)}
            />
          </Tooltip>
          <Button size="small" onClick={() => saveStateAndNavigate(r.id)}>详情</Button>
          <Popconfirm title="确定删除？" onConfirm={() => handleDelete(r.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <>
      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Input
            placeholder="搜索标题/作者/期刊"
            prefix={<SearchOutlined />}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onPressEnter={fetchList}
            style={{ width: 200 }}
            allowClear
          />
          <DiseaseSelector value={disease} onChange={setDisease} />
          <Input
            placeholder="省份"
            value={province}
            onChange={(e) => setProvince(e.target.value)}
            onPressEnter={fetchList}
            style={{ width: 100 }}
            allowClear
          />
          <Input
            placeholder="期刊"
            value={journal}
            onChange={(e) => setJournal(e.target.value)}
            onPressEnter={fetchList}
            style={{ width: 150 }}
            allowClear
          />
          <InputNumber
            placeholder="起始年"
            value={yearStart}
            onChange={(v) => setYearStart(v ?? undefined)}
            style={{ width: 100 }}
            min={1900}
            max={2100}
          />
          <span style={{ padding: '0 4px' }}>~</span>
          <InputNumber
            placeholder="结束年"
            value={yearEnd}
            onChange={(v) => setYearEnd(v ?? undefined)}
            style={{ width: 100 }}
            min={1900}
            max={2100}
          />
          <Select
            value={sortBy}
            onChange={(v) => { setSortBy(v); const fieldMap: Record<string, string | null> = { created: 'created_at', title: 'title', authors: 'authors', year: 'pub_year', journal: 'journal', province: 'province', status: 'extraction_status' }; setSortInfo({ field: fieldMap[v] || 'created_at', order: sortOrder === 'asc' ? 'ascend' : 'descend' }); }}
            style={{ width: 100 }}
            options={[
              { value: 'created', label: '创建时间' },
              { value: 'title', label: '标题' },
              { value: 'authors', label: '作者' },
              { value: 'year', label: '年份' },
              { value: 'journal', label: '期刊' },
              { value: 'province', label: '省份' },
              { value: 'status', label: '状态' },
            ]}
          />
          <Select
            value={sortOrder}
            onChange={(v) => { setSortOrder(v); setSortInfo((prev) => ({ ...prev, order: v === 'asc' ? 'ascend' : 'descend' })); }}
            style={{ width: 80 }}
            options={[
              { value: 'desc', label: '降序' },
              { value: 'asc', label: '升序' },
            ]}
          />
          <Select
            value={reviewStatus}
            onChange={(v) => setReviewStatus(v || '')}
            style={{ width: 100 }}
            placeholder="审核状态"
            allowClear
            options={[
              { value: 'pending', label: '未审核' },
              { value: 'partial', label: '部分审核' },
              { value: 'approved', label: '已完成' },
              { value: 'none', label: '无数据' },
            ]}
          />
          <Button icon={<ReloadOutlined />} onClick={() => {
            setKeyword(''); setDisease(''); setProvince(''); setYearStart(undefined);
            setYearEnd(undefined); setJournal(''); setSortBy('created'); setSortOrder('desc');
            setReviewStatus(''); setPage(1); setPageSize(20);
            setSortInfo({ field: 'created_at', order: 'descend' });
          }}>重置筛选</Button>
          <Button type="primary" icon={<SearchOutlined />} onClick={fetchList}>查询</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => {
            // 打开上传弹窗时，预填充已保存的默认模型
            const saved = loadSavedDefaultModel();
            if (saved && saved.model) {
              form.setFieldsValue({
                model: saved.model,
                apiKey: saved.apiKey || '',
                baseUrl: saved.baseUrl || '',
                customModel: saved.customModel || '',
              });
            }
            setSaveAsDefault(false);
            setUploadOpen(true);
          }}>
            上传文献
          </Button>
          <Button icon={<LinkOutlined />} onClick={() => {
            setUrlInput('');
            setUrlTitle('');
            setUrlProvince('');
            setUrlModalOpen(true);
          }}>
            从 URL 导入
          </Button>
          <Button icon={<CopyOutlined />} onClick={() => setScanOpen(true)}>
            扫描重复
          </Button>
          <Button icon={<ExportOutlined />} onClick={() => {
            const params = new URLSearchParams();
            if (keyword) params.set('keyword', keyword);
            if (disease) params.set('disease', disease);
            if (province) params.set('province', province);
            if (yearStart) params.set('year_start', String(yearStart));
            if (yearEnd) params.set('year_end', String(yearEnd));
            if (journal) params.set('journal', journal);
            if (reviewStatus) params.set('review_status', reviewStatus);
            window.open(`/api/v1/literatures/export?${params.toString()}`);
          }}>
            导出 CSV
          </Button>
        </Space>
      </Card>

      <Card>
        <Table
          rowKey="id"
          dataSource={items}
          columns={columns}
          loading={loading}
          onChange={handleTableChange}
          pagination={{
            current: page,
            total: loading ? items.length : total,
            pageSize,
            pageSizeOptions: [10, 20, 50, 100],
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
          }}
          scroll={{ x: 1100 }}
          size="middle"
        />
      </Card>

      <Modal
        title="上传文献"
        open={uploadOpen}
        onCancel={() => { setUploadOpen(false); form.resetFields(); setSaveAsDefault(false); setBatchProgress({ current: 0, total: 0, fileName: '' }); }}
        onOk={handleUpload}
        confirmLoading={uploading}
        okText={uploading ? `上传中 (${batchProgress.current}/${batchProgress.total})` : '上传'}
        okButtonProps={{ disabled: uploading }}
        width={520}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="file" label="文献文件（支持多选）" rules={[{ required: true, message: '请选择文件' }]} valuePropName="fileList" getValueFromEvent={(e: any) => e?.fileList}>
            <Upload beforeUpload={() => false} accept=".pdf,.caj,.epub,.docx,.pptx,.xlsx,.txt,.html,.htm" maxCount={20} multiple>
              <Button icon={<UploadOutlined />}>选择文献文件（可多选）</Button>
            </Upload>
          </Form.Item>
          <Form.Item name="title" label="标题（选填，批量上传时忽略）">
            <Input placeholder="文献标题" disabled={uploading} />
          </Form.Item>
          <Form.Item name="doi" label="DOI（选填，批量上传时忽略）">
            <Input placeholder="如 10.1038/..." disabled={uploading} />
          </Form.Item>
          <Form.Item name="province" label="省份（选填，批量上传时忽略）">
            <Input placeholder="如 北京" disabled={uploading} />
          </Form.Item>
          <Form.Item name="model" label="AI 提取模型" tooltip="选择用于 AI 数据提取的大语言模型。默认配置使用后端 .env 中 LLM_MODEL 设定的模型（当前为 DeepSeek Chat 远程 API）。本地 Ollama 模型无需 API Key，但需先在本地安装并运行 Ollama 服务。">
            <Select placeholder="默认配置（后端配置的模型）" allowClear disabled={uploading} style={{ width: '100%' }}>
              {MODEL_OPTIONS.map((opt) => (
                <Select.Option key={opt.value || '__default__'} value={opt.value}>{opt.label}</Select.Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item noStyle dependencies={['model']}>
            {({ getFieldValue }) => {
              const m = getFieldValue('model');
              const desc = MODEL_OPTIONS.find((o) => o.value === m)?.description;
              if (!desc) return null;
              return (
                <div style={{ color: '#888', fontSize: 12, marginTop: -8, marginBottom: 8, paddingLeft: 2, paddingRight: 2 }}>
                  {desc}
                </div>
              );
            }}
          </Form.Item>
          <Form.Item noStyle dependencies={['model']}>
            {({ getFieldValue }) => {
              const model = getFieldValue('model');
              if (model === 'ollama:custom') {
                return (
                  <Form.Item name="customModel" label="自定义模型名称" tooltip="输入 Ollama 中已安装的模型名称，如 qwen3:32b、glm4:9b 等">
                    <Input placeholder="如 qwen3:32b" disabled={uploading} />
                  </Form.Item>
                );
              }
              return null;
            }}
          </Form.Item>
          <Form.Item name="autoExtract" valuePropName="checked" initialValue={true}>
            <Checkbox disabled={uploading}>上传后自动启动 AI 提取（取消则仅上传文件，后续可手动提取）</Checkbox>
          </Form.Item>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <Checkbox
              disabled={uploading}
              checked={saveAsDefault}
              onChange={(e) => setSaveAsDefault(e.target.checked)}
            >
              将当前选择的模型设为默认
            </Checkbox>
            {savedDefault && (
              <>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  当前默认：{MODEL_OPTIONS.find((o) => o.value === savedDefault.model)?.label || savedDefault.model || '后端配置'}
                </Text>
                <Button
                  type="link"
                  size="small"
                  danger
                  disabled={uploading}
                  onClick={() => { clearDefaultModel(); setSavedDefault(null); message.info('已清除自定义默认模型，将使用后端配置'); }}
                >
                  清除
                </Button>
              </>
            )}
          </div>
          <Form.Item noStyle dependencies={['model']}>
            {({ getFieldValue }) => {
              const model = getFieldValue('model');
              const vendor = MODEL_OPTIONS.find((o) => o.value === model)?.vendor || '';
              const info = VENDOR_INFO[vendor];
              if (!vendor || !info.name) return null;
              if (info.isLocal) {
                return (
                  <Form.Item name="baseUrl" label="Ollama 服务地址（选填）" tooltip="Ollama 默认运行在 localhost:11434，如有自定义端口请修改">
                    <Input placeholder={info.baseUrlLabel} defaultValue={info.defaultBaseUrl} disabled={uploading} />
                  </Form.Item>
                );
              }
              return (
                <Form.Item name="apiKey" label="API Key（选填）">
                  <Input.Password placeholder={info.apiKeyLabel} disabled={uploading} />
                </Form.Item>
              );
            }}
          </Form.Item>
          <Form.Item noStyle dependencies={['model']}>
            {({ getFieldValue }) => {
              const model = getFieldValue('model');
              const vendor = MODEL_OPTIONS.find((o) => o.value === model)?.vendor || '';
              const info = VENDOR_INFO[vendor];
              if (!vendor || !info.name || info.isLocal) return null;
              return (
                <Form.Item name="baseUrl" label="API Base URL（选填）">
                  <Input placeholder={info.baseUrlLabel} defaultValue={info.defaultBaseUrl} disabled={uploading} />
                </Form.Item>
              );
            }}
          </Form.Item>
          {/* 批量上传进度 */}
          {uploading && batchProgress.total > 0 && (
            <div style={{ marginTop: 12 }}>
              <Progress percent={Math.round((batchProgress.current / batchProgress.total) * 100)}
                format={() => `${batchProgress.current}/${batchProgress.total}`} />
              <div style={{ fontSize: 12, color: '#888', marginTop: 4, wordBreak: 'break-all' }}>
                正在处理：{batchProgress.fileName}
              </div>
            </div>
          )}
        </Form>
      </Modal>

      {/* URL 导入对话框 */}
      <Modal
        title={<><LinkOutlined /> 从 URL 导入文献</>}
        open={urlModalOpen}
        onCancel={() => { setUrlModalOpen(false); setUrlInput(''); setUrlTitle(''); setUrlProvince(''); }}
        onOk={async () => {
          if (!urlInput.trim()) { message.error('请输入 URL'); return; }
          setUrlImporting(true);
          try {
            const lit = await createLiteratureFromUrl(
              urlInput.trim(),
              urlTitle.trim() || undefined,
              urlProvince.trim() || undefined,
            );
            message.success(`URL 导入成功：${lit.title || lit.id}`);
            setUrlModalOpen(false);
            setUrlInput('');
            setUrlTitle('');
            setUrlProvince('');
            fetchList();
          } catch (err) {
            console.error('[Literature] URL 导入失败:', err);
            message.error('URL 导入失败');
          } finally {
            setUrlImporting(false);
          }
        }}
        confirmLoading={urlImporting}
        okText="导入"
        width={520}
      >
        <div style={{ marginBottom: 16, color: '#888' }}>
          输入网页 URL，系统将自动抓取页面 HTML 内容并创建文献记录。
        </div>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Input
            placeholder="https://example.com/article"
            value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            prefix={<LinkOutlined />}
          />
          <Input
            placeholder="文献标题（选填，留空则自动从页面提取）"
            value={urlTitle}
            onChange={(e) => setUrlTitle(e.target.value)}
          />
          <Input
            placeholder="关联省份（选填）"
            value={urlProvince}
            onChange={(e) => setUrlProvince(e.target.value)}
          />
        </Space>
      </Modal>

      <Modal
        title={<><RobotOutlined /> 选择提取模型</>}
        open={extractModalOpen}
        onCancel={() => setExtractModalOpen(false)}
        onOk={confirmExtract}
        confirmLoading={extracting}
        okText="开始提取"
        width={560}
      >
        <p style={{ marginBottom: 12, color: '#888' }}>
          选择用于 AI 数据提取的大语言模型。<strong>默认配置</strong>使用后端 .env 中 LLM_MODEL 设定的模型（当前为 DeepSeek Chat 远程 API）。
          本地 Ollama 模型无需 API Key，但需先在本地运行 <code>ollama serve</code>。
        </p>
        <Select
          placeholder="默认配置（后端配置的模型）"
          allowClear
          style={{ width: '100%', marginBottom: 8 }}
          value={extractModel}
          onChange={(v) => {
            setExtractModel(v);
            const vendor = MODEL_OPTIONS.find((o) => o.value === v)?.vendor || '';
            setExtractBaseUrl(VENDOR_INFO[vendor]?.defaultBaseUrl || '');
          }}
        >
          {MODEL_OPTIONS.map((opt) => (
            <Select.Option key={opt.value || '__default__'} value={opt.value}>{opt.label}</Select.Option>
          ))}
        </Select>
        {extractModel && (() => {
          const desc = MODEL_OPTIONS.find((o) => o.value === extractModel)?.description;
          return desc ? <div style={{ color: '#888', fontSize: 12, marginBottom: 12 }}>{desc}</div> : null;
        })()}
        {extractModel === 'ollama:custom' && (
          <Input
            placeholder="输入 Ollama 模型名称，如 qwen3:32b"
            style={{ marginBottom: 12 }}
            onChange={(e) => setExtractCustomModel(e.target.value)}
          />
        )}
        {extractModel && extractModel !== '' && (() => {
          const vendor = MODEL_OPTIONS.find((o) => o.value === extractModel)?.vendor || '';
          const info = VENDOR_INFO[vendor];
          if (!vendor || !info.name) return null;
          if (info.isLocal) {
            return (
              <Input
                placeholder={info.baseUrlLabel}
                value={extractBaseUrl}
                onChange={(e) => setExtractBaseUrl(e.target.value)}
                style={{ marginBottom: 12 }}
              />
            );
          }
          return (
            <>
              <Input.Password
                placeholder={info.apiKeyLabel}
                value={extractApiKey}
                onChange={(e) => setExtractApiKey(e.target.value)}
                style={{ marginBottom: 12 }}
              />
              <Input
                placeholder={info.baseUrlLabel}
                value={extractBaseUrl}
                onChange={(e) => setExtractBaseUrl(e.target.value)}
              />
            </>
          );
        })()}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12, paddingTop: 8, borderTop: '1px solid #f0f0f0' }}>
          <Checkbox
            checked={saveAsDefault}
            onChange={(e) => setSaveAsDefault(e.target.checked)}
          >
            将当前选择的模型设为默认
          </Checkbox>
          {savedDefault && (
            <>
              <Text type="secondary" style={{ fontSize: 12 }}>
                当前默认：{MODEL_OPTIONS.find((o) => o.value === savedDefault.model)?.label || savedDefault.model || '后端配置'}
              </Text>
              <Button
                type="link"
                size="small"
                danger
                onClick={() => { clearDefaultModel(); setSavedDefault(null); message.info('已清除自定义默认模型'); }}
              >
                清除
              </Button>
            </>
          )}
        </div>
      </Modal>

      <PdfPreviewModal
        open={previewOpen}
        literatureId={previewLitId}
        literatureTitle={previewLitTitle}
        onClose={() => setPreviewOpen(false)}
      />

      {/* 上传后查重警告 */}
      <Modal
        title={<><CopyOutlined /> 发现重复文献</>}
        open={dupWarningOpen}
        onCancel={() => { setDupWarningOpen(false); setDupWarnings([]); }}
        width={680}
        footer={[
          <Button key="scan" icon={<CopyOutlined />} onClick={() => { setDupWarningOpen(false); setDupWarnings([]); setScanOpen(true); }}>
            打开扫描面板
          </Button>,
          <Button key="close" type="primary" onClick={() => { setDupWarningOpen(false); setDupWarnings([]); }}>
            稍后处理
          </Button>,
        ]}
      >
        <p style={{ marginBottom: 12 }}>
          上传过程中发现 <Text strong type="danger">{dupWarnings.length}</Text> 篇文献与库中已有记录重复，建议进行合并处理。
        </p>
        <Collapse
          items={dupWarnings.map((w, i) => ({
            key: String(i),
            label: (
              <Space>
                <Text strong>{w.litTitle}</Text>
                <Tag color="red">{w.duplicates.length} 条重复</Tag>
              </Space>
            ),
            children: (
              <div>
                {w.duplicates.map((d, j) => (
                  <div key={j} style={{
                    padding: '6px 8px', marginBottom: 4, background: '#fafafa',
                    borderRadius: 4, border: '1px solid #f0f0f0',
                  }}>
                    <Space wrap>
                      <Text strong>{d.literature.title}</Text>
                      {d.literature.pub_year && <Text type="secondary">{d.literature.pub_year}年</Text>}
                      {d.match_reasons.map((r) => (
                        <Tag key={r} color={
                          r === 'doi' ? 'red' : r === 'title' ? 'orange' :
                          r === 'title+authors' ? 'gold' : r === 'pdf_hash' ? 'volcano' : 'blue'
                        }>
                          {r === 'doi' ? 'DOI相同' : r === 'title' ? '标题相同' :
                           r === 'title+authors' ? '标题+作者相似' : r === 'pdf_hash' ? '文件哈希相同' : r}
                        </Tag>
                      ))}
                    </Space>
                  </div>
                ))}
                <Button
                  type="primary"
                  size="small"
                  style={{ marginTop: 8 }}
                  onClick={() => {
                    const dup = w.duplicates[0];
                    setDupWarningOpen(false);
                    setMergeState({
                      open: true,
                      sourceId: w.litId,
                      targetId: dup.literature.id,
                      sourceTitle: w.litTitle,
                      targetTitle: dup.literature.title,
                    });
                  }}
                >
                  合并到已有文献
                </Button>
              </div>
            ),
          }))}
        />
      </Modal>

      {/* 全库扫描面板 */}
      <DuplicateScanPanel
        open={scanOpen}
        onClose={() => setScanOpen(false)}
        onMerge={(sourceId, targetId, sourceTitle, targetTitle) => {
          setScanOpen(false);
          setMergeState({ open: true, sourceId, targetId, sourceTitle, targetTitle });
        }}
      />

      {/* 合并对话框 */}
      <MergeDialog
        open={mergeState.open}
        sourceId={mergeState.sourceId}
        targetId={mergeState.targetId}
        sourceTitle={mergeState.sourceTitle}
        targetTitle={mergeState.targetTitle}
        onClose={() => setMergeState((s) => ({ ...s, open: false }))}
        onMerged={() => {
          setMergeState((s) => ({ ...s, open: false }));
          fetchList();
        }}
      />
    </>
  );
};

export default LiteraturePage;
