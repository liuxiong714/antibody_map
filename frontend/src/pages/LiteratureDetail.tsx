import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Card, Descriptions, Table, Button, Space, Tag, Modal, Input, InputNumber, Checkbox, message, Spin, Select, Row, Col, Tooltip, Switch, Typography, Alert, Popconfirm, DatePicker,
} from 'antd';
import { CheckOutlined, CloseOutlined, ExperimentOutlined, ArrowLeftOutlined, RobotOutlined, MenuFoldOutlined, MenuUnfoldOutlined, UpOutlined, DownOutlined, RightOutlined, LeftOutlined, EditOutlined, SaveOutlined, SyncOutlined, DownloadOutlined, PlusOutlined, HistoryOutlined, ClockCircleOutlined, FileTextOutlined, DeleteOutlined, FilterOutlined, SearchOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import ConfidenceBadge from '../components/ConfidenceBadge';
import StatusBadge from '../components/StatusBadge';
import QualityBadge from '../components/QualityBadge';
import {
  getLiterature, getExtractionResults, getExtractionStatus, getExtractionHistory, deleteExtractionHistory, updateDataPoints, triggerExtraction, updateLiterature, createDataPoint, getSourceText, confirmDataPoints, disputeDataPoints, deleteLiterature, listLiterature,
  exportExtractionCsv, exportTraceabilityHtml, exportExtractionWord,
} from '../services/literature';
import PdfViewer from '../components/PdfViewer';
import FilePreview from '../components/FilePreview';
import { DATA_TYPE_LABEL, DISEASES, PROVINCES, VENDOR_INFO } from '../utils/constants';
import { buildModelOptions, ExtendedModelOption } from '../utils/modelOptions';
import type { Literature, DataPoint, ExtractionStatusWithUsage } from '../types';
import PathogenPanel from '../components/PathogenPanel';
import type { ExtractionHistoryItem } from '../services/literature';
import dayjs from 'dayjs';
import { clearAnalysisApiCache, clearMapApiCache } from '../services/map';
import { usePolling } from '../hooks/usePolling';

const { Text } = Typography;

// 列表页跳转详情页前保存的 sessionStorage key（与 Literature.tsx 保持一致）
const LIST_STATE_KEY = 'literature_list_back_state';

// 从 sessionStorage 解析列表页保存的筛选/排序参数，用于上一篇/下一篇保持与列表一致的上下文
function readSavedListParams(): Record<string, unknown> {
  try {
    const raw = sessionStorage.getItem(LIST_STATE_KEY);
    if (!raw) return {};
    const s = JSON.parse(raw);
    const params: Record<string, unknown> = {};
    if (s.keyword) params.keyword = s.keyword;
    if (s.disease) params.disease = s.disease;
    if (s.province) params.province = s.province;
    if (s.yearStart) params.year_start = s.yearStart;
    if (s.yearEnd) params.year_end = s.yearEnd;
    if (s.journal) params.journal = s.journal;
    if (s.sortBy) params.sort_by = s.sortBy;
    if (s.sortOrder) params.sort_order = s.sortOrder;
    if (s.reviewStatus) params.review_status = s.reviewStatus;
    if (s.extractionStatus) params.extraction_status = s.extractionStatus;
    if (s.fileFormat) params.file_format = s.fileFormat;
    if (s.titleFilter) params.title = s.titleFilter;
    if (s.authorsFilter) params.authors = s.authorsFilter;
    if (s.createdStart) params.created_start = s.createdStart;
    if (s.createdEnd) params.created_end = s.createdEnd;
    if (s.hasAbstract === 'has') params.has_abstract = true;
    if (s.hasAbstract === 'none') params.has_abstract = false;
    if (s.tagFilter) params.tag_id = s.tagFilter;
    return params;
  } catch (err) {
    console.error('[LiteratureDetail] 解析列表状态失败:', err);
    return {};
  }
}

const LiteratureDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [literature, setLiterature] = useState<Literature | null>(null);
  const [dataPoints, setDataPoints] = useState<DataPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [extracting, setExtracting] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  // L3 全量筛选状态：自定义 range / input（Table 原生 filters 自行管理）
  const [yearRange, setYearRange] = useState<[number, number] | null>(null);
  const [popKeyword, setPopKeyword] = useState('');
  const [reviewNote, setReviewNote] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [modalAction, setModalAction] = useState<'approved' | 'rejected'>('approved');
  // F-2：统一轮询 hook 取代手动 intervalRef（组件卸载自动清理）
  // tick 内闭包捕获 id（URL 稳定），所以用 ref cache 最新值就够了
  const metadataSyncTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [extractModalOpen, setExtractModalOpen] = useState(false);
  const [extractModel, setExtractModel] = useState<string | undefined>(undefined);
  const [extractApiKey, setExtractApiKey] = useState('');
  const [extractBaseUrl, setExtractBaseUrl] = useState('');
  // 统一模型候选项（本地模型来自后端 /models，与报告生成等功能保持一致）
  const [modelOptions, setModelOptions] = useState<ExtendedModelOption[]>([]);
  useEffect(() => {
    buildModelOptions().then(setModelOptions);
  }, []);
  // 2026-09-22：彻底禁用 replace 模式，clearExistingData 状态已移除
  // 是否强制跳过 LLM 缓存（重新跑 LLM 获取新鲜结果）
  const [forceRefreshCache, setForceRefreshCache] = useState<boolean>(false);
  // 是否开启模型原生 thinking/推理模式（默认关，抽取任务不需要推理）
  const [enableThinking, setEnableThinking] = useState<boolean>(false);
  // 是否在本次提取完成后显示 token/费用/模型信息
  const [showUsageOnComplete, setShowUsageOnComplete] = useState<boolean>(() => {
    try { return localStorage.getItem('lit_show_usage_on_complete') === '1'; } catch { return false; }
  });
  // 最近一次提取的 token 用量摘要（来自 extraction/status 接口）
  const [lastUsage, setLastUsage] = useState<ExtractionStatusWithUsage | null>(null);

  // 提取历史（内联展示）
  const [historyList, setHistoryList] = useState<ExtractionHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  // 面板大小状态
  const [topHeightPercent, setTopHeightPercent] = useState(30);
  const [leftWidthPercent, setLeftWidthPercent] = useState(55);
  const dragRef = useRef<'vertical' | 'horizontal' | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // 数据点表格滚动区域高度（动态测量，使表头固定、横向滚动条常驻可视区底部）
  const dataTableWrapRef = useRef<HTMLDivElement>(null);
  const [tableScrollY, setTableScrollY] = useState(400);

  // 折叠状态
  const [isTopCollapsed, setIsTopCollapsed] = useState(false);
  const [isLeftCollapsed, setIsLeftCollapsed] = useState(false);
  const [isRightCollapsed, setIsRightCollapsed] = useState(true);

  // 编辑状态
  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState<Record<string, string | number | null>>({});
  const [saving, setSaving] = useState(false);

  // 上一篇 / 下一篇：与文献列表（列表页离开时保存的排序/筛选）保持一致，取当前文献的前后 id
  const [prevId, setPrevId] = useState<string | null>(null);
  const [nextId, setNextId] = useState<string | null>(null);

  // 数据点行内编辑状态
  const [editingRowId, setEditingRowId] = useState<string | null>(null);
  const [editRowData, setEditRowData] = useState<Partial<DataPoint> | null>(null);
  const [editSavingRow, setEditSavingRow] = useState(false);

  // 手动新增数据点状态
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [addForm, setAddForm] = useState<Record<string, unknown>>({ confidence: 'medium', is_grounded: false });
  const [addSaving, setAddSaving] = useState(false);

  // P2：溯源查看弹窗状态
  const [sourceModalOpen, setSourceModalOpen] = useState(false);
  const [sourceText, setSourceText] = useState('');
  const [sourceHighlightStart, setSourceHighlightStart] = useState<number | null>(null);
  const [sourceHighlightEnd, setSourceHighlightEnd] = useState<number | null>(null);
  const [sourceLoading, setSourceLoading] = useState(false);

  // 需求3：新增数据点弹窗拖拽
  const [addModalPos, setAddModalPos] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const modalDragRef = useRef<{ startX: number; startY: number; baseX: number; baseY: number } | null>(null);

  const handleModalDragMouseDown = (e: React.MouseEvent) => {
    modalDragRef.current = { startX: e.clientX, startY: e.clientY, baseX: addModalPos.x, baseY: addModalPos.y };
    e.preventDefault();
  };

  useEffect(() => {
    if (!addModalOpen) return;
    const handleMouseMove = (e: MouseEvent) => {
      if (!modalDragRef.current) return;
      const dx = e.clientX - modalDragRef.current.startX;
      const dy = e.clientY - modalDragRef.current.startY;
      setAddModalPos({ x: modalDragRef.current.baseX + dx, y: modalDragRef.current.baseY + dy });
    };
    const handleMouseUp = () => { modalDragRef.current = null; };
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [addModalOpen]);

  const handleViewSource = async (r: DataPoint) => {
    if (!id) return;
    setSourceModalOpen(true);
    setSourceLoading(true);
    setSourceText('');
    setSourceHighlightStart(null);
    setSourceHighlightEnd(null);
    try {
      const hasRange = r.source_char_start != null && r.source_char_end != null;
      const result = await getSourceText(
        id,
        hasRange ? r.source_char_start! : undefined,
        hasRange ? r.source_char_end! : undefined,
        300,
      );
      if (result.snippet != null) {
        setSourceText(result.snippet);
        setSourceHighlightStart(result.highlight_start ?? null);
        setSourceHighlightEnd(result.highlight_end ?? null);
      } else if (result.full_text != null) {
        setSourceText(result.full_text);
      }
    } catch (e) {
      console.error('获取溯源文本失败:', e);
    } finally {
      setSourceLoading(false);
    }
  };

  const handleStartEdit = () => {
    if (!literature) return;
    setEditForm({
      title: literature.title || '',
      title_en: literature.title_en || '',
      authors: literature.authors || '',
      author_affiliations: literature.author_affiliations || '',
      journal: literature.journal || '',
      pub_year: literature.pub_year ?? null,
      doi: literature.doi || '',
      pmid: literature.pmid || '',
      abstract: literature.abstract || '',
      region: literature.region || '',
      province: literature.province || '',
    });
    setEditing(true);
  };

  const handleCancelEdit = () => {
    setEditing(false);
    setEditForm({});
  };

  // 删除文献（软删除 → 回收站）
  const handleDelete = () => {
    if (!literature) return;
    Modal.confirm({
      title: '确认删除该文献？',
      content: (
        <div>
          <p>删除后该文献将移入回收站，可在回收站中恢复。</p>
          <p style={{ color: '#8c8c8c', marginBottom: 0 }}>《{literature.title || '未命名文献'}》</p>
        </div>
      ),
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await deleteLiterature(id!);
          message.success('已删除到回收站');
          if (nextId) {
            navigate(`/literature/${nextId}`);
          } else if (prevId) {
            navigate(`/literature/${prevId}`);
          } else {
            navigate('/literature');
          }
        } catch (err) {
          console.error('[LiteratureDetail] 删除文献失败:', err);
          message.error('删除失败');
        }
      },
    });
  };

  // 数据点行内编辑
  const handleStartEditRow = (record: DataPoint) => {
    setEditingRowId(record.id);
    setEditRowData({ ...record });
  };

  const handleCancelEditRow = () => {
    setEditingRowId(null);
    setEditRowData(null);
  };

  const handleSaveEditRow = async () => {
    if (!id || !editRowData?.id) return;
    setEditSavingRow(true);
    try {
      const payload: Record<string, unknown> = { id: editRowData.id };
      const fields: (keyof DataPoint)[] = [
        'disease', 'province', 'city', 'data_type', 'value', 'unit',
        'sample_size', 'population', 'age_min', 'age_max', 'collection_year',
        'confidence', 'method', 'assay', 'source_page', 'source_context',
        // P0 新增：精确字符级溯源字段（允许手动修复）
        'source_char_start', 'source_char_end', 'is_grounded',
        // 审核意见
        'review_comment',
      ];
      fields.forEach((f) => {
        if (editRowData[f] !== undefined) {
          payload[f] = editRowData[f];
        }
      });
      await updateDataPoints(id, [payload as any]);
      message.success('数据点已更新');
      setEditingRowId(null);
      setEditRowData(null);
      // 数据点变更影响地图/分析数据，清除相关接口缓存
      clearMapApiCache();
      clearAnalysisApiCache();
      fetchData();
    } catch (err) {
      console.error('[LiteratureDetail] 保存数据点行编辑失败:', err);
      message.error('更新失败');
    } finally {
      setEditSavingRow(false);
    }
  };

  const updateEditField = (field: keyof DataPoint, value: unknown) => {
    setEditRowData((prev) => (prev ? { ...prev, [field]: value } : prev));
  };

  const handleSaveEdit = async () => {
    if (!id) return;
    setSaving(true);
    try {
      const updates: Record<string, unknown> = {};
      Object.entries(editForm).forEach(([k, v]) => {
        if (v !== '' && v !== null && v !== undefined) {
          updates[k] = k === 'pub_year' ? (v ? Number(v) : null) : v;
        }
      });
      await updateLiterature(id, updates);
      message.success('文献信息已更新');
      setEditing(false);
      fetchData();
    } catch (err) {
      console.error('[LiteratureDetail] 保存文献编辑失败:', err);
      message.error('更新失败');
    } finally {
      setSaving(false);
    }
  };

  // 解析 prev/next：复用列表页进入详情前保存的排序/筛选，拉取有序 id 序列，
  // 找到当前文献的前一条 / 后一条。无列表上下文时按默认排序（created desc）拉取。
  const resolvePrevNext = useCallback(async (currentId: string) => {
    try {
      const savedParams = readSavedListParams();
      const PAGE_SIZE = 100;
      const MAX_PAGES = 20; // 安全上限 2000 条
      let items: { id: string }[] = [];
      let foundIdx = -1;
      let total = Infinity;

      // 带列表页筛选/排序逐页拉取，找到当前文献位置
      for (let p = 1; p <= MAX_PAGES && items.length < total; p++) {
        const resp = await listLiterature({ ...savedParams, page: p, page_size: PAGE_SIZE });
        total = resp.total;
        if (resp.items.length === 0) break;
        const idxInPage = resp.items.findIndex((it) => it.id === currentId);
        items = items.concat(resp.items);
        if (idxInPage >= 0) {
          foundIdx = items.length - resp.items.length + idxInPage;
          // 当前文献是本页最后一条且仍有下一页：再拉一页以获取 nextId
          if (idxInPage === resp.items.length - 1 && items.length < total) {
            const next = await listLiterature({ ...savedParams, page: p + 1, page_size: PAGE_SIZE });
            items = items.concat(next.items);
          }
          break;
        }
      }

      // 兜底：带筛选未找到（数据变动/筛选失效）则回退默认排序
      if (foundIdx < 0 && Object.keys(savedParams).length > 0) {
        const resp = await listLiterature({ page: 1, page_size: 100 });
        items = resp.items;
        foundIdx = resp.items.findIndex((it) => it.id === currentId);
      }

      setPrevId(foundIdx > 0 ? items[foundIdx - 1].id : null);
      setNextId(foundIdx >= 0 && foundIdx + 1 < items.length ? items[foundIdx + 1].id : null);
    } catch (err) {
      console.error('[LiteratureDetail] resolvePrevNext failed:', err);
      setPrevId(null);
      setNextId(null);
    }
  }, []);
  const fetchData = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const [lit, ext] = await Promise.all([
        getLiterature(id),
        getExtractionResults(id),
        resolvePrevNext(id),
      ]);
      setLiterature(lit);
      setDataPoints((ext as { data_points?: DataPoint[] })?.data_points || []);
    } catch (err) {
      console.error('[LiteratureDetail] 加载文献详情失败:', err);
      message.error('加载文献详情失败');
    } finally {
      setLoading(false);
    }
  }, [id, resolvePrevNext]);

  // 排查页码丢失问题：记录进入详情页时的来源上下文
  useEffect(() => {
    if (import.meta.env.DEV) console.debug('[文献详情] 详情页挂载', {
      id,
      // 存在备份状态说明是从列表页点击进入（返回列表时应恢复页码）
      hasBackState: sessionStorage.getItem('literature_list_back_state') !== null,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  // 同步数据点中的年份和省份到文献信息
  // 优先级：已审核通过的数据点 > 所有数据点
  const syncMetadataFromDataPoints = useCallback(async (force = false): Promise<Record<string, unknown> | null> => {
    if (!literature || dataPoints.length === 0 || !id) return null;

    const updates: Record<string, unknown> = {};

    // 过滤：优先使用已审核通过的数据点，否则使用所有数据点
    const approvedPoints = dataPoints.filter((dp) => dp.review_status === 'approved');
    const candidatePoints = approvedPoints.length > 0 ? approvedPoints : dataPoints;

    // 同步省份
    if (force || !literature.province) {
      const provinceCounts = new Map<string, number>();
      candidatePoints.forEach((dp) => {
        if (dp.province) {
          provinceCounts.set(dp.province, (provinceCounts.get(dp.province) || 0) + 1);
        }
      });
      if (provinceCounts.size > 0) {
        const [topProvince, count] = Array.from(provinceCounts.entries()).sort((a, b) => b[1] - a[1])[0];
        updates.province = topProvince;
        // 如果有多个省份，同时取第一个省份作为 region
        const uniqueProvinces = Array.from(provinceCounts.keys());
        if (uniqueProvinces.length === 1) {
          updates.region = topProvince;
        }
        if (import.meta.env.DEV) console.debug(`[Sync] 省份: ${topProvince} (${count} 个数据点支持, 共 ${provinceCounts.size} 个不同省份)`);
      }
    }

    // 同步年份
    if (force || !literature.pub_year) {
      const yearCounts = new Map<number, number>();
      candidatePoints.forEach((dp) => {
        if (dp.collection_year) {
          yearCounts.set(dp.collection_year, (yearCounts.get(dp.collection_year) || 0) + 1);
        }
      });
      if (yearCounts.size > 0) {
        // 选择众数年份，若有多个相同数量，选择最近的年份
        const sortedYears = Array.from(yearCounts.entries()).sort((a, b) => {
          if (b[1] !== a[1]) return b[1] - a[1];
          return b[0] - a[0]; // 数量相同则选最近的年份
        });
        const [topYear, count] = sortedYears[0];
        updates.pub_year = topYear;
        if (import.meta.env.DEV) console.debug(`[Sync] 年份: ${topYear} (${count} 个数据点支持, 共 ${yearCounts.size} 个不同年份)`);
      }
    }

    if (Object.keys(updates).length === 0) return null;

    await updateLiterature(id, updates);
    setLiterature((prev) => (prev ? { ...prev, ...updates } : prev));
    return updates;
  }, [literature, dataPoints, id]);

  // 手动触发同步
  const handleSyncFromDataPoints = async () => {
    if (dataPoints.length === 0) {
      message.warning('尚未提取数据点，无法同步');
      return;
    }
    setSyncing(true);
    try {
      const prevProvince = literature?.province;
      const prevYear = literature?.pub_year;
      const result = await syncMetadataFromDataPoints(true);
      if (result) {
        const changed: string[] = [];
        if (result.province && result.province !== prevProvince) changed.push(`省份: ${prevProvince || '空'} → ${result.province}`);
        if (result.pub_year && result.pub_year !== prevYear) changed.push(`年份: ${prevYear || '空'} → ${result.pub_year}`);
        if (changed.length > 0) {
          message.success(`已同步: ${changed.join(', ')}`);
        } else {
          message.info('文献信息已是最新，无需同步');
        }
      } else {
        message.info('数据点中暂无可用的省份或年份信息');
      }
    } catch (err) {
      console.error('[LiteratureDetail] 同步数据点信息失败:', err);
      message.error('同步失败，请重试');
    } finally {
      setSyncing(false);
    }
  };

  // 自动同步：进入详情页后，如果年份或省份为空，则从数据点同步
  useEffect(() => {
    if (!literature || dataPoints.length === 0) return;
    if (literature.pub_year && literature.province) return; // 已有信息则跳过

    syncMetadataFromDataPoints(false).catch(() => {
      // 静默失败
    });
  }, [literature, dataPoints, syncMetadataFromDataPoints]);

  // F-2：统一轮询 hook —— 替换手写 intervalRef，组件卸载自动清理 + 404 容错
  const pollExtraction = useCallback(async () => {
    if (!id) return;
    const fresh = await getLiterature(id);
    setLiterature(fresh);

    if (fresh.extraction_status === 'processing' || fresh.extraction_status === 'queued') {
      return; // continue polling
    }

    // 终态
    if (fresh.extraction_status === 'done') {
      getExtractionResults(id).then((ext) => {
        setDataPoints((ext as { data_points?: DataPoint[] })?.data_points || []);
      }).catch(() => {});
      let usageSuffix = '';
      if (showUsageOnComplete) {
        try {
          const status = await getExtractionStatus(id);
          setLastUsage(status);
          if (status && status.total_tokens > 0) {
            usageSuffix = `，消耗 ${status.total_tokens.toLocaleString()} tokens (${status.llm_model_used || '未知模型'}，约 $${status.llm_cost_usd.toFixed(4)})`;
          }
        } catch (e) {
          console.warn('[LiteratureDetail] 获取 token 用量失败:', e);
        }
      }
      message.success(`提取完成，共提取 ${fresh.extracted_count} 个数据点${usageSuffix}`);
      if (metadataSyncTimeoutRef.current) clearTimeout(metadataSyncTimeoutRef.current);
      metadataSyncTimeoutRef.current = setTimeout(() => {
        syncMetadataFromDataPoints(false).then((updates) => {
          if (updates) {
            const parts: string[] = [];
            if (updates.province) parts.push(`省份=${updates.province}`);
            if (updates.pub_year) parts.push(`年份=${updates.pub_year}`);
            if (parts.length > 0) message.success(`自动同步: ${parts.join(', ')}`);
          }
        }).catch(() => {});
      }, 500);
    } else if (fresh.extraction_status === 'failed') {
      message.error('提取失败，请重试');
    }
  }, [id, showUsageOnComplete, syncMetadataFromDataPoints]);

  const { start: startExtractionPolling, stop: stopExtractionPolling } = usePolling(pollExtraction, {
    intervalMs: 3000,
    maxAttempts: 200,
    shouldStop: () => {
      const st = literature?.extraction_status;
      return st !== 'processing' && st !== 'queued' && st != null;
    },
    onGiveUp: (reason) => {
      if (reason === 'maxAttempts') message.warning('提取轮询超时（10 分钟无响应），请刷新页面查看最新状态');
    },
  });

  const handleExtract = () => {
    setExtractModel(undefined);
    setExtractApiKey('');
    setExtractBaseUrl('');
    setExtractModalOpen(true);
  };

  const doExtract = async () => {
    if (!id) return;
    setExtracting(true);
    setExtractModalOpen(false);
    setLastUsage(null);
    try {
      let model = extractModel;
      let modelConfigId: string | undefined;
      // 远程 API 模型：value 形如 remote:<配置id>，取真实模型名与配置 ID，后端据此读取 API Key/Base URL
      if (model && model.startsWith('remote:')) {
        const remoteOpt = modelOptions.find((o) => o.value === model);
        const rawId = model.substring('remote:'.length);
        modelConfigId = remoteOpt?.model_config_id || rawId;
        model = remoteOpt?.model_name || rawId;
      }
      if (model && model !== '') {
        await triggerExtraction(id, {
          model,
          modelConfigId,
          apiKey: extractApiKey || undefined,
          baseUrl: extractBaseUrl || undefined,
          // clearExistingData 已移除（2026-09-22 彻底禁用 replace 模式，后端 API 也强制 append）
          useCache: !forceRefreshCache,  // 勾选强制刷新时跳过 LLM 缓存
          enableThinking,
        });
      } else {
        await triggerExtraction(id, { model: '', useCache: !forceRefreshCache, enableThinking });
      }
      message.success('AI 提取任务已提交，正在轮询进度...');
      // F-2：统一轮询 hook 启动 —— 先停旧轮询（幂等），再开始新的
      startExtractionPolling();
    } catch (err) {
      console.error('[LiteratureDetail] 提取任务提交失败:', err);
      message.error('提取失败');
    } finally {
      setExtracting(false);
    }
  };

  const confirmExtract = () => {
    // 2026-09-22：彻底禁用 replace 模式，永远走 append，直接执行
    doExtract();
  };

  // 切换"显示提取消耗"开关时持久化到 localStorage
  const toggleShowUsage = (checked: boolean) => {
    setShowUsageOnComplete(checked);
    try { localStorage.setItem('lit_show_usage_on_complete', checked ? '1' : '0'); } catch { /* ignore */ }
  };

  // 加载提取历史（内联展示，随文献 id 变化自动加载）
  const loadExtractionHistory = useCallback(async () => {
    if (!id) return;
    setHistoryLoading(true);
    try {
      const history = await getExtractionHistory(id);
      setHistoryList(history);
    } catch (err) {
      console.error('[LiteratureDetail] 加载提取历史失败:', err);
      message.error('加载提取历史失败');
      setHistoryList([]);
    } finally {
      setHistoryLoading(false);
    }
  }, [id]);

  // 切换文献时自动加载历次提取历史
  useEffect(() => {
    setHistoryList([]);
    loadExtractionHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadExtractionHistory]);

  // 提取历史状态映射
  const HISTORY_STATUS_META: Record<string, { color: string; label: string }> = {
    success: { color: 'green', label: '成功' },
    no_data: { color: 'orange', label: '无数据' },
    failed: { color: 'red', label: '失败' },
  };

  // F-2：组件卸载时清理 metadataSyncTimeoutRef（polling hook 自己有卸载清理，
  // 这里只处理额外的 setTimeout 防抖清理）
  useEffect(() => {
    return () => {
      if (metadataSyncTimeoutRef.current) {
        clearTimeout(metadataSyncTimeoutRef.current);
        metadataSyncTimeoutRef.current = null;
      }
    };
  }, []);

  const handleSingleReview = async (dpId: string, status: 'approved' | 'rejected') => {
    if (!id) return;
    try {
      await updateDataPoints(id, [{ id: dpId, review_status: status }]);
      message.success(status === 'approved' ? '已通过' : '已驳回');
      // 审核状态影响地图/分析数据，清除相关接口缓存
      clearMapApiCache();
      clearAnalysisApiCache();
      fetchData();
    } catch (err) {
      console.error('[LiteratureDetail] 单个审核操作失败:', err);
      message.error('操作失败');
    }
  };

  const handleBatchReview = async () => {
    if (!id || selectedRowKeys.length === 0) return;
    // 驳回必须填写审核意见
    if (modalAction === 'rejected' && !reviewNote.trim()) {
      message.warning('驳回必须填写审核意见');
      return;
    }
    try {
      const ids = selectedRowKeys.map((k) => k as string);
      if (modalAction === 'approved') {
        await confirmDataPoints(id, ids, reviewNote.trim() || undefined);
      } else {
        await disputeDataPoints(id, ids, reviewNote.trim());
      }
      message.success(`已${modalAction === 'approved' ? '通过' : '驳回'} ${selectedRowKeys.length} 个数据点`);
      setSelectedRowKeys([]);
      setModalOpen(false);
      setReviewNote('');
      // 审核状态影响地图/分析数据，清除相关接口缓存
      clearMapApiCache();
      clearAnalysisApiCache();
      fetchData();
    } catch (err) {
      console.error('[LiteratureDetail] 批量审核操作失败:', err);
      message.error('批量操作失败');
    }
  };

  const openBatchModal = (action: 'approved' | 'rejected') => {
    setModalAction(action);
    setReviewNote('');
    setModalOpen(true);
  };

  const isEditing = (record: DataPoint) => editingRowId === record.id;

  // L3：从当前数据自动生成各列 filter options（多选筛选）
  const filterOptions = useMemo(() => {
    const uniq = <T,>(arr: T[], key?: (v: T) => string) => {
      const seen = new Set<string>();
      return arr.filter((v) => {
        const k = key ? key(v) : String(v);
        if (seen.has(k)) return false;
        seen.add(k);
        return true;
      });
    };
    return {
      disease: uniq(dataPoints.map((r) => r.disease).filter(Boolean) as string[])
        .map((v) => ({ text: v, value: v })),
      province: uniq(dataPoints.map((r) => r.province).filter(Boolean) as string[])
        .map((v) => ({ text: v, value: v })),
      data_type: uniq(dataPoints.map((r) => r.data_type).filter(Boolean) as string[])
        .map((v) => ({ text: DATA_TYPE_LABEL[v] || v, value: v })),
      confidence: [
        { text: '高', value: 'high' }, { text: '中', value: 'medium' }, { text: '低', value: 'low' },
      ],
      review_status: [
        { text: '待审', value: 'pending' }, { text: '通过', value: 'approved' }, { text: '驳回', value: 'rejected' },
      ],
      grounded: [
        { text: '已匹配', value: 'yes' }, { text: '未匹配', value: 'no' },
      ],
      quality_grade: uniq(dataPoints.map((r) => r.quality_grade).filter(Boolean) as string[])
        .sort()
        .map((v) => ({ text: v, value: v })),
      model_used: uniq(dataPoints.map((r) => r.model_used).filter(Boolean) as string[])
        .map((v) => ({ text: v.includes(':') ? v.split(':').slice(-1)[0] + ' / ' + v : v, value: v })),
    };
  }, [dataPoints]);

  // L3：手动处理年份 range 和人群关键词（因为 Table 原生 filters 不擅长范围/模糊）
  const filteredDataPoints = useMemo(() => {
    let arr = dataPoints;
    if (yearRange) {
      const [lo, hi] = yearRange;
      arr = arr.filter((r) => {
        const y = r.collection_year;
        if (y == null) return false;
        return y >= lo && y <= hi;
      });
    }
    if (popKeyword.trim()) {
      const kw = popKeyword.trim().toLowerCase();
      arr = arr.filter((r) => (r.population || '').toLowerCase().includes(kw));
    }
    return arr;
  }, [dataPoints, yearRange, popKeyword]);

  const activeFilterCount = useMemo(() => {
    return (yearRange ? 1 : 0) + (popKeyword.trim() ? 1 : 0);
  }, [yearRange, popKeyword]);

  const clearAllFilters = () => {
    setYearRange(null);
    setPopKeyword('');
  };

  const columns: ColumnsType<DataPoint> = [
    {
      title: '疾病', dataIndex: 'disease', key: 'disease', width: 85,
      sorter: (a, b) => (a.disease || '').localeCompare(b.disease || ''),
      filters: filterOptions.disease,
      onFilter: (v, r) => r.disease === v,
      render: (v: string, r: DataPoint) =>
        isEditing(r) ? (
          <Input size="small" value={editRowData?.disease ?? ''}
            onChange={(e) => updateEditField('disease', e.target.value || null)}
            style={{ width: 75 }} />
        ) : (
          <Tooltip title={v} placement="top">
            <span>{v || '-'}</span>
          </Tooltip>
        ),
    },
    {
      title: '地区', key: 'region', width: 110,
      sorter: (a, b) => {
        const ra = [a.province, a.city].filter(Boolean).join(' ') || '';
        const rb = [b.province, b.city].filter(Boolean).join(' ') || '';
        return ra.localeCompare(rb);
      },
      filters: filterOptions.province,
      onFilter: (v, r) => r.province === v,
      render: (_: unknown, r: DataPoint) =>
        isEditing(r) ? (
          <Space size={4}>
            <Input size="small" value={editRowData?.province ?? ''}
              onChange={(e) => updateEditField('province', e.target.value || null)}
              placeholder="省" style={{ width: 46 }} />
            <Input size="small" value={editRowData?.city ?? ''}
              onChange={(e) => updateEditField('city', e.target.value || null)}
              placeholder="市" style={{ width: 46 }} />
          </Space>
        ) : (
          (() => {
            const prov = r.province;
            const city = r.city;
            if (!prov && !city) return '-';
            const label = city ? `${prov ?? ''}·${city}` : (prov || '');
            return (
              <Tooltip title={label} placement="top">
                <span>{label}</span>
              </Tooltip>
            );
          })()
        ),
    },
    {
      title: '年龄段', key: 'age', width: 85,
      sorter: (a, b) => {
        const amin = a.age_min ?? Number.MAX_SAFE_INTEGER;
        const bmin = b.age_min ?? Number.MAX_SAFE_INTEGER;
        if (amin !== bmin) return amin - bmin;
        return (a.age_max ?? Number.MAX_SAFE_INTEGER) - (b.age_max ?? Number.MAX_SAFE_INTEGER);
      },
      render: (_: unknown, r: DataPoint) =>
        isEditing(r) ? (
          <Space size={4}>
            <InputNumber size="small" value={editRowData?.age_min ?? undefined}
              onChange={(v) => updateEditField('age_min', v ?? null)}
              placeholder="最小" style={{ width: 42 }} min={0} max={150} />
            <InputNumber size="small" value={editRowData?.age_max ?? undefined}
              onChange={(v) => updateEditField('age_max', v ?? null)}
              placeholder="最大" style={{ width: 42 }} min={0} max={150} />
          </Space>
        ) : (
          r.age_min != null && r.age_max != null ? `${r.age_min}–${r.age_max}岁` :
          r.age_min != null ? `≥${r.age_min}岁` :
          r.age_max != null ? `≤${r.age_max}岁` : '-'
        ),
    },
    {
      title: '人群', key: 'population', width: 100,
      sorter: (a, b) => (a.population || '').localeCompare(b.population || ''),
      filterDropdown: ({ setSelectedKeys, selectedKeys, confirm, visible }) => (
        <div style={{ padding: 8 }}>
          <Input.Search
            size="small"
            placeholder="输入关键词筛选"
            allowClear
            enterButton={<SearchOutlined />}
            onSearch={(kw) => { setPopKeyword(kw); confirm(); }}
            onChange={(e) => { if (!e.target.value) { setPopKeyword(''); confirm(); } }}
            style={{ width: 180 }}
          />
        </div>
      ),
      filterIcon: <FilterOutlined style={{ color: popKeyword ? '#1677ff' : undefined }} />,
      filterDropdownOpen: false,
      render: (_: unknown, r: DataPoint) => r.population ? (
        <Tooltip title={r.population} placement="top">
          <span>{r.population.length > 10 ? r.population.slice(0, 10) + '…' : r.population}</span>
        </Tooltip>
      ) : '-',
    },
    {
      title: '数据类型', dataIndex: 'data_type', key: 'dt', width: 85,
      sorter: (a, b) => (a.data_type || '').localeCompare(b.data_type || ''),
      filters: filterOptions.data_type,
      onFilter: (v, r) => r.data_type === v,
      render: (v: string, r: DataPoint) =>
        isEditing(r) ? (
          <Select size="small" value={editRowData?.data_type ?? undefined}
            onChange={(val) => updateEditField('data_type', val || null)}
            style={{ width: 75 }} allowClear
            options={Object.entries(DATA_TYPE_LABEL).map(([k, label]) => ({ value: k, label }))} />
        ) : (DATA_TYPE_LABEL[v] || v || '-'),
    },
    {
      title: '数值', key: 'value', width: 110,
      sorter: (a, b) => (a.value ?? Number.MAX_SAFE_INTEGER) - (b.value ?? Number.MAX_SAFE_INTEGER),
      render: (_: unknown, r: DataPoint) =>
        isEditing(r) ? (
          <Space size={4}>
            <InputNumber size="small" value={editRowData?.value ?? undefined}
              onChange={(v) => updateEditField('value', v ?? null)}
              style={{ width: 60 }} step={0.1} />
            <Input size="small" value={editRowData?.unit ?? ''}
              onChange={(e) => updateEditField('unit', e.target.value || null)}
              placeholder="单位" style={{ width: 40 }} />
          </Space>
        ) : r.value != null ? (
          <span>
            <strong style={{ color: r.data_type === 'seroprevalence' ? '#1677ff' : '#52c41a' }}>
              {Number.isInteger(r.value) ? r.value : parseFloat(r.value.toFixed(4))}
            </strong>
            <span style={{ color: '#8c8c8c', marginLeft: 4 }}>{r.unit || ''}</span>
          </span>
        ) : '-',
    },
    {
      title: '冲突', key: 'conflict', width: 72,
      sorter: (a, b) =>
        (a.conflicts?.some((c) => c.conflict) ? 1 : 0) - (b.conflicts?.some((c) => c.conflict) ? 1 : 0),
      render: (_: unknown, r: DataPoint) => {
        const rels = r.conflicts || [];
        const conflicts = rels.filter((c) => c.conflict);
        if (conflicts.length === 0) return <span style={{ color: '#d9d9d9' }}>-</span>;
        const lines = rels.map((c, i) => {
          const diffPct = (c.relative_diff * 100).toFixed(1);
          return (
            <div key={i} style={{ marginBottom: 4 }}>
              <span style={{ color: c.conflict ? '#cf1322' : '#8c8c8c' }}>
                {c.conflict ? '⚠ 差异大' : '· 有对比'}：已有值 {c.value}{c.unit ? ` ${c.unit}` : ''}
                {c.collection_year ? `（${c.collection_year}年）` : ''}，相对差异 {diffPct}%
              </span>
              <div style={{ color: '#bfbfbf', fontSize: 12 }}>《{c.literature_title || '未知文献'}》</div>
            </div>
          );
        });
        return (
          <Tooltip
            title={
              <div style={{ maxWidth: 380 }}>
                <div style={{ marginBottom: 4 }}>同省同病同年已有已审核数据点（仅提示，不阻止审核）：</div>
                {lines}
              </div>
            }
            placement="topLeft"
          >
            <Tag color="red" style={{ margin: 0, cursor: 'help' }}>⚠ {conflicts.length}处</Tag>
          </Tooltip>
        );
      },
    },
    {
      title: '样本量', dataIndex: 'sample_size', key: 'ss', width: 72,
      sorter: (a, b) => (a.sample_size ?? Number.MAX_SAFE_INTEGER) - (b.sample_size ?? Number.MAX_SAFE_INTEGER),
      render: (v: number, r: DataPoint) =>
        isEditing(r) ? (
          <InputNumber size="small" value={editRowData?.sample_size ?? undefined}
            onChange={(val) => updateEditField('sample_size', val ?? null)}
            style={{ width: 62 }} min={0} />
        ) : (v ?? '-'),
    },
    {
      title: '年份', dataIndex: 'collection_year', key: 'cy', width: 72,
      sorter: (a, b) => (a.collection_year ?? Number.MAX_SAFE_INTEGER) - (b.collection_year ?? Number.MAX_SAFE_INTEGER),
      filterDropdown: ({ confirm }) => (
        <div style={{ padding: 8 }}>
          <Space direction="vertical" size={8}>
            <DatePicker.RangePicker
              picker="year"
              size="small"
              style={{ width: 220 }}
              placeholder={['起始年', '结束年']}
              value={yearRange ? [dayjs(yearRange[0]), dayjs(yearRange[1])] : null}
              onChange={(vals) => {
                if (vals && vals[0] && vals[1]) {
                  setYearRange([vals[0].year(), vals[1].year()]);
                } else {
                  setYearRange(null);
                }
              }}
            />
            <Space size={4}>
              <Button type="primary" size="small" onClick={() => confirm()}>确定</Button>
              <Button size="small" onClick={() => { setYearRange(null); confirm(); }}>清除</Button>
            </Space>
          </Space>
        </div>
      ),
      filterIcon: <FilterOutlined style={{ color: yearRange ? '#1677ff' : undefined }} />,
      render: (v: number, r: DataPoint) =>
        isEditing(r) ? (
          <InputNumber size="small" value={editRowData?.collection_year ?? undefined}
            onChange={(val) => updateEditField('collection_year', val ?? null)}
            style={{ width: 62 }} min={1900} max={2100} />
        ) : (v ?? '-'),
    },
    {
      title: '置信度', dataIndex: 'confidence', key: 'cf', width: 70,
      sorter: (a, b) => {
        const order = { high: 3, medium: 2, low: 1 };
        return (order[a.confidence as keyof typeof order] || 0) - (order[b.confidence as keyof typeof order] || 0);
      },
      filters: filterOptions.confidence,
      onFilter: (v, r) => r.confidence === v,
      render: (v: string, r: DataPoint) =>
        isEditing(r) ? (
          <Select size="small" value={editRowData?.confidence ?? undefined}
            onChange={(val) => updateEditField('confidence', val || null)}
            style={{ width: 60 }} allowClear
            options={[
              { value: 'high', label: '高' },
              { value: 'medium', label: '中' },
              { value: 'low', label: '低' },
            ]} />
        ) : (<ConfidenceBadge confidence={v} />),
    },
    {
      title: '溯源', key: 'grounded', width: 68,
      sorter: (a, b) => Number(b.is_grounded) - Number(a.is_grounded),
      filters: filterOptions.grounded,
      onFilter: (v, r) => (v === 'yes' ? r.is_grounded : !r.is_grounded),
      render: (_: unknown, r: DataPoint) => {
        if (r.is_grounded) {
          const extra = r.source_char_start != null && r.source_char_end != null
            ? ` [${r.source_char_start},${r.source_char_end})`
            : '';
          return (
            <Tooltip title={`原文已匹配${extra}`} placement="top">
              <Tag color="green" style={{ margin: 0 }}>✓</Tag>
            </Tooltip>
          );
        }
        return (
          <Tooltip title="LLM 提供的原文依据在整篇文档中未找到对应片段，疑似幻觉" placement="topLeft">
            <Tag color="default" style={{ margin: 0, opacity: 0.55 }}>未匹配</Tag>
          </Tooltip>
        );
      },
    },
    {
      title: '原文依据', key: 'source', width: 150,
      render: (_: unknown, r: DataPoint) => {
        if (isEditing(r)) {
          return (
            <Space size={4} style={{ width: 140 }} direction="vertical">
              <Space size={4}>
                <InputNumber size="small" value={editRowData?.source_page ?? undefined}
                  onChange={(v) => updateEditField('source_page', v ?? null)}
                  placeholder="页" style={{ width: 50 }} min={1} />
                <Input size="small" value={editRowData?.source_context ?? ''}
                  onChange={(e) => updateEditField('source_context', e.target.value || null)}
                  placeholder="上下文" style={{ width: 80 }} />
              </Space>
              <Space size={4}>
                <InputNumber size="small" value={editRowData?.source_char_start ?? undefined}
                  onChange={(v) => updateEditField('source_char_start', v ?? null)}
                  placeholder="起" style={{ width: 60 }} min={0} />
                <InputNumber size="small" value={editRowData?.source_char_end ?? undefined}
                  onChange={(v) => updateEditField('source_char_end', v ?? null)}
                  placeholder="止" style={{ width: 60 }} min={0} />
              </Space>
              <Checkbox
                checked={!!editRowData?.is_grounded}
                onChange={(e) => updateEditField('is_grounded', e.target.checked)}
              >
                已匹配
              </Checkbox>
            </Space>
          );
        }
        const context = r.source_context;
        const page = r.source_page;
        const hasInterval = r.source_char_start != null && r.source_char_end != null;
        if (!context && !page && !hasInterval) return '-';

        const displayText = page
          ? `第${page}页`
          : (hasInterval
              ? `[${r.source_char_start},${r.source_char_end})`
              : (context ? context.substring(0, 16) + '…' : '-'));

        const tooltipLines: string[] = [];
        if (page) tooltipLines.push(`页码：第 ${page} 页`);
        if (hasInterval) tooltipLines.push(`字符区间：[${r.source_char_start}, ${r.source_char_end})`);
        if (context) tooltipLines.push(context);
        const tooltip = tooltipLines.length > 0 ? tooltipLines.join('\n') : undefined;

        return (
          <Tooltip title={tooltip || '点击查看原文'} placement="topLeft">
            <span
              style={{ cursor: 'pointer', color: r.is_grounded ? undefined : '#b82601' }}
              onClick={() => handleViewSource(r)}
            >
              {displayText}
            </span>
          </Tooltip>
        );
      },
    },
    {
      title: '质量', key: 'quality', width: 80,
      sorter: (a, b) => (a.quality_score ?? -1) - (b.quality_score ?? -1),
      filters: filterOptions.quality_grade,
      onFilter: (v, r) => r.quality_grade === v,
      render: (_: unknown, r: DataPoint) => (
        <QualityBadge
          qualityScore={r.quality_score}
          qualityGrade={r.quality_grade}
          estimateGrade={r.estimate_grade}
          breakdown={r.quality_breakdown}
        />
      ),
    },
    {
      title: '状态', key: 'status', width: 72,
      sorter: (a, b) => {
        const order: Record<string, number> = { approved: 3, pending: 2, rejected: 1 };
        return (order[a.review_status] || 0) - (order[b.review_status] || 0);
      },
      filters: filterOptions.review_status,
      onFilter: (v, r) => r.review_status === v,
      render: (_: unknown, r: DataPoint) => (
        <Tag color={r.review_status === 'approved' ? 'green' : r.review_status === 'rejected' ? 'red' : 'default'} style={{ margin: 0 }}>
          {r.review_status === 'approved' ? '通过' : r.review_status === 'rejected' ? '驳回' : '待审'}
        </Tag>
      ),
    },
    {
      title: '审核人', key: 'reviewer', width: 75,
      sorter: (a, b) => (a.reviewer_name || a.reviewer_id || '').localeCompare(b.reviewer_name || b.reviewer_id || ''),
      render: (_: unknown, r: DataPoint) => (r.reviewer_name || r.reviewer_id || <span style={{ color: '#d9d9d9' }}>-</span>),
    },
    {
      title: '审核时间', key: 'reviewed_at', width: 120,
      sorter: (a, b) => (a.reviewed_at || '').localeCompare(b.reviewed_at || ''),
      render: (_: unknown, r: DataPoint) => (r.reviewed_at ? dayjs(r.reviewed_at).format('MM-DD HH:mm') : <span style={{ color: '#d9d9d9' }}>-</span>),
    },
    {
      title: '审核意见', key: 'review_comment', width: 140,
      render: (_: unknown, r: DataPoint) =>
        isEditing(r) ? (
          <Input.TextArea size="small" value={editRowData?.review_comment ?? ''}
            onChange={(e) => updateEditField('review_comment', e.target.value || null)}
            autoSize={{ minRows: 1, maxRows: 4 }} placeholder="审核意见" />
        ) : (
          <Tooltip title={r.review_comment || '暂无'} placement="topLeft">
            <span style={{ color: r.review_comment ? undefined : '#bbb' }}>
              {(r.review_comment || '').length > 16 ? `${(r.review_comment || '').slice(0, 16)}…` : (r.review_comment || '-')}
            </span>
          </Tooltip>
        ),
    },
    {
      title: '操作', key: 'actions', width: 200,
      render: (_: unknown, r: DataPoint) =>
        isEditing(r) ? (
          <Space size="small">
            <Button size="small" type="primary" icon={<SaveOutlined />} loading={editSavingRow} onClick={handleSaveEditRow}>保存</Button>
            <Button size="small" onClick={handleCancelEditRow}>取消</Button>
          </Space>
        ) : (
          <Space size="small">
            <Button size="small" icon={<EditOutlined />} onClick={() => handleStartEditRow(r)}>编辑</Button>
            <Button size="small" type="primary" icon={<CheckOutlined />}
              disabled={r.review_status === 'approved'}
              onClick={() => handleSingleReview(r.id, 'approved')} />
            <Button size="small" danger icon={<CloseOutlined />}
              disabled={r.review_status === 'rejected'}
              onClick={() => handleSingleReview(r.id, 'rejected')} />
          </Space>
        ),
    },
    // F21：提取批次溯源
    {
      title: '提取模型/时间',
      key: 'provenance',
      width: 170,
      sorter: (a, b) => {
        const ma = (a.model_used || '').localeCompare(b.model_used || '');
        if (ma !== 0) return ma;
        return (a.created_at || '').localeCompare(b.created_at || '');
      },
      filters: filterOptions.model_used,
      onFilter: (v, r) => r.model_used === v,
      render: (_: unknown, r: DataPoint) => (
        <div style={{ fontSize: 12, lineHeight: 1.5 }}>
          <Tag color={r.model_used ? 'blue' : 'default'} style={{ marginBottom: 2, marginRight: 0 }}>
            {r.model_used
              ? (() => {
                  const parts = r.model_used.split(':');
                  return parts.length > 2 ? parts.slice(1).join(':') : r.model_used;
                })()
              : '未记录'}
          </Tag>
          <div style={{ color: '#8c8c8c', fontSize: 11 }}>
            {r.created_at
              ? dayjs(r.created_at).format('MM-DD HH:mm')
              : '-'}
          </div>
        </div>
      ),
    },
  ];

  // 拖拽调整面板大小
  const handleDragStart = useCallback((direction: 'vertical' | 'horizontal') => (e: React.MouseEvent) => {
    e.preventDefault();
    dragRef.current = direction;
    document.body.style.cursor = direction === 'vertical' ? 'row-resize' : 'col-resize';
    document.body.style.userSelect = 'none';
  }, []);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!dragRef.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();

      if (dragRef.current === 'vertical') {
        const ratio = ((e.clientY - rect.top) / rect.height) * 100;
        setTopHeightPercent(Math.min(65, Math.max(15, ratio)));
      } else {
        const ratio = ((e.clientX - rect.left) / rect.width) * 100;
        setLeftWidthPercent(Math.min(80, Math.max(25, ratio)));
      }
    };

    const handleMouseUp = () => {
      if (dragRef.current) {
        dragRef.current = null;
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
      }
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, []);

  // 数据点表格：动态测量容器高度，设置 Table scroll.y 使表头固定、横向滚动条常驻
  useEffect(() => {
    const el = dataTableWrapRef.current;
    if (!el) return;
    const update = () => {
      // 容器高度 - 表头(~48px) - 分页栏(~56px) - 边框余量
      const h = el.clientHeight - 110;
      setTableScrollY(Math.max(160, h));
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    window.addEventListener('resize', update);
    return () => {
      ro.disconnect();
      window.removeEventListener('resize', update);
    };
  }, []);

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />;

  return (
    <>
      <Button icon={<ArrowLeftOutlined />} onClick={() => {
        if (import.meta.env.DEV) console.debug('[文献详情] 点击返回列表', {
          id,
          hasBackState: sessionStorage.getItem('literature_list_back_state') !== null,
        });
        navigate('/literature');
      }} style={{ marginBottom: 12 }}>
        返回列表
      </Button>

      {/* 可拖拽调整的整体容器 */}
      <div
        ref={containerRef}
        style={{
          display: 'flex',
          flexDirection: 'column',
          height: 'calc(100vh - 90px)',
          minHeight: 500,
        }}
      >
        {/* ===== 上方：文献信息卡片 ===== */}
        {isTopCollapsed ? (
          /* 折叠态：仅显示标题栏 */
          <div
            style={{
              flexShrink: 0,
              background: '#fff',
              border: '1px solid #e8e8e8',
              borderRadius: 6,
              padding: '6px 16px',
              marginBottom: 4,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              cursor: 'pointer',
            }}
            onClick={() => setIsTopCollapsed(false)}
          >
            <span style={{ fontWeight: 600, fontSize: 14 }}>文献详情</span>
            <DownOutlined style={{ color: '#888' }} />
          </div>
        ) : (
          <>
            <div style={{ flex: `0 0 ${topHeightPercent}%`, overflow: 'hidden', minHeight: 0, marginBottom: 0, transition: 'flex 0.25s' }}>
              <Card
                style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
                styles={{ body: { flex: 1, overflow: 'auto', minHeight: 0 } }}
                title={
                  <Space align="start">
                    <span style={{ cursor: 'pointer', flexShrink: 0 }} onClick={() => setIsTopCollapsed(true)}>
                      <UpOutlined style={{ marginRight: 4, color: '#888' }} />
                    </span>
                    <span style={{ whiteSpace: 'normal', wordBreak: 'break-word', lineHeight: 1.5 }}>
                      {editing ? '编辑文献信息' : (literature?.title || '文献详情')}
                    </span>
                  </Space>
                }
                extra={
                  editing ? (
                    <Space>
                      <Button size="small" onClick={handleCancelEdit}>取消</Button>
                      <Button size="small" type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSaveEdit}>保存</Button>
                    </Space>
                  ) : (
                    <Space>
                      <Button
                        size="small"
                        icon={<LeftOutlined />}
                        disabled={!prevId}
                        onClick={() => prevId && navigate(`/literature/${prevId}`)}
                      >上一篇</Button>
                      <Button
                        size="small"
                        icon={<RightOutlined />}
                        disabled={!nextId}
                        onClick={() => nextId && navigate(`/literature/${nextId}`)}
                      >下一篇</Button>
                      <Button size="small" icon={<EditOutlined />} onClick={handleStartEdit}>编辑</Button>
                      <Button size="small" danger icon={<DeleteOutlined />} onClick={handleDelete}>删除</Button>
                    </Space>
                  )
                }
              >
                {editing ? (
                  <Row gutter={[16, 12]}>
                    <Col span={12}>
                      <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>标题</div>
                      <Input value={String(editForm.title ?? '')} onChange={(e) => setEditForm((f) => ({ ...f, title: e.target.value }))} />
                    </Col>
                    <Col span={12}>
                      <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>英文标题</div>
                      <Input value={String(editForm.title_en ?? '')} onChange={(e) => setEditForm((f) => ({ ...f, title_en: e.target.value }))} />
                    </Col>
                    <Col span={12}>
                      <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>作者</div>
                      <Input value={String(editForm.authors ?? '')} onChange={(e) => setEditForm((f) => ({ ...f, authors: e.target.value }))} />
                    </Col>
                    <Col span={12}>
                      <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>作者单位</div>
                      <Input value={String(editForm.author_affiliations ?? '')} onChange={(e) => setEditForm((f) => ({ ...f, author_affiliations: e.target.value }))} />
                    </Col>
                    <Col span={12}>
                      <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>期刊</div>
                      <Input value={String(editForm.journal ?? '')} onChange={(e) => setEditForm((f) => ({ ...f, journal: e.target.value }))} />
                    </Col>
                    <Col span={6}>
                      <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>年份</div>
                      <Input value={editForm.pub_year != null ? String(editForm.pub_year) : ''} onChange={(e) => setEditForm((f) => ({ ...f, pub_year: e.target.value }))} />
                    </Col>
                    <Col span={6}>
                      <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>DOI</div>
                      <Input value={String(editForm.doi ?? '')} onChange={(e) => setEditForm((f) => ({ ...f, doi: e.target.value }))} />
                    </Col>
                    <Col span={6}>
                      <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>PMID</div>
                      <Input value={String(editForm.pmid ?? '')} onChange={(e) => setEditForm((f) => ({ ...f, pmid: e.target.value }))} />
                    </Col>
                    <Col span={6}>
                      <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>省份</div>
                      <Input value={String(editForm.province ?? '')} onChange={(e) => setEditForm((f) => ({ ...f, province: e.target.value }))} />
                    </Col>
                    <Col span={24}>
                      <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>摘要</div>
                      <Input.TextArea rows={3} value={String(editForm.abstract ?? '')} onChange={(e) => setEditForm((f) => ({ ...f, abstract: e.target.value }))} />
                    </Col>
                  </Row>
                ) : (
                  <>
                    <Descriptions column={2} size="small">
                      <Descriptions.Item label="作者">{literature?.authors || '-'}</Descriptions.Item>
                      <Descriptions.Item label="作者单位">{literature?.author_affiliations || '-'}</Descriptions.Item>
                      <Descriptions.Item label="期刊">{literature?.journal || '-'}</Descriptions.Item>
                      <Descriptions.Item label="年份">{literature?.pub_year || '-'}</Descriptions.Item>
                      <Descriptions.Item label="DOI">{literature?.doi || '-'}</Descriptions.Item>
                      <Descriptions.Item label="省份">{literature?.province || '-'}</Descriptions.Item>
                      <Descriptions.Item label="提取状态">
                        <StatusBadge status={literature?.extraction_status || 'pending'} />
                      </Descriptions.Item>
                      <Descriptions.Item label="审核进度">
                        {literature?.approved_count || 0} / {literature?.extracted_count || 0} 已通过
                      </Descriptions.Item>
                      <Descriptions.Item label="提取模型">
                        {literature?.llm_model_used || '-'}
                      </Descriptions.Item>
                      <Descriptions.Item label="Token 用量">
                        {literature && (literature.total_tokens ?? 0) > 0 ? (
                          <Tooltip title={
                            `输入: ${literature.prompt_tokens ?? 0} / 输出: ${literature.completion_tokens ?? 0} / 调用次数: ${literature.llm_call_count ?? 0}` +
                            (literature.llm_usage_detail
                              ? '\n按模型明细:\n' + Object.entries(literature.llm_usage_detail).map(([m, u]) => `  ${m}: ${u.total_tokens} tokens (${u.call_count}次)`).join('\n')
                              : '')
                          }>
                            <Tag color="blue">{(literature.total_tokens ?? 0).toLocaleString()} tokens</Tag>
                          </Tooltip>
                        ) : '-'}
                      </Descriptions.Item>
                      <Descriptions.Item label="估算费用">
                        {literature && Number(literature.llm_cost_usd ?? 0) > 0 ? (
                          <Tag color="gold">${Number(literature.llm_cost_usd).toFixed(4)}</Tag>
                        ) : '-'}
                      </Descriptions.Item>
                    </Descriptions>
                    {literature?.abstract && (
                      <div style={{ marginTop: 12 }}>
                        <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>摘要</div>
                        <p style={{ color: '#666', margin: 0, lineHeight: 1.8 }}>{literature.abstract}</p>
                      </div>
                    )}
                    {literature && !literature.file_path && literature.abstract && (
                      <Alert
                        type="info"
                        showIcon
                        style={{ marginTop: 12 }}
                        message="当前仅基于摘要提取"
                        description="该文献暂无关联 PDF，当前基于摘要提取数据。关联 PDF 后可重新提取，获得更完整的全文数据。"
                      />
                    )}
                    <Space style={{ marginTop: 12 }}>
                      <Button icon={<ExperimentOutlined />} onClick={handleExtract} loading={extracting}>
                        {dataPoints.length > 0 || historyList.length > 0 ? '再次 AI 提取' : 'AI 提取'}
                      </Button>
                      <Tooltip title="从已提取的数据点中同步年份和省份信息">
                        <Button
                          icon={<SyncOutlined spin={syncing} />}
                          onClick={handleSyncFromDataPoints}
                          loading={syncing}
                          disabled={dataPoints.length === 0}
                        >
                          同步信息
                        </Button>
                      </Tooltip>
                    </Space>

                    {/* 历次 AI 提取历史（内联展示） */}
                    <div style={{ marginTop: 16 }}>
                      <div style={{ marginBottom: 8, fontSize: 13, fontWeight: 600 }}>
                        <HistoryOutlined style={{ marginRight: 6 }} />历次 AI 提取历史
                      </div>
                      <Spin spinning={historyLoading}>
                        {historyList.length === 0 && !historyLoading ? (
                          <div style={{ padding: '20px 0', color: '#999', fontSize: 13 }}>
                            <ClockCircleOutlined style={{ marginRight: 6 }} />暂无提取历史记录
                          </div>
                        ) : (
                          <Table
                            rowKey="id"
                            dataSource={historyList}
                            pagination={false}
                            size="small"
                            scroll={{ x: 900 }}
                            columns={[
                              {
                                title: '提取时间',
                                dataIndex: 'extracted_at',
                                key: 'time',
                                width: 160,
                                render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm:ss'),
                              },
                              {
                                title: '使用模型',
                                dataIndex: 'model',
                                key: 'model',
                                width: 160,
                                render: (v: string | null) => v || '-',
                              },
                              {
                                title: '状态',
                                dataIndex: 'status',
                                key: 'status',
                                width: 100,
                                render: (s: string) => {
                                  const meta = HISTORY_STATUS_META[s] || { color: 'default', label: s };
                                  return <Tag color={meta.color}>{meta.label}</Tag>;
                                },
                              },
                              {
                                title: '数据点数',
                                dataIndex: 'data_point_count',
                                key: 'count',
                                width: 80,
                                render: (v: number) => v || 0,
                              },
                              {
                                title: 'Token 用量',
                                key: 'tokens',
                                width: 120,
                                render: (_: unknown, r: ExtractionHistoryItem) =>
                                  r.total_tokens > 0
                                    ? <Tag color="blue">{r.total_tokens.toLocaleString()} tokens</Tag>
                                    : '-',
                              },
                              {
                                title: '调用次数',
                                dataIndex: 'llm_call_count',
                                key: 'calls',
                                width: 80,
                                render: (v: number) => v || 0,
                              },
                              {
                                title: '耗时',
                                key: 'duration',
                                width: 90,
                                render: (_: unknown, r: ExtractionHistoryItem) => {
                                  if (!r.duration_seconds || r.duration_seconds <= 0) return '-';
                                  const s = r.duration_seconds;
                                  if (s < 60) return <span>{s.toFixed(1)}s</span>;
                                  if (s < 3600) return <span>{(s / 60).toFixed(1)}min</span>;
                                  return <span>{(s / 3600).toFixed(2)}h</span>;
                                },
                              },
                              {
                                title: '费用',
                                key: 'cost',
                                width: 100,
                                render: (_: unknown, r: ExtractionHistoryItem) =>
                                  r.llm_cost_usd > 0
                                    ? <Tag color="gold">${r.llm_cost_usd.toFixed(4)}</Tag>
                                    : '-',
                              },
                              {
                                title: '错误分类',
                                key: 'err_category',
                                width: 160,
                                render: (_: unknown, r: ExtractionHistoryItem) => {
                                  const m = r.error_message?.match(/^\[([^\]]+)\]/);
                                  if (!m) return r.status === 'failed' ? <Tag color="red">未知错误</Tag> : '-';
                                  const code = m[1];
                                  const COLOR: Record<string, string> = {
                                    ollama_unreachable: 'volcano',
                                    connection_error: 'orange',
                                    api_key_invalid: 'red', api_key_expired: 'red',
                                    llm_timeout: 'gold', llm_parse_error: 'purple',
                                    schema_validation: 'geekblue', pdf_parse_error: 'cyan',
                                  };
                                  const LABEL: Record<string, string> = {
                                    ollama_unreachable: 'Ollama 连不上',
                                    connection_error: '网络连接失败',
                                    api_key_invalid: 'API Key 无效',
                                    api_key_expired: 'API Key 过期',
                                    llm_timeout: 'LLM 超时',
                                    llm_parse_error: 'LLM 响应解析失败',
                                    schema_validation: 'Schema 校验未通过',
                                    pdf_parse_error: 'PDF 解析失败',
                                  };
                                  return <Tag color={COLOR[code] || 'default'}>{LABEL[code] || code}</Tag>;
                                },
                              },
                              {
                                title: '错误信息',
                                dataIndex: 'error_message',
                                key: 'error',
                                render: (v: string | null) =>
                                  v ? <Tooltip title={v}><Tag color="red" style={{ maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis' }}>{v}</Tag></Tooltip> : '-',
                              },
                              {
                                title: '操作',
                                key: 'action',
                                width: 150,
                                render: (_: unknown, r: ExtractionHistoryItem) => {
                                  const isAdmin = localStorage.getItem('is_admin') === 'true';
                                  return (
                                    <Space size={4}>
                                      <Button
                                        type="link"
                                        size="small"
                                        onClick={() => {
                                          if (!id) return;
                                          // 点击历史记录，使用相同模型重新提取
                                          if (r.model) {
                                            setExtractModel(r.model);
                                            // 自动根据模型匹配默认 baseUrl
                                            const vendor = modelOptions.find((o) => o.value === r.model)?.vendor || '';
                                            setExtractBaseUrl(VENDOR_INFO[vendor]?.defaultBaseUrl || '');
                                          } else {
                                            setExtractModel(undefined);
                                            setExtractBaseUrl('');
                                          }
                                          setExtractApiKey('');
                                          setExtractModalOpen(true);
                                        }}
                                      >
                                        重新提取
                                      </Button>
                                      {isAdmin && (
                                        <Popconfirm
                                          title="删除该提取历史？"
                                          description={
                                            <>
                                              历史记录 <b>{r.model || '(未记录)'}</b> ({r.status}) 将被永久删除。<br />
                                              关联的数据点 <b>不会删除</b>，仅解除追溯关联。
                                            </>
                                          }
                                          okText="删除"
                                          okButtonProps={{ danger: true }}
                                          cancelText="取消"
                                          onConfirm={async () => {
                                            try {
                                              await deleteExtractionHistory(r.id);
                                              message.success('提取历史已删除');
                                              loadExtractionHistory();
                                            } catch {
                                              message.error('删除失败');
                                            }
                                          }}
                                        >
                                          <Button type="link" size="small" danger icon={<DeleteOutlined />} />
                                        </Popconfirm>
                                      )}
                                    </Space>
                                  );
                                },
                              },
                            ]}
                          />
                        )}
                      </Spin>
                    </div>
                  </>
                )}
              </Card>
            </div>

            {/* 水平拖拽手柄 */}
            <div
              onMouseDown={handleDragStart('vertical')}
              style={{
                height: 6,
                cursor: 'row-resize',
                background: 'linear-gradient(to bottom, #d9d9d9, #bfbfbf, #d9d9d9)',
                flexShrink: 0,
                borderRadius: '0 0 2px 2px',
                margin: '0 0',
                transition: 'background 0.15s',
              }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = '#1677ff'; }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = 'linear-gradient(to bottom, #d9d9d9, #bfbfbf, #d9d9d9)'; }}
            />
          </>
        )}

        {/* ===== 下方：数据点 + PDF 预览 分栏 ===== */}
        <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
          {/* 左侧：数据点表格 */}
          {isLeftCollapsed ? (
            /* 折叠态：左侧竖条，内容向左贴边 */
            <div
              style={{
                flexShrink: 0,
                width: 32,
                background: '#fafafa',
                border: '1px solid #e8e8e8',
                borderLeft: 'none',
                borderRadius: '0 6px 6px 0',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer',
                gap: 8,
              }}
              onClick={() => setIsLeftCollapsed(false)}
              title="展开数据点面板"
            >
              <RightOutlined style={{ fontSize: 12, color: '#888' }} />
              <span
                style={{
                  writingMode: 'vertical-rl',
                  fontSize: 13,
                  fontWeight: 600,
                  color: '#666',
                  letterSpacing: 2,
                }}
              >
                数据点
              </span>
            </div>
          ) : (
            <>
              <div style={{ flex: isRightCollapsed ? '1 1 0%' : `0 0 ${leftWidthPercent}%`, minWidth: 0, display: 'flex', flexDirection: 'column', transition: 'flex 0.25s' }}>
                <Card
                  title={
                    <Space>
                      <MenuFoldOutlined
                        style={{ cursor: 'pointer', color: '#888' }}
                        onClick={() => setIsLeftCollapsed(true)}
                      />
                      <span>{`数据点（${dataPoints.length}）`}</span>
                    </Space>
                  }
                  extra={
                    <Space>
                      <Button
                        icon={<PlusOutlined />}
                        onClick={() => {
                          setAddForm({ confidence: 'medium', is_grounded: false });
                          setAddModalPos({ x: 0, y: 0 });
                          setAddModalOpen(true);
                        }}
                      >
                        新增数据点
                      </Button>
                      <Button
                        icon={<DownloadOutlined />}
                        onClick={async () => {
                          const hide = message.loading('正在生成 CSV...', 0);
                          try {
                            await exportExtractionCsv(id!);
                            message.success('CSV 已下载');
                          } catch (e: any) {
                            message.error(e?.response?.status === 401 ? '登录已过期，请重新登录' : 'CSV 导出失败');
                          } finally {
                            hide();
                          }
                        }}
                        disabled={dataPoints.length === 0}
                      >
                        导出 CSV
                      </Button>
                      <Button
                        icon={<DownloadOutlined />}
                        onClick={async () => {
                          const hide = message.loading('正在生成溯源 HTML...', 0);
                          try {
                            await exportTraceabilityHtml(id!);
                            message.success('溯源 HTML 已下载');
                          } catch (e: any) {
                            message.error(e?.response?.status === 401 ? '登录已过期，请重新登录' : '溯源 HTML 导出失败');
                          } finally {
                            hide();
                          }
                        }}
                        disabled={dataPoints.length === 0}
                      >
                        溯源 HTML
                      </Button>
                      <Button
                        icon={<FileTextOutlined />}
                        onClick={async () => {
                          const hide = message.loading('正在生成 Word 报告...', 0);
                          try {
                            await exportExtractionWord(id!);
                            message.success('Word 报告已下载');
                          } catch (e: any) {
                            message.error(e?.response?.status === 401 ? '登录已过期，请重新登录' : 'Word 导出失败');
                          } finally {
                            hide();
                          }
                        }}
                        disabled={dataPoints.length === 0}
                      >
                        导出 Word
                      </Button>
                      <Button
                        type="primary"
                        icon={<CheckOutlined />}
                        disabled={selectedRowKeys.length === 0}
                        onClick={() => openBatchModal('approved')}
                      >
                        批量通过
                      </Button>
                      <Button
                        danger
                        icon={<CloseOutlined />}
                        disabled={selectedRowKeys.length === 0}
                        onClick={() => openBatchModal('rejected')}
                      >
                        批量驳回
                      </Button>
                      {activeFilterCount > 0 && (
                        <Button
                          icon={<FilterOutlined />}
                          onClick={clearAllFilters}
                        >
                          清空筛选（{activeFilterCount}）
                        </Button>
                      )}
                    </Space>
                  }
                  styles={{ body: { flex: 1, overflow: 'auto', padding: 0, minHeight: 0 } }}
                  style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}
                >
                  <div ref={dataTableWrapRef} style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
                  <Table
                    rowKey="id"
                    dataSource={filteredDataPoints}
                    columns={columns}
                    showSorterTooltip={{ title: '点击排序' }}
                    scroll={{ x: 2050, y: tableScrollY }}
                    size="middle"
                    rowClassName={(r: DataPoint) => {
                      if (r.confidence === 'low') return 'low-confidence-row';
                      if (!r.is_grounded) return 'ungrounded-row';
                      return '';
                    }}
                    rowSelection={{
                      selectedRowKeys,
                      onChange: (keys) => setSelectedRowKeys(keys),
                      // F-4：跨页保留选中——翻页后之前勾的还在，批量审核不受分页影响
                      preserveSelectedRowKeys: true,
                      getCheckboxProps: (r: DataPoint) => ({
                        disabled: isEditing(r),
                      }),
                    }}
                    pagination={{
                      pageSize: 50,
                      showSizeChanger: true,
                      pageSizeOptions: ['20', '50', '100'],
                      showTotal: (total, range) => `${range[0]}-${range[1]} / ${total}`,
                    }}
                  />
                  </div>
                </Card>
                <PathogenPanel literatureId={id || ''} />
              </div>

              {/* 垂直拖拽手柄（仅当右侧未折叠时显示） */}
              {!isRightCollapsed && (
                <div
                  onMouseDown={handleDragStart('horizontal')}
                  style={{
                    width: 6,
                    cursor: 'col-resize',
                    background: 'linear-gradient(to right, #d9d9d9, #bfbfbf, #d9d9d9)',
                    flexShrink: 0,
                    margin: '0 2px',
                    transition: 'background 0.15s',
                  }}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = '#1677ff'; }}
                  onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = 'linear-gradient(to right, #d9d9d9, #bfbfbf, #d9d9d9)'; }}
                />
              )}
            </>
          )}

          {/* 右侧：PDF 预览 */}
          {isRightCollapsed ? (
            /* 折叠态：右侧竖条，内容向右贴边 */
            <div
              style={{
                flexShrink: 0,
                width: 32,
                background: '#fafafa',
                border: '1px solid #e8e8e8',
                borderRight: 'none',
                borderRadius: '6px 0 0 6px',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer',
                gap: 8,
              }}
              onClick={() => setIsRightCollapsed(false)}
              title="展开文献预览面板"
            >
              <LeftOutlined style={{ fontSize: 12, color: '#888' }} />
              <span
                style={{
                  writingMode: 'vertical-rl',
                  fontSize: 13,
                  fontWeight: 600,
                  color: '#666',
                  letterSpacing: 2,
                }}
              >
                文献预览
              </span>
            </div>
          ) : (
            <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', transition: 'flex 0.25s' }}>
              <Card
                title={
                  <Space>
                    <MenuFoldOutlined
                      style={{ cursor: 'pointer', color: '#888' }}
                      onClick={() => setIsRightCollapsed(true)}
                    />
                    <span>文献预览</span>
                  </Space>
                }
                styles={{ body: { padding: 8, flex: 1, overflow: 'hidden', minHeight: 0 } }}
                style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
              >
                {id ? (
                  <FilePreview
                    literatureId={id}
                    filePath={literature?.file_path || null}
                    defaultScale={0.8}
                    maxHeight="100%"
                    onFileUploaded={fetchData}
                  />
                ) : (
                  <div style={{ textAlign: 'center', paddingTop: 100, color: '#999' }}>
                    无法加载预览
                  </div>
                )}
              </Card>
            </div>
          )}
        </div>
      </div>

      <Modal
        title={modalAction === 'approved' ? '批量审核通过' : '批量驳回'}
        open={modalOpen}
        onOk={handleBatchReview}
        onCancel={() => { setModalOpen(false); setReviewNote(''); }}
        okText="确认"
        cancelText="取消"
      >
        <p style={{ marginBottom: 12 }}>
          将对选中的 {selectedRowKeys.length} 个数据点{modalAction === 'approved' ? '通过' : '驳回'}审核。
          {modalAction === 'rejected' && <span style={{ color: '#cf1322' }}> 驳回必须填写审核意见。</span>}
        </p>
        <Input.TextArea
          placeholder={modalAction === 'rejected' ? '审核意见（必填）' : '审核意见（选填）'}
          value={reviewNote}
          onChange={(e) => setReviewNote(e.target.value)}
          rows={3}
        />
      </Modal>

      <Modal
        title={<><RobotOutlined /> 选择提取模型</>}
        open={extractModalOpen}
        onCancel={() => setExtractModalOpen(false)}
        onOk={confirmExtract}
        confirmLoading={extracting}
        okText="开始提取"
        width={520}
      >
        <p style={{ marginBottom: 16, color: '#888' }}>选择用于 AI 数据提取的大语言模型。不同模型的提取精度和速度可能有所差异。</p>
        <Select
          placeholder="默认模型"
          allowClear
          style={{ width: '100%', marginBottom: 16 }}
          value={extractModel}
          onChange={(v) => {
            setExtractModel(v);
            const vendor = modelOptions.find((o) => o.value === v)?.vendor || '';
            setExtractBaseUrl(VENDOR_INFO[vendor]?.defaultBaseUrl || '');
          }}
          options={modelOptions}
        />
        {extractModel && extractModel !== '' && (() => {
          const vendor = modelOptions.find((o) => o.value === extractModel)?.vendor || '';
          const info = VENDOR_INFO[vendor];
          if (!vendor || !info.name) return null;
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
                style={{ marginBottom: 12 }}
              />
            </>
          );
        })()}
        <div style={{ marginTop: 16, paddingTop: 12, borderTop: '1px solid #f0f0f0' }}>
          <Checkbox
            checked={forceRefreshCache}
            onChange={(e) => setForceRefreshCache(e.target.checked)}
          >
            强制重新跑 LLM（跳过已有缓存，重新调用模型获取新鲜结果）
          </Checkbox>
        </div>
        <div style={{ marginTop: 8 }}>
          <Checkbox
            checked={enableThinking}
            onChange={(e) => setEnableThinking(e.target.checked)}
          >
            开启模型推理（thinking）—— 让模型先思考再输出，耗时更长，抽取任务建议保持关闭
          </Checkbox>
        </div>
        <div style={{ marginTop: 8 }}>
          <Checkbox
            checked={showUsageOnComplete}
            onChange={(e) => toggleShowUsage(e.target.checked)}
          >
            提取完成后显示 Token 用量、费用和模型信息
          </Checkbox>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8, paddingTop: 8, borderTop: '1px solid #f0f0f0' }}>
          <Text style={{ fontSize: 13, color: '#1677ff' }}>
            ℹ️ 追加模式：本次提取将保留全部已有数据点，新增一批独立结果（新旧通过「提取模型/时间」列区分）
          </Text>
        </div>
        {(dataPoints.length > 0 || historyList.length > 0) && (
          <Alert
            style={{ marginTop: 10 }}
            type="warning"
            showIcon
            message="该文献已有提取记录/数据点，以上开关决定了本次如何处理已有数据。新提取的数据点会自动标记本次使用的模型和时间。"
          />
        )}
      </Modal>

      <Modal
        title={
          <div
            onMouseDown={handleModalDragMouseDown}
            style={{ cursor: 'move', userSelect: 'none', display: 'inline-block', width: '100%' }}
          >
            <PlusOutlined /> 新增数据点 <span style={{ fontSize: 12, color: '#999', marginLeft: 8 }}>(可拖拽移动)</span>
          </div>
        }
        open={addModalOpen}
        onCancel={() => setAddModalOpen(false)}
        onOk={async () => {
          if (!id) return;
          setAddSaving(true);
          try {
            await createDataPoint(id, addForm);
            message.success('数据点已添加');
            setAddModalOpen(false);
            // 数据点变更影响地图/分析数据，清除相关接口缓存
            clearMapApiCache();
            clearAnalysisApiCache();
            fetchData();
          } catch (err) {
            console.error('[LiteratureDetail] 手动新增数据点失败:', err);
            message.error('添加失败');
          } finally {
            setAddSaving(false);
          }
        }}
        confirmLoading={addSaving}
        okText="添加"
        cancelText="取消"
        width={640}
        mask={false}
        maskClosable={false}
        style={{ left: addModalPos.x, top: addModalPos.y, pointerEvents: 'auto' }}
        wrapProps={{ style: { pointerEvents: 'none' } }}
        modalRender={(node) => <div style={{ pointerEvents: 'auto' }}>{node}</div>}
      >
        <Row gutter={[16, 12]}>
          <Col span={8}>
            <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>疾病</div>
            <Select
              style={{ width: '100%' }}
              size="small"
              placeholder="选择疾病"
              allowClear
              value={addForm.disease as string | undefined}
              onChange={(v) => setAddForm((f) => ({ ...f, disease: v || null }))}
              options={DISEASES.map((d) => ({ value: d.key, label: d.name_cn }))}
            />
          </Col>
          <Col span={8}>
            <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>数据类型</div>
            <Select
              style={{ width: '100%' }}
              size="small"
              placeholder="选择类型"
              allowClear
              value={addForm.data_type as string | undefined}
              onChange={(v) => setAddForm((f) => ({ ...f, data_type: v || null }))}
              options={Object.entries(DATA_TYPE_LABEL).map(([k, label]) => ({ value: k, label }))}
            />
          </Col>
          <Col span={8}>
            <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>置信度</div>
            <Select
              style={{ width: '100%' }}
              size="small"
              value={addForm.confidence as string}
              onChange={(v) => setAddForm((f) => ({ ...f, confidence: v }))}
              options={[
                { value: 'high', label: '高' },
                { value: 'medium', label: '中' },
                { value: 'low', label: '低' },
              ]}
            />
          </Col>
          <Col span={8}>
            <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>省份</div>
            <Select
              style={{ width: '100%' }}
              size="small"
              placeholder="选择省份"
              allowClear
              showSearch
              value={addForm.province as string | undefined}
              onChange={(v) => setAddForm((f) => ({ ...f, province: v || null }))}
              options={PROVINCES.map((p) => ({ value: p, label: p }))}
            />
          </Col>
          <Col span={8}>
            <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>城市</div>
            <Input
              size="small"
              placeholder="输入城市"
              value={addForm.city as string | undefined}
              onChange={(e) => setAddForm((f) => ({ ...f, city: e.target.value || null }))}
            />
          </Col>
          <Col span={8}>
            <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>群体</div>
            <Input
              size="small"
              placeholder="如：儿童、学生"
              value={addForm.population as string | undefined}
              onChange={(e) => setAddForm((f) => ({ ...f, population: e.target.value || null }))}
            />
          </Col>
          <Col span={6}>
            <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>数值</div>
            <InputNumber
              size="small"
              style={{ width: '100%' }}
              placeholder="数值"
              value={addForm.value as number | undefined}
              onChange={(v) => setAddForm((f) => ({ ...f, value: v ?? null }))}
              step={0.1}
            />
          </Col>
          <Col span={6}>
            <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>单位</div>
            <Input
              size="small"
              placeholder="如：%、IU/mL"
              value={addForm.unit as string | undefined}
              onChange={(e) => setAddForm((f) => ({ ...f, unit: e.target.value || null }))}
            />
          </Col>
          <Col span={6}>
            <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>样本量</div>
            <InputNumber
              size="small"
              style={{ width: '100%' }}
              placeholder="样本量"
              value={addForm.sample_size as number | undefined}
              onChange={(v) => setAddForm((f) => ({ ...f, sample_size: v ?? null }))}
              min={0}
            />
          </Col>
          <Col span={6}>
            <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>采集年份</div>
            <InputNumber
              size="small"
              style={{ width: '100%' }}
              placeholder="年份"
              value={addForm.collection_year as number | undefined}
              onChange={(v) => setAddForm((f) => ({ ...f, collection_year: v ?? null }))}
              min={1900}
              max={2100}
            />
          </Col>
          <Col span={6}>
            <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>年龄下限</div>
            <InputNumber
              size="small"
              style={{ width: '100%' }}
              placeholder="最小年龄"
              value={addForm.age_min as number | undefined}
              onChange={(v) => setAddForm((f) => ({ ...f, age_min: v ?? null }))}
              min={0}
              max={150}
            />
          </Col>
          <Col span={6}>
            <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>年龄上限</div>
            <InputNumber
              size="small"
              style={{ width: '100%' }}
              placeholder="最大年龄"
              value={addForm.age_max as number | undefined}
              onChange={(v) => setAddForm((f) => ({ ...f, age_max: v ?? null }))}
              min={0}
              max={150}
            />
          </Col>
          <Col span={6}>
            <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>方法</div>
            <Input
              size="small"
              placeholder="检测方法"
              value={addForm.method as string | undefined}
              onChange={(e) => setAddForm((f) => ({ ...f, method: e.target.value || null }))}
            />
          </Col>
          <Col span={6}>
            <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>试剂/试纸</div>
            <Input
              size="small"
              placeholder="试剂/试纸"
              value={addForm.assay as string | undefined}
              onChange={(e) => setAddForm((f) => ({ ...f, assay: e.target.value || null }))}
            />
          </Col>
          <Col span={12}>
            <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>来源页码</div>
            <InputNumber
              size="small"
              style={{ width: '100%' }}
              placeholder="页码"
              value={addForm.source_page as number | undefined}
              onChange={(v) => setAddForm((f) => ({ ...f, source_page: v ?? null }))}
              min={1}
            />
          </Col>
          <Col span={12}>
            <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>字符区间 [start, end)</div>
            <Space size={4}>
              <InputNumber
                size="small"
                style={{ width: 120 }}
                placeholder="起始"
                min={0}
                value={addForm.source_char_start as number | undefined}
                onChange={(v) => setAddForm((f) => ({ ...f, source_char_start: v ?? null }))}
              />
              <InputNumber
                size="small"
                style={{ width: 120 }}
                placeholder="结束"
                min={0}
                value={addForm.source_char_end as number | undefined}
                onChange={(v) => setAddForm((f) => ({ ...f, source_char_end: v ?? null }))}
              />
            </Space>
          </Col>
          <Col span={24}>
            <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>原文依据</div>
            <Input.TextArea
              rows={2}
              placeholder="输入原文依据上下文"
              value={addForm.source_context as string | undefined}
              onChange={(e) => setAddForm((f) => ({ ...f, source_context: e.target.value || null }))}
            />
          </Col>
          <Col span={24} style={{ marginBottom: 4 }}>
            <div
              style={{
                fontSize: 12,
                color: addForm.is_grounded ? '#389e0d' : '#b82601',
                display: 'flex',
                alignItems: 'center',
                gap: 8,
              }}
            >
              <span>
                溯源状态：
                {addForm.is_grounded
                  ? '已匹配原文（用户手动确认）'
                  : '未匹配 / 未确认'}
              </span>
              <Button
                size="small"
                type={addForm.is_grounded ? 'default' : 'primary'}
                onClick={() =>
                  setAddForm((f) => ({ ...f, is_grounded: !f.is_grounded }))
                }
              >
                {addForm.is_grounded ? '取消确认' : '手动标记为已匹配'}
              </Button>
            </div>
          </Col>
        </Row>
      </Modal>

      {/* P2：溯源查看弹窗 */}
      <Modal
        title="溯源查看 — 原文高亮"
        open={sourceModalOpen}
        onCancel={() => setSourceModalOpen(false)}
        footer={null}
        width={800}
        styles={{ body: { maxHeight: '60vh', overflow: 'auto' } }}
      >
        {sourceLoading ? (
          <div style={{ textAlign: 'center', padding: '40px 0' }}>
            <Spin tip="加载原文中...">
              <div style={{ height: 80 }} />
            </Spin>
          </div>
        ) : sourceText ? (
          <div
            style={{
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-all',
              lineHeight: 1.8,
              fontSize: 14,
              fontFamily: "'Consolas', 'Monaco', monospace",
              background: '#fafafa',
              padding: 16,
              borderRadius: 6,
              border: '1px solid #e8e8e8',
            }}
          >
            {(() => {
              if (sourceHighlightStart == null || sourceHighlightEnd == null) {
                return sourceText;
              }
              const before = sourceText.substring(0, sourceHighlightStart);
              const highlight = sourceText.substring(sourceHighlightStart, sourceHighlightEnd);
              const after = sourceText.substring(sourceHighlightEnd);
              return (
                <>
                  {before}
                  <span className="source-highlight">{highlight}</span>
                  {after}
                </>
              );
            })()}
          </div>
        ) : (
          <div style={{ textAlign: 'center', padding: '40px 0', color: '#999' }}>
            未能获取溯源文本。该文献可能尚未提取，或溯源文本缓存不存在，请重新提取该文献。
          </div>
        )}
      </Modal>

      </>
  );
};

export default LiteratureDetail;
