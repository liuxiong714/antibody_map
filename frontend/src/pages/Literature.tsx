import React, { useCallback, useEffect, useState } from 'react';
import {
  Card, Table, Button, Input, InputNumber, Space, Modal, Upload, Form, Select, message, Popconfirm, Tag, Tooltip, Progress, Collapse, Typography, Checkbox, Dropdown, Switch, DatePicker,
} from 'antd';
import { UploadOutlined, SearchOutlined, DeleteOutlined, ExperimentOutlined, PlusOutlined, RobotOutlined, ReloadOutlined, EyeOutlined, DownloadOutlined, CopyOutlined, ExportOutlined, LinkOutlined, SyncOutlined, ImportOutlined, FileTextOutlined, TableOutlined, FilePdfOutlined, FileUnknownOutlined, BookOutlined, FileWordOutlined, FilePptOutlined, FileExcelOutlined, GlobalOutlined, FileOutlined, StopOutlined, FolderOpenOutlined, ShrinkOutlined, PaperClipOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useNavigate } from 'react-router-dom';
import { Resizable, ResizeCallbackData } from 'react-resizable';
import 'react-resizable/css/styles.css';
import DiseaseSelector from '../components/DiseaseSelector';
import StatusBadge from '../components/StatusBadge';
import PdfPreviewModal from '../components/PdfPreviewModal';
import MergeDialog from '../components/MergeDialog';
import DuplicateScanPanel from '../components/DuplicateScanPanel';
import { listLiterature, deleteLiterature, batchDeleteLiteratures, uploadLiterature, uploadLiteratureFile, downloadLiteratureFile, triggerExtraction, triggerBatchExtraction, checkDuplicate, createLiteratureFromUrl, syncMetadata, syncMetadataBatch, importLiteratures, stopExtraction, resetStuckExtractions, batchImportFromFolder, batchUploadFiles, BatchImportResult, openLiteratureFolder, cleanupEmpty, CleanupEmptyResult } from '../services/literature';
import { Literature, DuplicateMatchItem } from '../types';
import { VENDOR_INFO, EXTRACTION_STATUS_META, PROVINCES } from '../utils/constants';
import { buildModelOptions, ExtendedModelOption } from '../utils/modelOptions';
import { formatAuthors } from '../utils/format';
import dayjs from 'dayjs';

const { Text } = Typography;

// 列宽状态（可拖拽调整，标题列默认较宽以完整显示）
const DEFAULT_COL_WIDTHS: Record<string, number> = {
  title: 175,
  authors: 90,
  journal: 85,
  year: 55,
  province: 65,
  file_format: 70,
  has_abstract: 60,
  status: 80,
  review_status: 120,
  created: 80,
  actions: 185,
};

// ===== 可调整宽度的表头 =====
// 通过 react-resizable 实现拖拽列宽，保证标题等长文本可完整展示
interface ResizableTitleProps extends React.HTMLAttributes<HTMLTableCellElement> {
  width?: number;
  onResize?: (e: React.SyntheticEvent, data: ResizeCallbackData) => void;
}
const ResizableTitle: React.FC<ResizableTitleProps> = (props) => {
  const { onResize, width, children, ...restProps } = props;
  if (!width || !onResize) {
    return <th {...restProps}>{children}</th>;
  }
  return (
    <Resizable
      width={width}
      height={0}
      handle={
        <span
          className="react-resizable-handle"
          onClick={(e) => { e.stopPropagation(); }}
        />
      }
      onResize={onResize}
      draggableOpts={{ enableUserSelectHack: false }}
      minConstraints={[60, 0]}
      maxConstraints={[1200, 0]}
    >
      <th {...restProps}>{children}</th>
    </Resizable>
  );
};

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

  // 列宽状态（可拖拽调整）
  const [colWidths, setColWidths] = useState<Record<string, number>>(DEFAULT_COL_WIDTHS);
  const handleColumnResize = (key: string) => (
    _e: React.SyntheticEvent,
    { size }: ResizeCallbackData,
  ) => {
    setColWidths((prev) => ({ ...prev, [key]: Math.max(60, Math.round(size.width)) }));
  };
  const [keyword, setKeyword] = useState(() => (_cachedState?.keyword as string) || '');
  const [disease, setDisease] = useState(() => (_cachedState?.disease as string) || '');
  const [province, setProvince] = useState(() => (_cachedState?.province as string) || '');
  const [yearStart, setYearStart] = useState<number | undefined>(() => _cachedState?.yearStart as number | undefined);
  const [yearEnd, setYearEnd] = useState<number | undefined>(() => _cachedState?.yearEnd as number | undefined);
  const [journal, setJournal] = useState(() => (_cachedState?.journal as string) || '');
  const [sortBy, setSortBy] = useState(() => (_cachedState?.sortBy as string) || 'created');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>(() => (_cachedState?.sortOrder as 'asc' | 'desc') || 'desc');
  const [reviewStatus, setReviewStatus] = useState<string>(() => (_cachedState?.reviewStatus as string) || '');
  const [extractionStatus, setExtractionStatus] = useState<string>(() => (_cachedState?.extractionStatus as string) || '');
  const [fileFormat, setFileFormat] = useState<string>(() => (_cachedState?.fileFormat as string) || '');
  const [titleFilter, setTitleFilter] = useState<string>(() => (_cachedState?.titleFilter as string) || '');
  const [authorsFilter, setAuthorsFilter] = useState<string>(() => (_cachedState?.authorsFilter as string) || '');
  const [createdStart, setCreatedStart] = useState<string | undefined>(() => _cachedState?.createdStart as string | undefined);
  const [createdEnd, setCreatedEnd] = useState<string | undefined>(() => _cachedState?.createdEnd as string | undefined);
  const [sortInfo, setSortInfo] = useState<{ field: string | null; order: 'ascend' | 'descend' | null }>(() => (
    _cachedState?.sortInfo as { field: string | null; order: 'ascend' | 'descend' | null }
  ) || { field: 'created_at', order: 'descend' });
  const [hasAbstract, setHasAbstract] = useState<string>((_cachedState?.hasAbstract as string) || '');
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
      keyword, disease, province, yearStart, yearEnd, journal, reviewStatus, extractionStatus, fileFormat,
      titleFilter, authorsFilter, createdStart, createdEnd, hasAbstract,
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
  // 批量提取模式
  const [batchExtractMode, setBatchExtractMode] = useState(false);
  // 提取时是否保留已审核数据
  const [clearExistingData, setClearExistingData] = useState(true);
  // 表格多选
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [selectedRows, setSelectedRows] = useState<Literature[]>([]);
  // 统一模型候选项（本地模型来自后端 /models，与报告生成等功能保持一致）
  const [modelOptions, setModelOptions] = useState<ExtendedModelOption[]>([]);
  useEffect(() => {
    buildModelOptions().then(setModelOptions);
  }, []);

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

  // 文件导入
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importSkipDuplicates, setImportSkipDuplicates] = useState(true);
  const [importing, setImporting] = useState(false);

  // 从本地文件夹批量导入
  const [folderImportOpen, setFolderImportOpen] = useState(false);
  const [folderFiles, setFolderFiles] = useState<File[]>([]);
  const [folderImporting, setFolderImporting] = useState(false);
  const [folderImportResult, setFolderImportResult] = useState<BatchImportResult | null>(null);

  // 修改关联文件（替换已有文献关联的本地文档）
  const [replaceLit, setReplaceLit] = useState<Literature | null>(null);
  const [replaceFile, setReplaceFile] = useState<File | null>(null);
  const [replacing, setReplacing] = useState(false);
  const [folderImportTriggerExtraction, setFolderImportTriggerExtraction] = useState(true);

  const handleFolderImport = async () => {
    if (folderFiles.length === 0) {
      message.warning('请先选择文件夹');
      return;
    }
    setFolderImporting(true);
    try {
      const result = await batchUploadFiles(folderFiles, folderImportTriggerExtraction);
      setFolderImportResult(result);
      const parts: string[] = [];
      if (result.matched > 0) parts.push(`关联 ${result.matched} 篇`);
      if (result.imported > 0) parts.push(`新建 ${result.imported} 篇`);
      if (result.skipped > 0) parts.push(`跳过 ${result.skipped} 篇`);
      if (result.failed > 0) parts.push(`失败 ${result.failed} 个`);
      let msg = '批量导入完成：' + parts.join('，');
      if (result.extraction_triggered > 0) msg += `，已触发 ${result.extraction_triggered} 篇 AI 提取`;
      message.success(msg);
      fetchList();
    } catch (err: any) {
      console.error('[Literature] 批量导入失败:', err);
      message.error(err.response?.data?.detail || '批量导入失败');
    } finally {
      setFolderImporting(false);
    }
  };

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
      if (extractionStatus) params.extraction_status = extractionStatus;
      if (fileFormat) params.file_format = fileFormat;
      if (titleFilter) params.title = titleFilter;
      if (authorsFilter) params.authors = authorsFilter;
      if (createdStart) params.created_start = createdStart;
      if (createdEnd) params.created_end = createdEnd;
      if (hasAbstract === 'has') params.has_abstract = true;
      if (hasAbstract === 'none') params.has_abstract = false;
      const resp = await listLiterature(params);
      setItems(resp.items);
      setTotal(resp.total);
    } catch (err) {
      console.error('[Literature] 加载文献列表失败:', err);
      message.error('加载文献列表失败');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, keyword, disease, province, yearStart, yearEnd, journal, sortBy, sortOrder, reviewStatus, extractionStatus, fileFormat, titleFilter, authorsFilter, createdStart, createdEnd, hasAbstract]);

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

  const handleBatchDelete = async () => {
    if (selectedRowKeys.length === 0) return;
    try {
      const ids = selectedRowKeys.map((k) => String(k));
      await batchDeleteLiteratures(ids);
      message.success(`已删除 ${ids.length} 篇文献`);
      setSelectedRowKeys([]);
      setSelectedRows([]);
      fetchList();
    } catch (err) {
      console.error('[Literature] 批量删除文献失败:', err);
      message.error('批量删除失败');
    }
  };

  const handleOpenFolder = async (id: string) => {
    try {
      await openLiteratureFolder(id);
      message.success('已打开文件所在文件夹');
    } catch (err: any) {
      console.error('[Literature] 打开所在文件夹失败:', err);
      const detail = err?.response?.data?.detail;
      message.error(detail ? `打开文件夹失败：${detail}` : '打开文件夹失败，文件可能不存在');
    }
  };

  const handleDownload = async (r: Literature) => {
    try {
      await downloadLiteratureFile(r.id, r.title);
    } catch (err: any) {
      console.error('[Literature] 下载失败:', err);
      const detail = err?.response?.data?.detail;
      message.error(detail ? `下载失败：${detail}` : '下载失败，文件可能不存在');
    }
  };

  const handleOpenReplacement = (lit: Literature) => {
    setReplaceLit(lit);
    setReplaceFile(null);
  };

  const handleReplaceCancel = () => {
    if (replacing) return;
    setReplaceLit(null);
    setReplaceFile(null);
  };

  const handleReplaceFile = async () => {
    if (!replaceLit) return;
    if (!replaceFile) {
      message.warning('请先选择要关联的文件');
      return;
    }
    setReplacing(true);
    try {
      await uploadLiteratureFile(replaceLit.id, replaceFile);
      message.success('文件关联已更新');
      setReplaceLit(null);
      setReplaceFile(null);
      fetchList();
    } catch (err: any) {
      console.error('[Literature] 修改关联文件失败:', err);
      const detail = err?.response?.data?.detail;
      message.error(detail ? `更新失败：${detail}` : '更新失败，请检查文件格式与大小');
    } finally {
      setReplacing(false);
    }
  };

  const handleSyncMetadata = async (id: string) => {
    try {
      const result = await syncMetadata(id);
      if (result.pub_year_updated || result.province_updated) {
        const parts: string[] = [];
        if (result.pub_year_updated) parts.push(`年份 → ${result.pub_year}`);
        if (result.province_updated) parts.push(`省份 → ${result.province}`);
        message.success(`元数据已更新：${parts.join('，')}`);
      } else {
        message.info('该文献的元数据已是最新，无需更新');
      }
      fetchList();
    } catch (err) {
      console.error('[Literature] 同步元数据失败:', err);
      message.error('同步元数据失败');
    }
  };
  const [batchSyncing, setBatchSyncing] = useState(false);
  const handleSyncMetadataBatch = async () => {
    setBatchSyncing(true);
    try {
      const result = await syncMetadataBatch();
      if (result.synced > 0) {
        message.success(`批量同步完成：${result.synced} 篇已更新，${result.skipped} 篇无需更新`);
      } else {
        message.info(`没有需要同步的文献（共检查 ${result.total} 篇）`);
      }
      fetchList();
    } catch (err) {
      console.error('[Literature] 批量同步元数据失败:', err);
      message.error('批量同步元数据失败');
    } finally {
      setBatchSyncing(false);
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
      message.info(`已将「${modelOptions.find((o) => o.value === values.model)?.label || '自定义模型'}」设为默认模型`);
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

  const handleImport = async () => {
    if (!importFile) { message.warning('请选择要导入的 JSON 文件'); return; }
    setImporting(true);
    try {
      const result = await importLiteratures(importFile, importSkipDuplicates);
      const parts: string[] = [];
      if (result.imported_count > 0) parts.push(`导入 ${result.imported_count} 篇文献`);
      if (result.data_point_count > 0) parts.push(`${result.data_point_count} 个数据点`);
      if (result.skipped_count > 0) parts.push(`跳过 ${result.skipped_count} 篇重复`);
      if (result.error_count > 0) parts.push(`失败 ${result.error_count} 条`);
      if (result.imported_count > 0) {
        message.success(`导入完成：${parts.join('，')}`);
      } else if (result.skipped_count > 0) {
        message.info(`所有文献均已存在，跳过 ${result.skipped_count} 篇`);
      } else {
        message.warning(`导入未成功：${parts.join('，')}`);
      }
      setImportModalOpen(false);
      setImportFile(null);
      fetchList();
    } catch (err) {
      console.error('[Literature] 导入失败:', err);
      message.error('导入失败，请检查文件格式是否正确');
    } finally {
      setImporting(false);
    }
  };

  // 停止单篇文献提取（重置卡住的 processing 状态为 failed）
  const [stoppingIds, setStoppingIds] = useState<Set<string>>(new Set());
  const handleStopExtraction = async (id: string) => {
    setStoppingIds((prev) => { const n = new Set(prev); n.add(id); return n; });
    try {
      const result = await stopExtraction(id);
      message.success(`已停止提取，状态重置为失败（当前状态：${result.status}）`);
      fetchList();
    } catch (err) {
      console.error('[Literature] 停止提取失败:', err);
      message.error('停止提取失败，请检查后端服务是否正常');
    } finally {
      setStoppingIds((prev) => { const n = new Set(prev); n.delete(id); return n; });
    }
  };

  // 批量重置所有卡在 processing 状态的文献为 failed
  const [resettingStuck, setResettingStuck] = useState(false);
  const handleResetStuck = async () => {
    setResettingStuck(true);
    try {
      const result = await resetStuckExtractions();
      if (result.reset_count > 0) {
        message.success(`已重置 ${result.reset_count} 篇卡住的提取状态为失败`);
      } else {
        message.info('当前没有卡住的提取任务');
      }
      fetchList();
    } catch (err) {
      console.error('[Literature] 重置卡住提取失败:', err);
      message.error('重置卡住提取失败，请检查后端服务是否正常');
    } finally {
      setResettingStuck(false);
    }
  };

  const handleExtract = (id: string) => {
    setBatchExtractMode(false);
    setExtractLitId(id);
    // 预填充已保存的默认模型
    const saved = loadSavedDefaultModel();
    if (saved && saved.model) {
      setExtractModel(saved.model);
      const vendor = modelOptions.find((o) => o.value === saved.model)?.vendor || '';
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

  const handleBatchExtract = () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要重新提取的文献');
      return;
    }
    setBatchExtractMode(true);
    setExtractLitId(null);
    // 预填充已保存的默认模型
    const saved = loadSavedDefaultModel();
    if (saved && saved.model) {
      setExtractModel(saved.model);
      const vendor = modelOptions.find((o) => o.value === saved.model)?.vendor || '';
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
        message.info(`已将「${modelOptions.find((o) => o.value === extractModel)?.label || '自定义模型'}」设为默认模型`);
      }

      const modelLabel = modelOptions.find((o) => o.value === extractModel)?.label
        || (extractCustomModel ? `Ollama:${extractCustomModel}` : '默认模型');
      const options = (model && model !== '') ? {
        model,
        apiKey: extractApiKey || undefined,
        baseUrl: extractBaseUrl || undefined,
        clearExistingData,
      } : (clearExistingData !== undefined ? { model: '', clearExistingData } : undefined);

      if (batchExtractMode) {
        // 批量提取模式
        const ids = selectedRowKeys.map((k) => String(k));
        const result = await triggerBatchExtraction(ids, options);
        const parts: string[] = [];
        if (result.submitted_count > 0) parts.push(`成功提交 ${result.submitted_count} 篇`);
        if (result.skipped_count > 0) parts.push(`跳过 ${result.skipped_count} 篇`);
        if (result.error_count > 0) parts.push(`失败 ${result.error_count} 篇`);
        if (result.submitted_count > 0) {
          message.success(`批量提取已使用 ${modelLabel} 启动：${parts.join('，')}`);
        } else {
          message.warning(`批量提取未提交任何文献：${parts.join('，')}`);
        }
      } else {
        // 单篇提取模式
        if (!extractLitId) return;
        if (options) {
          await triggerExtraction(extractLitId, options);
        } else {
          await triggerExtraction(extractLitId);
        }
        message.success(`已使用 ${modelLabel} 启动 AI 提取`);
      }

      setExtractModalOpen(false);
      setExtractCustomModel('');
      setSaveAsDefault(false);
      setSelectedRowKeys([]);
      setSelectedRows([]);
      fetchList();
    } catch (err) {
      console.error('[Literature] 提取失败:', err);
      message.error(batchExtractMode ? '批量提取失败，请检查后端服务是否正常' : '提取失败，请检查后端服务是否正常');
    } finally {
      setExtracting(false);
    }
  };

  const handleTableChange = (pagination: any, filters: any, sorter: any) => {
    // 处理分页变更
    if (pagination.current !== page || pagination.pageSize !== pageSize) {
      // 切换分页参数时清空旧数据，避免 dataSource 与新 pageSize 不匹配触发 antd 警告
      setItems([]);
      setPage(pagination.current);
      setPageSize(pagination.pageSize);
    }
    // 处理筛选变更
    const f = filters || {};
    setFileFormat(f.file_format?.[0] || '');
    setTitleFilter(f.title?.[0] || '');
    setAuthorsFilter(f.authors?.[0] || '');
    setJournal(f.journal?.[0] || '');
    setProvince(f.province?.[0] || '');
    setYearStart(f.year?.[0] !== undefined ? Number(f.year?.[0]) : undefined);
    setYearEnd(f.year?.[1] !== undefined ? Number(f.year?.[1]) : undefined);
    setExtractionStatus(f.status?.[0] || '');
    setReviewStatus(f.review_status?.[0] || '');
    setCreatedStart(f.created?.[0] || undefined);
    setCreatedEnd(f.created?.[1] || undefined);
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
        review_status: 'review_status',
        file_format: 'file_format',
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
      width: colWidths.title,
      ellipsis: true,
      sorter: true,
      sortOrder: sortInfo.field === 'title' ? sortInfo.order : null,
      filteredValue: titleFilter ? [titleFilter] : null,
      filterDropdown: ({ setSelectedKeys, selectedKeys, confirm, clearFilters }) => (
        <div style={{ padding: 8 }}>
          <Input
            placeholder="按标题模糊搜索"
            value={selectedKeys[0] as string}
            onChange={(e) => setSelectedKeys(e.target.value ? [e.target.value] : [])}
            onPressEnter={() => confirm()}
            style={{ width: 188, marginBottom: 8, display: 'block' }}
            allowClear
          />
          <Space>
            <Button type="primary" size="small" onClick={() => confirm()}>确定</Button>
            <Button
              size="small"
              onClick={() => { clearFilters?.(); setSelectedKeys([]); confirm(); }}
            >重置</Button>
          </Space>
        </div>
      ),
      onHeaderCell: () => ({ width: colWidths.title, onResize: handleColumnResize('title') }),
      render: (t: string, r: Literature) => (
        <a onClick={() => saveStateAndNavigate(r.id)} title={t}>{t}</a>
      ),
    },
    {
      title: '作者',
      dataIndex: 'authors',
      key: 'authors',
      width: colWidths.authors,
      ellipsis: true,
      sorter: true,
      sortOrder: sortInfo.field === 'authors' ? sortInfo.order : null,
      filteredValue: authorsFilter ? [authorsFilter] : null,
      filterDropdown: ({ setSelectedKeys, selectedKeys, confirm, clearFilters }) => (
        <div style={{ padding: 8 }}>
          <Input
            placeholder="按作者模糊搜索"
            value={selectedKeys[0] as string}
            onChange={(e) => setSelectedKeys(e.target.value ? [e.target.value] : [])}
            onPressEnter={() => confirm()}
            style={{ width: 188, marginBottom: 8, display: 'block' }}
            allowClear
          />
          <Space>
            <Button type="primary" size="small" onClick={() => confirm()}>确定</Button>
            <Button
              size="small"
              onClick={() => { clearFilters?.(); setSelectedKeys([]); confirm(); }}
            >重置</Button>
          </Space>
        </div>
      ),
      onHeaderCell: () => ({ width: colWidths.authors, onResize: handleColumnResize('authors') }),
      render: (v: string) => formatAuthors(v),
    },
    {
      title: '期刊',
      dataIndex: 'journal',
      key: 'journal',
      width: colWidths.journal,
      ellipsis: true,
      sorter: true,
      sortOrder: sortInfo.field === 'journal' ? sortInfo.order : null,
      filteredValue: journal ? [journal] : null,
      filterDropdown: ({ setSelectedKeys, selectedKeys, confirm, clearFilters }) => (
        <div style={{ padding: 8 }}>
          <Input
            placeholder="按期刊模糊搜索"
            value={selectedKeys[0] as string}
            onChange={(e) => setSelectedKeys(e.target.value ? [e.target.value] : [])}
            onPressEnter={() => confirm()}
            style={{ width: 188, marginBottom: 8, display: 'block' }}
            allowClear
          />
          <Space>
            <Button type="primary" size="small" onClick={() => confirm()}>确定</Button>
            <Button
              size="small"
              onClick={() => { clearFilters?.(); setSelectedKeys([]); confirm(); }}
            >重置</Button>
          </Space>
        </div>
      ),
      onHeaderCell: () => ({ width: colWidths.journal, onResize: handleColumnResize('journal') }),
      render: (v: string) => v || '-',
    },
    {
      title: (
        <Tooltip title="文献的发表年份，与文献中样本的采集年份（数据点详情中的「采集年份」）不是同一个概念">
          发表年份
        </Tooltip>
      ),
      dataIndex: 'pub_year',
      key: 'year',
      width: colWidths.year,
      sorter: true,
      sortOrder: sortInfo.field === 'pub_year' ? sortInfo.order : null,
      filteredValue: (() => {
        const arr: React.Key[] = [];
        if (yearStart !== undefined) arr.push(yearStart);
        if (yearEnd !== undefined) arr.push(yearEnd);
        return arr.length ? arr : null;
      })(),
      filterDropdown: ({ setSelectedKeys, selectedKeys, confirm, clearFilters }) => {
        // 只保留有效年份，避免把 null/空串写入 filters（否则会被误筛成 0）
        const applyYears = (start: number | string | null | undefined, end: number | string | null | undefined) => {
          const keys: React.Key[] = [];
          const s = typeof start === 'string' ? (start ? Number(start) : null) : start;
          const e = typeof end === 'string' ? (end ? Number(end) : null) : end;
          if (s !== null && s !== undefined) keys.push(s);
          if (e !== null && e !== undefined) keys.push(e);
          setSelectedKeys(keys);
        };
        return (
          <div style={{ padding: 8 }}>
            <Space>
              <InputNumber
                placeholder="起始年"
                value={selectedKeys[0] ? Number(selectedKeys[0]) : undefined}
                onChange={(v) => applyYears(v, (selectedKeys[1] as number | string | undefined) ?? null)}
                style={{ width: 100 }}
                min={1900}
                max={2100}
              />
              <span style={{ padding: '0 4px' }}>~</span>
              <InputNumber
                placeholder="结束年"
                value={selectedKeys[1] ? Number(selectedKeys[1]) : undefined}
                onChange={(v) => applyYears((selectedKeys[0] as number | string | undefined) ?? null, v)}
                style={{ width: 100 }}
                min={1900}
                max={2100}
              />
            </Space>
            <Space style={{ marginTop: 8, display: 'flex', justifyContent: 'flex-end' }}>
              <Button type="primary" size="small" onClick={() => confirm()}>确定</Button>
              <Button
                size="small"
                onClick={() => { clearFilters?.(); setSelectedKeys([]); }}
              >重置</Button>
            </Space>
          </div>
        );
      },
      onHeaderCell: () => ({ width: colWidths.year, onResize: handleColumnResize('year') }),
      render: (v: number | null) => v || '-',
    },
    {
      title: '省份',
      dataIndex: 'province',
      key: 'province',
      width: colWidths.province,
      sorter: true,
      sortOrder: sortInfo.field === 'province' ? sortInfo.order : null,
      filteredValue: province ? [province] : null,
      filterDropdown: ({ setSelectedKeys, selectedKeys, confirm, clearFilters }) => (
        <div style={{ padding: 8 }}>
          <Select
            placeholder="选择省份"
            value={selectedKeys[0] as string}
            onChange={(v) => setSelectedKeys(v ? [v] : [])}
            style={{ width: 160, marginBottom: 8 }}
            allowClear
            options={PROVINCES.map((p) => ({ value: p, label: p }))}
          />
          <Space style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <Button type="primary" size="small" onClick={() => confirm()}>确定</Button>
            <Button
              size="small"
              onClick={() => { clearFilters?.(); setSelectedKeys([]); confirm(); }}
            >重置</Button>
          </Space>
        </div>
      ),
      onHeaderCell: () => ({ width: colWidths.province, onResize: handleColumnResize('province') }),
      render: (v: string) => v || '-',
    },
    {
      title: '文档',
      dataIndex: 'file_format',
      key: 'file_format',
      width: colWidths.file_format,
      sorter: true,
      sortOrder: sortInfo.field === 'file_format' ? sortInfo.order : null,
      filters: [
        { text: 'PDF', value: 'PDF' },
        { text: 'CAJ', value: 'CAJ' },
        { text: 'EPUB', value: 'EPUB' },
        { text: 'DOCX', value: 'DOCX' },
        { text: 'PPTX', value: 'PPTX' },
        { text: 'XLSX', value: 'XLSX' },
        { text: 'TXT', value: 'TXT' },
        { text: 'HTML', value: 'HTML' },
        { text: 'URL', value: 'URL' },
        { text: '无', value: '__none__' },
      ],
      filteredValue: fileFormat ? [fileFormat] : null,
      onFilter: undefined,
      onHeaderCell: () => ({ width: colWidths.file_format, onResize: handleColumnResize('file_format') }),
      render: (_: unknown, r: Literature) => {
        const fmt = r.file_format;
        const hasFile = !!fmt;
        // 各格式对应的颜色与图标
        const formatColorMap: Record<string, string> = {
          PDF: '#f5222d',
          CAJ: '#722ed1',
          EPUB: '#fa8c16',
          DOCX: '#1677ff',
          PPTX: '#d46b08',
          XLSX: '#389e0d',
          TXT: '#8c8c8c',
          HTML: '#13c2c2',
          URL: '#2f54eb',
        };
        if (!hasFile) {
          return (
            <Tooltip title="暂无本地文档（仅元数据）">
              <Tag color="default" style={{ border: '1px dashed #d9d9d9' }}>
                <FileUnknownOutlined style={{ marginRight: 2 }} />
                无
              </Tag>
            </Tooltip>
          );
        }
        const color = formatColorMap[fmt!] || '#595959';
        const formatIconMap: Record<string, React.ReactNode> = {
          PDF: <FilePdfOutlined />,
          CAJ: <FileTextOutlined />,
          EPUB: <BookOutlined />,
          DOCX: <FileWordOutlined />,
          PPTX: <FilePptOutlined />,
          XLSX: <FileExcelOutlined />,
          TXT: <FileTextOutlined />,
          HTML: <LinkOutlined />,
          URL: <GlobalOutlined />,
        };
        const icon = formatIconMap[fmt!] || <FileOutlined />;
        // 点击预览：HTML 直接新标签页打开，其它格式走内部预览弹窗
        const handlePreview = () => {
          const ext = (r.file_path || '').split('.').pop()?.toLowerCase();
          if (ext === 'html' || ext === 'htm') {
            window.open(`/api/v1/literatures/${r.id}/file`, '_blank');
          } else {
            setPreviewLitId(r.id);
            setPreviewLitTitle(r.title);
            setPreviewOpen(true);
          }
        };
        return (
          <Tooltip title={`点击预览 ${fmt!} 文档`}>
            <Tag
              onClick={handlePreview}
              color={color}
              style={{
                cursor: 'pointer',
                fontWeight: 600,
                fontSize: 12,
                paddingLeft: 8,
                paddingRight: 8,
                borderRadius: 4,
              }}
            >
              <span style={{ marginRight: 3 }}>{icon}</span>
              {fmt}
            </Tag>
          </Tooltip>
        );
      },
    },
    {
      title: '摘要',
      dataIndex: 'abstract',
      key: 'has_abstract',
      width: colWidths.has_abstract,
      sorter: true,
      filteredValue: hasAbstract ? [hasAbstract] : null,
      filterDropdown: ({ setSelectedKeys, selectedKeys, confirm, clearFilters }) => (
        <div style={{ padding: 8 }}>
          <Space direction="vertical" style={{ width: '100%' }}>
            <Button
              type={hasAbstract === 'has' ? 'primary' : 'default'}
              size="small"
              block
              onClick={() => {
                setHasAbstract('has');
                setSelectedKeys(['has']);
                confirm();
              }}
            >
              有摘要
            </Button>
            <Button
              type={hasAbstract === 'none' ? 'primary' : 'default'}
              size="small"
              block
              onClick={() => {
                setHasAbstract('none');
                setSelectedKeys(['none']);
                confirm();
              }}
            >
              无摘要
            </Button>
            <Button
              size="small"
              block
              onClick={() => {
                setHasAbstract('');
                setSelectedKeys([]);
                clearFilters?.();
                confirm();
              }}
            >
              重置
            </Button>
          </Space>
        </div>
      ),
      onHeaderCell: () => ({ width: colWidths.has_abstract, onResize: handleColumnResize('has_abstract') }),
      render: (v: string | null) => {
        const _hasAbstract = !!(v && v.trim());
        return _hasAbstract ? (
          <Tooltip title="有摘要">
            <Tag color="green" style={{ borderRadius: 4 }}>
              <FileTextOutlined style={{ marginRight: 2 }} />
              有
            </Tag>
          </Tooltip>
        ) : (
          <Tooltip title="无摘要">
            <Tag color="default" style={{ border: '1px dashed #d9d9d9', borderRadius: 4 }}>
              <FileUnknownOutlined style={{ marginRight: 2 }} />
              无
            </Tag>
          </Tooltip>
        );
      },
    },
    {
      title: '提取状态',
      dataIndex: 'extraction_status',
      key: 'status',
      width: colWidths.status,
      sorter: true,
      sortOrder: sortInfo.field === 'extraction_status' ? sortInfo.order : null,
      filters: Object.entries(EXTRACTION_STATUS_META).map(([k, v]) => ({ text: v.label, value: k })),
      filteredValue: extractionStatus ? [extractionStatus] : null,
      onHeaderCell: () => ({ width: colWidths.status, onResize: handleColumnResize('status') }),
      render: (s: string) => <StatusBadge status={s} />,
    },
    {
      title: '审核状态',
      key: 'review_status',
      width: colWidths.review_status,
      sorter: true,
      sortOrder: sortInfo.field === 'review_status' ? sortInfo.order : null,
      filters: [
        { text: '未审核', value: 'pending' },
        { text: '部分审核', value: 'partial' },
        { text: '已完成', value: 'approved' },
        { text: '无数据', value: 'none' },
      ],
      filteredValue: reviewStatus ? [reviewStatus] : null,
      onHeaderCell: () => ({ width: colWidths.review_status, onResize: handleColumnResize('review_status') }),
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
      width: colWidths.created,
      sorter: true,
      sortOrder: sortInfo.field === 'created_at' ? sortInfo.order : null,
      filteredValue: createdStart || createdEnd ? [createdStart ?? '', createdEnd ?? ''] : null,
      filterDropdown: ({ setSelectedKeys, selectedKeys, confirm, clearFilters }) => (
        <div style={{ padding: 8 }}>
          <DatePicker.RangePicker
            value={[
              selectedKeys[0] ? dayjs(selectedKeys[0] as string) : null,
              selectedKeys[1] ? dayjs(selectedKeys[1] as string) : null,
            ]}
            onChange={(dates) => {
              setSelectedKeys(dates && dates[0] ? [dates[0].format('YYYY-MM-DD'), dates[1] ? dates[1].format('YYYY-MM-DD') : ''] : []);
            }}
            style={{ width: 220, marginBottom: 8, display: 'block' }}
          />
          <Space style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <Button type="primary" size="small" onClick={() => confirm()}>确定</Button>
            <Button
              size="small"
              onClick={() => { clearFilters?.(); setSelectedKeys([]); confirm(); }}
            >重置</Button>
          </Space>
        </div>
      ),
      onHeaderCell: () => ({ width: colWidths.created, onResize: handleColumnResize('created') }),
      render: (v: string) => dayjs(v).format('YYYY-MM-DD'),
    },
    {
      title: '操作',
      key: 'actions',
      width: colWidths.actions,
      onHeaderCell: () => ({ width: colWidths.actions, onResize: handleColumnResize('actions') }),
      render: (_: unknown, r: Literature) => (
        <Space size={4} wrap>
          <Tooltip title="AI 提取">
            <Button
              size="small"
              icon={<ExperimentOutlined />}
              onClick={() => handleExtract(r.id)}
              loading={r.extraction_status === 'processing'}
              disabled={r.extraction_status === 'processing'}
            />
          </Tooltip>
          {r.extraction_status === 'processing' && (
            <Tooltip title="手动停止提取（状态异常时使用）">
              <Popconfirm
                title="确定停止该文献的提取？"
                description="停止后状态将重置为失败，可重新触发提取。"
                onConfirm={() => handleStopExtraction(r.id)}
                okText="停止"
                cancelText="取消"
                okButtonProps={{ danger: true }}
              >
                <Button
                  size="small"
                  danger
                  icon={<StopOutlined />}
                  loading={stoppingIds.has(r.id)}
                />
              </Popconfirm>
            </Tooltip>
          )}
          {r.extraction_status === 'done' && (!r.pub_year || !r.province) && (
            <Tooltip title="同步元数据（从数据点聚合年份/省份）">
              <Button
                size="small"
                icon={<SyncOutlined />}
                onClick={() => handleSyncMetadata(r.id)}
              />
            </Tooltip>
          )}
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
          <Tooltip title="修改关联文件（替换已有的本地文档）">
            <Button
              size="small"
              icon={<PaperClipOutlined />}
              onClick={() => handleOpenReplacement(r)}
            />
          </Tooltip>
          <Tooltip title="下载并用本地阅读器打开">
            <Button
              size="small"
              icon={<DownloadOutlined />}
              onClick={() => handleDownload(r)}
            />
          </Tooltip>
          {r.file_path && (
            <Tooltip title="打开所在文件夹">
              <Button
                size="small"
                icon={<FolderOpenOutlined />}
                onClick={() => handleOpenFolder(r.id)}
              />
            </Tooltip>
          )}
          <Tooltip title="详情">
            <Button
              size="small"
              icon={<FileTextOutlined />}
              onClick={() => saveStateAndNavigate(r.id)}
            />
          </Tooltip>
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
            placeholder="搜索标题/作者/期刊/摘要/关键词"
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
            onChange={(v) => { setSortBy(v); const fieldMap: Record<string, string | null> = { created: 'created_at', title: 'title', authors: 'authors', year: 'pub_year', journal: 'journal', province: 'province', status: 'extraction_status', review_status: 'review_status', file_format: 'file_format' }; setSortInfo({ field: fieldMap[v] || 'created_at', order: sortOrder === 'asc' ? 'ascend' : 'descend' }); }}
            style={{ width: 100 }}
            options={[
              { value: 'created', label: '创建时间' },
              { value: 'title', label: '标题' },
              { value: 'authors', label: '作者' },
              { value: 'year', label: '年份' },
              { value: 'journal', label: '期刊' },
              { value: 'province', label: '省份' },
              { value: 'status', label: '提取状态' },
              { value: 'review_status', label: '审核状态' },
              { value: 'file_format', label: '文档' },
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
          <Select
            value={extractionStatus || undefined}
            onChange={(v) => setExtractionStatus(v || '')}
            style={{ width: 120 }}
            placeholder="提取状态"
            allowClear
            options={Object.entries(EXTRACTION_STATUS_META).map(([k, v]) => ({
              value: k,
              label: v.label,
            }))}
          />
          <Button icon={<ReloadOutlined />} onClick={() => {
            setKeyword(''); setDisease(''); setProvince(''); setYearStart(undefined);
            setYearEnd(undefined); setJournal(''); setSortBy('created'); setSortOrder('desc');
            setReviewStatus(''); setExtractionStatus(''); setFileFormat(''); setPage(1); setPageSize(20);
            setTitleFilter(''); setAuthorsFilter(''); setCreatedStart(undefined); setCreatedEnd(undefined);
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
          <Button icon={<FolderOpenOutlined />} onClick={() => {
            setFolderFiles([]);
            setFolderImportResult(null);
            setFolderImportOpen(true);
          }}>
            从本地文件夹导入
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
          <Button
            icon={<DeleteOutlined />}
            onClick={() => {
              // 先预览，确认后再执行
              cleanupEmpty(true).then((result) => {
                if (result.preview_count === 0) {
                  message.info('没有需要清理的文献（所有文献均有文档或摘要）');
                  return;
                }
                Modal.confirm({
                  title: '确认清理无文档无摘要的文献',
                  content: (
                    <div>
                      <p>发现 <strong>{result.preview_count}</strong> 篇既无文档文件又无摘要内容的文献。</p>
                      <p>删除后不可恢复，确定继续？</p>
                    </div>
                  ),
                  okText: '确认清理',
                  cancelText: '取消',
                  okButtonProps: { danger: true },
                  onOk: async () => {
                    try {
                      const delResult = await cleanupEmpty(false);
                      message.success(`成功清理 ${delResult.deleted_count} 篇文献`);
                      fetchList();
                    } catch (err: any) {
                      message.error(err?.response?.data?.detail || '清理失败');
                    }
                  },
                });
              }).catch((err: any) => {
                message.error(err?.response?.data?.detail || '预览失败');
              });
            }}
          >
            清理无文件文献
          </Button>
          <Button
            icon={<ExperimentOutlined />}
            onClick={handleBatchExtract}
            disabled={selectedRowKeys.length === 0}
          >
            批量AI提取 {selectedRowKeys.length > 0 ? `(${selectedRowKeys.length})` : ''}
          </Button>
          <Button
            icon={<ShrinkOutlined />}
            onClick={() => {
              if (selectedRows.length !== 2) {
                message.warning('请先选择 2 篇文献进行合并（在表格左侧勾选）');
                return;
              }
              // 默认以第一行选中的为源文献，第二行为目标文献
              const [src, tgt] = selectedRows;
              setMergeState({
                open: true,
                sourceId: src.id,
                targetId: tgt.id,
                sourceTitle: src.title,
                targetTitle: tgt.title,
              });
            }}
            disabled={selectedRowKeys.length === 0}
          >
            合并选中 {selectedRowKeys.length > 0 ? `(${selectedRowKeys.length})` : ''}
          </Button>
          <Popconfirm
            title={`批量删除 ${selectedRowKeys.length > 0 ? selectedRowKeys.length : ''} 篇文献`}
            description="将删除选中文献的记录、关联文件及数据点，此操作不可恢复。确定继续？"
            onConfirm={handleBatchDelete}
            disabled={selectedRowKeys.length === 0}
            okButtonProps={{ danger: true }}
          >
            <Button icon={<DeleteOutlined />} danger disabled={selectedRowKeys.length === 0}>
              批量删除 {selectedRowKeys.length > 0 ? `(${selectedRowKeys.length})` : ''}
            </Button>
          </Popconfirm>
          <Popconfirm
            title="批量同步元数据"
            description="将所有提取完成但缺少年份/省份的文献，从数据点自动聚合元数据。确定继续？"
            onConfirm={handleSyncMetadataBatch}
            disabled={batchSyncing}
          >
            <Button icon={<SyncOutlined />} loading={batchSyncing}>
              批量同步元数据
            </Button>
          </Popconfirm>
          <Popconfirm
            title="重置卡住的提取状态"
            description="将所有状态为「提取中」的文献重置为「失败」（适用于服务器重启后状态卡住的情况）。确定继续？"
            onConfirm={handleResetStuck}
            disabled={resettingStuck}
          >
            <Button icon={<StopOutlined />} loading={resettingStuck} danger>
              重置卡住的提取
            </Button>
          </Popconfirm>
          <Dropdown menu={{
            items: [
              { key: 'all_csv', icon: <FileTextOutlined />, label: '导出全部 CSV（仅文献信息）' },
              { key: 'all_xlsx', icon: <FileExcelOutlined />, label: '导出全部 Excel（仅文献信息）' },
              { type: 'divider' },
              { key: 'all_json_dp', icon: <TableOutlined />, label: '导出全部 JSON（含数据点，可导入）' },
              { key: 'all_xlsx_dp', icon: <FileExcelOutlined />, label: '导出全部 Excel（含数据点）' },
              { type: 'divider' },
              { key: 'sel_json_dp', icon: <TableOutlined />, label: `导出选中 JSON（含数据点）${selectedRowKeys.length > 0 ? ` (${selectedRowKeys.length}篇)` : ''}`, disabled: selectedRowKeys.length === 0 },
              { key: 'sel_xlsx_dp', icon: <FileExcelOutlined />, label: `导出选中 Excel（含数据点）${selectedRowKeys.length > 0 ? ` (${selectedRowKeys.length}篇)` : ''}`, disabled: selectedRowKeys.length === 0 },
              { key: 'sel_csv', icon: <FileTextOutlined />, label: `导出选中 CSV${selectedRowKeys.length > 0 ? ` (${selectedRowKeys.length}篇)` : ''}`, disabled: selectedRowKeys.length === 0 },
            ],
            onClick: ({ key }) => {
              const idsParam = selectedRowKeys.map((k) => String(k)).join(',');
              const buildUrl = (extra: Record<string, string>) => {
                const params = new URLSearchParams(extra);
                if (keyword) params.set('keyword', keyword);
                if (disease) params.set('disease', disease);
                if (province) params.set('province', province);
                if (yearStart) params.set('year_start', String(yearStart));
                if (yearEnd) params.set('year_end', String(yearEnd));
                if (journal) params.set('journal', journal);
                if (reviewStatus) params.set('review_status', reviewStatus);
                if (fileFormat) params.set('file_format', fileFormat);
                return params;
              };
              const urls: Record<string, string> = {
                all_csv: buildUrl({}).toString(),
                all_xlsx: buildUrl({ format: 'xlsx' }).toString(),
                all_json_dp: buildUrl({ format: 'json', include_data_points: 'true' }).toString(),
                all_xlsx_dp: buildUrl({ format: 'xlsx', include_data_points: 'true' }).toString(),
                sel_csv: buildUrl({ literature_ids: idsParam }).toString(),
                sel_json_dp: buildUrl({ format: 'json', include_data_points: 'true', literature_ids: idsParam }).toString(),
                sel_xlsx_dp: buildUrl({ format: 'xlsx', include_data_points: 'true', literature_ids: idsParam }).toString(),
              };
              const url = urls[key];
              if (url) window.open(`/api/v1/literatures/export?${url}`);
            },
          }}>
            <Button icon={<ExportOutlined />}>
              导出文献 <ExportOutlined />
            </Button>
          </Dropdown>
          <Button icon={<ImportOutlined />} onClick={() => { setImportFile(null); setImportSkipDuplicates(true); setImportModalOpen(true); }}>
            导入文献
          </Button>
        </Space>
      </Card>

      <Card>
        <Table
          rowKey="id"
          className="literature-table"
          dataSource={items}
          columns={columns}
          loading={loading}
          components={{ header: { cell: ResizableTitle } }}
          onChange={handleTableChange}
          rowSelection={{
            selectedRowKeys,
            onChange: (keys, rows) => {
              setSelectedRowKeys(keys);
              setSelectedRows(rows as Literature[]);
            },
            preserveSelectedRowKeys: true,
          }}
          pagination={{
            current: page,
            total,
            pageSize,
            pageSizeOptions: [10, 20, 50, 100],
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条${selectedRowKeys.length > 0 ? `，已选 ${selectedRowKeys.length} 条` : ''}`,
          }}
          scroll={{ x: 1045, y: 560 }}
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
              {modelOptions.map((opt) => (
                <Select.Option key={opt.value || '__default__'} value={opt.value}>{opt.label}</Select.Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item noStyle dependencies={['model']}>
            {({ getFieldValue }) => {
              const m = getFieldValue('model');
              const desc = modelOptions.find((o) => o.value === m)?.description;
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
                  当前默认：{modelOptions.find((o) => o.value === savedDefault.model)?.label || savedDefault.model || '后端配置'}
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
              const vendor = modelOptions.find((o) => o.value === model)?.vendor || '';
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
              const vendor = modelOptions.find((o) => o.value === model)?.vendor || '';
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

      {/* 从本地文件夹批量导入对话框 */}
      <Modal
        title={<><FolderOpenOutlined /> 从本地文件夹批量导入</>}
        open={folderImportOpen}
        onCancel={() => { setFolderImportOpen(false); setFolderFiles([]); setFolderImportResult(null); }}
        onOk={handleFolderImport}
        confirmLoading={folderImporting}
        okText={folderImporting ? `上传中 (${folderFiles.length} 个文件)...` : '开始导入'}
        okButtonProps={{ disabled: folderFiles.length === 0 }}
        width={680}
      >
        <div style={{ marginBottom: 16 }}>
          <p>选择本地文件夹，批量导入其中的文献文件，自动匹配已有文献或创建新记录。</p>
        </div>

        {!folderImportResult && (
          <>
            <div style={{
              border: '2px dashed #d9d9d9', borderRadius: 8, padding: 32,
              textAlign: 'center', cursor: 'pointer', background: '#fafafa',
              marginBottom: 16,
            }}>
              <input
                type="file"
                {...({ webkitdirectory: '', directory: '' } as React.InputHTMLAttributes<HTMLInputElement>)}
                multiple
                style={{ display: 'none' }}
                id="folder-picker"
                onChange={(e) => {
                  const fileList = e.target.files;
                  if (fileList) {
                    setFolderFiles(Array.from(fileList));
                  }
                }}
              />
              <label htmlFor="folder-picker" style={{ cursor: 'pointer', display: 'block' }}>
                <FolderOpenOutlined style={{ fontSize: 48, color: '#1677ff', marginBottom: 12 }} />
                <div style={{ fontSize: 16, fontWeight: 500, marginBottom: 4 }}>
                  {folderFiles.length > 0
                    ? `已选择 ${folderFiles.length} 个文件`
                    : '点击选择文件夹'}
                </div>
                <div style={{ color: '#999', fontSize: 13 }}>
                  {folderFiles.length > 0
                    ? `共 ${(folderFiles.reduce((s, f) => s + f.size, 0) / 1024 / 1024).toFixed(1)} MB`
                    : '支持 PDF、CAJ、DOCX、TXT 等格式'}
                </div>
              </label>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
              <Switch
                checked={folderImportTriggerExtraction}
                onChange={setFolderImportTriggerExtraction}
                size="small"
              />
              <Text style={{ fontSize: 13 }}>
                对新导入的文献自动触发 AI 提取
              </Text>
            </div>
          </>
        )}

        {folderImportResult && (
          <>
            <div style={{
              padding: '8px 12px', borderRadius: 6, marginBottom: 12,
              background: folderImportResult.failed > 0 ? '#fff2f0' : '#f6ffed',
              border: `1px solid ${folderImportResult.failed > 0 ? '#ffccc7' : '#b7eb8f'}`,
            }}>
              <Text strong>
                关联 {folderImportResult.matched} 篇
                {' | '}新建 {folderImportResult.imported} 篇
                {' | '}跳过 {folderImportResult.skipped} 篇
                {' | '}失败 {folderImportResult.failed} 个
              </Text>
            </div>
            <div style={{ maxHeight: 320, overflow: 'auto' }}>
              <Table
                dataSource={folderImportResult.details}
                columns={[
                  { title: '文件名', dataIndex: 'filename', key: 'filename', width: 200 },
                  { title: '状态', dataIndex: 'status', key: 'status', width: 100, render: (s: string) => {
                    switch(s) {
                      case 'matched': return <Tag color="green">已关联</Tag>;
                      case 'imported': return <Tag color="blue">已新建</Tag>;
                      case 'skipped_has_file': return <Tag color="orange">已跳过</Tag>;
                      default: return <Tag color="red">失败</Tag>;
                    }
                  }},
                  { title: '文献标题', dataIndex: 'title', key: 'title', render: (t: string | undefined) => t || '-' },
                  { title: '错误信息', dataIndex: 'error', key: 'error', width: 150, render: (e: string | undefined) => e || '-' },
                ]}
                rowKey="filename"
                pagination={false}
                size="small"
              />
            </div>
          </>
        )}
      </Modal>

      {/* 文件导入对话框 */}
      <Modal
        title={<><ImportOutlined /> 导入文献及数据点</>}
        open={importModalOpen}
        onCancel={() => { setImportModalOpen(false); setImportFile(null); }}
        onOk={handleImport}
        confirmLoading={importing}
        okText="开始导入"
        okButtonProps={{ disabled: !importFile }}
        width={520}
      >
        <div style={{ marginBottom: 12, color: '#888' }}>
          从 JSON 导出文件导入文献及数据点。导入后数据点保留原有审核状态，可在地图、分析等模块中正常展示。
          <br />
          请使用「导出文献 → 导出 JSON（含数据点）」生成的文件。
        </div>
        <Upload
          beforeUpload={(file) => {
            if (!file.name.toLowerCase().endsWith('.json')) {
              message.error('请上传 JSON 格式文件');
              return Upload.LIST_IGNORE;
            }
            setImportFile(file);
            return false;
          }}
          accept=".json"
          maxCount={1}
          onRemove={() => setImportFile(null)}
          fileList={importFile ? [{ uid: '-1', name: importFile.name, status: 'done' }] : []}
        >
          <Button icon={<UploadOutlined />}>选择 JSON 文件</Button>
        </Upload>
        {importFile && (
          <div style={{ marginTop: 12, padding: '8px 12px', background: '#f6ffed', border: '1px solid #b7eb8f', borderRadius: 6 }}>
            <Text style={{ fontSize: 13 }}>
              已选择文件：{importFile.name}（{(importFile.size / 1024).toFixed(1)} KB）
            </Text>
          </div>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 16, paddingTop: 12, borderTop: '1px solid #f0f0f0' }}>
          <Switch checked={importSkipDuplicates} onChange={setImportSkipDuplicates} size="small" />
          <Text style={{ fontSize: 13 }}>
            {importSkipDuplicates ? '跳过重复文献（按 DOI/标题匹配）' : '更新已有文献的数据'}
          </Text>
        </div>
      </Modal>

      {/* 修改关联文件 —— 替换已有文献关联的本地文档 */}
      <Modal
        title={<>修改关联文件</>}
        open={!!replaceLit}
        onCancel={handleReplaceCancel}
        onOk={handleReplaceFile}
        confirmLoading={replacing}
        okText="确认修改"
        cancelText="取消"
        width={520}
        maskClosable={!replacing}
      >
        {replaceLit && (
          <div style={{ marginBottom: 12, padding: '10px 12px', background: '#f6ffed', border: '1px solid #b7eb8f', borderRadius: 6 }}>
            <Text style={{ fontSize: 13 }}>
              当前文献：<strong>{replaceLit.title}</strong>
              <br />
              原有文档：{replaceLit.file_format ? `${replaceLit.file_format}（${replaceLit.file_path || ''}）` : '无'}
            </Text>
          </div>
        )}
        <Upload
          accept=".pdf,.caj,.epub,.docx,.pptx,.xlsx,.txt,.html,.htm,.doc,.wps,.ps,.md"
          maxCount={1}
          beforeUpload={(file) => { setReplaceFile(file); return false; }}
          onRemove={() => setReplaceFile(null)}
          fileList={replaceFile ? [{ uid: '-1', name: replaceFile.name, status: 'done' }] : []}
          disabled={replacing}
        >
          <Button icon={<PaperClipOutlined />} disabled={replacing}>选择新关联文件</Button>
        </Upload>
        <div style={{ marginTop: 12 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            选择后将替换该文献原有的本地文档文件，支持 PDF/CAJ/EPUB/DOCX/PPTX/XLSX/TXT/HTML 等格式。
          </Text>
        </div>
      </Modal>

      <Modal
        title={batchExtractMode ? (<><RobotOutlined /> 批量选择提取模型</>) : (<><RobotOutlined /> 选择提取模型</>)}
        open={extractModalOpen}
        onCancel={() => setExtractModalOpen(false)}
        onOk={confirmExtract}
        confirmLoading={extracting}
        okText={batchExtractMode ? '开始批量提取' : '开始提取'}
        width={560}
      >
        {batchExtractMode && (
          <div style={{
            marginBottom: 12,
            padding: '10px 12px',
            background: '#e6f4ff',
            border: '1px solid #91caff',
            borderRadius: 6,
          }}>
            <Text strong style={{ color: '#1677ff' }}>
              已选择 {selectedRowKeys.length} 篇文献进行批量重新提取
            </Text>
            {selectedRows.filter((r) => r.extraction_status === 'processing').length > 0 && (
              <div style={{ fontSize: 12, color: '#d46b08', marginTop: 4 }}>
                提示：正在提取中的文献将被自动跳过
              </div>
            )}
          </div>
        )}
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
            const vendor = modelOptions.find((o) => o.value === v)?.vendor || '';
            setExtractBaseUrl(VENDOR_INFO[vendor]?.defaultBaseUrl || '');
          }}
        >
          {modelOptions.map((opt) => (
            <Select.Option key={opt.value || '__default__'} value={opt.value}>{opt.label}</Select.Option>
          ))}
        </Select>
        {extractModel && (() => {
          const desc = modelOptions.find((o) => o.value === extractModel)?.description;
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
          const vendor = modelOptions.find((o) => o.value === extractModel)?.vendor || '';
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
                当前默认：{modelOptions.find((o) => o.value === savedDefault.model)?.label || savedDefault.model || '后端配置'}
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
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8, paddingTop: 8, borderTop: '1px solid #f0f0f0' }}>
          <Switch checked={clearExistingData} onChange={setClearExistingData} size="small" />
          <Text style={{ fontSize: 13 }}>
            {clearExistingData ? '清除并重新提取所有数据（含已审核的）' : '保留已审核通过的数据点，仅覆盖未审核/已驳回的数据'}
          </Text>
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
