import React, { useState } from 'react';
import { Button, Card, Input, Modal, Progress, Select, Space, Table, Upload, message } from 'antd';
import { DownloadOutlined, FileTextOutlined, ImportOutlined, OrderedListOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import api from '../services/api';
import { listImportLogs } from '../services/literature';
import type { ImportLogItem, ImportLogsResult } from '../services/literature';

// 检索来源下拉选项；pubmed 走 /pubmed/search，其余走 /pubmed/search/multi
const SOURCE_OPTIONS = [
  { value: 'pubmed', label: 'PubMed' },
  { value: 'crossref', label: 'Crossref' },
  { value: 'openalex', label: 'OpenAlex' },
  { value: 'europepmc', label: 'Europe PMC' },
];

// 题录导入的格式/来源下拉选项
const REF_FMT_OPTIONS = [
  { value: 'auto', label: '自动识别' },
  { value: 'pubmed', label: 'PubMed' },
  { value: 'cnki', label: '知网' },
  { value: 'wos', label: 'Web of Science' },
];

// 来源 → 后端 fmt 参数；知网 .ris/.enw 由后端自动识别
const REF_FMT_MAP: Record<string, string> = {
  auto: 'auto',
  pubmed: 'pubmed',
  cnki: 'auto',
  wos: 'wos',
};

interface PubmedItem {
  id?: string;
  source?: string;
  pmid?: string;
  title?: string;
  year?: string | null;
  journal?: string | null;
  authors?: string | null;
  doi?: string | null;
  abstract?: string | null;
  oa_pdf_url?: string | null;
}

interface PubmedSearchResponse {
  items: PubmedItem[];
  total: number;
  page: number;
  page_size: number;
}

const PubmedSearchPage: React.FC = () => {
  const [keyword, setKeyword] = useState('');
  const [source, setSource] = useState('pubmed');
  const [items, setItems] = useState<PubmedItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [importing, setImporting] = useState(false);
  const [downloading, setDownloading] = useState(false);
  // 导入任务进度：done/total（按批导入时实时更新）
  const [importProgress, setImportProgress] = useState<{ done: number; total: number }>({ done: 0, total: 0 });
  const [refFmt, setRefFmt] = useState('auto');
  const [importingRef, setImportingRef] = useState(false);
  // 导入题录进度：done/total（按批导入时实时更新）
  const [importRefProgress, setImportRefProgress] = useState<{ done: number; total: number }>({ done: 0, total: 0 });

  // 摘要展开缓存：pmid → abstract text
  const [abstractCache, setAbstractCache] = useState<Record<string, string>>({});
  const [expandedPmids, setExpandedPmids] = useState<React.Key[]>([]);
  const [loadingAbstracts, setLoadingAbstracts] = useState<Record<string, boolean>>({});

  // 导入日志
  const [importLogModalOpen, setImportLogModalOpen] = useState(false);
  const [importLogs, setImportLogs] = useState<ImportLogItem[]>([]);
  const [importLogsLoading, setImportLogsLoading] = useState(false);
  const [importLogsTotal, setImportLogsTotal] = useState(0);
  const [importLogsPage, setImportLogsPage] = useState(1);

  const selectedPmids = selectedRowKeys.map(String);

  const doSearch = async (p = page, ps = pageSize) => {
    const q = keyword.trim();
    if (!q) {
      message.warning('请输入检索关键词');
      return;
    }
    setLoading(true);
    try {
      let data: PubmedSearchResponse;
      if (source === 'pubmed') {
        const resp = await api.get('/pubmed/search', { params: { q, page: p, page_size: ps } });
        data = resp.data as PubmedSearchResponse;
      } else {
        const resp = await api.get('/pubmed/search/multi', {
          params: { source, q, page: p, page_size: ps },
        });
        data = resp.data as PubmedSearchResponse;
      }
      setItems(data.items || []);
      setTotal(data.total || 0);
      setPage(data.page || p);
      setPageSize(data.page_size || ps);
      setSelectedRowKeys([]);
      setExpandedPmids([]);
      setAbstractCache({});
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '检索失败');
    } finally {
      setLoading(false);
    }
  };

  const handleImport = async () => {
    const pmids = selectedPmids;
    if (pmids.length === 0) return;
    setImporting(true);
    // 每批导入条数：批量分批请求，实时刷新进度；后端按 PMID 幂等查重
    const BATCH = 10;
    setImportProgress({ done: 0, total: pmids.length });
    let success = 0;
    let fail = 0;
    try {
      for (let i = 0; i < pmids.length; i += BATCH) {
        const batch = pmids.slice(i, i + BATCH);
        try {
          const resp = await api.post('/pubmed/import', { pmids: batch });
          const data = resp.data as { success_count?: number; fail_count?: number };
          success += data.success_count ?? 0;
          fail += data.fail_count ?? 0;
        } catch (err: any) {
          // 单批失败计入失败数，继续导入剩余批次
          fail += batch.length;
        }
        setImportProgress((p) => ({ ...p, done: Math.min(i + batch.length, pmids.length) }));
      }
      message.success(`成功纳入 ${success} 篇，失败 ${fail} 篇`);
    } finally {
      setImporting(false);
      setImportProgress({ done: 0, total: 0 });
    }
  };

  const handleDownloadPdf = async () => {
    const pmids = selectedPmids;
    if (pmids.length === 0) return;
    setDownloading(true);
    try {
      const resp = await api.post('/pubmed/download-pdf', { pmids });
      const data = resp.data as {
        downloaded?: string[];
        no_oa?: string[];
        failed?: string[];
        dir?: string;
      };
      message.success(`已下载 ${data.downloaded?.length ?? 0} 篇到 ${data.dir ?? ''}`);
      message.warning(`${data.no_oa?.length ?? 0} 篇无开放全文`);
      message.error(`${data.failed?.length ?? 0} 篇下载失败`);
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '下载 PDF 失败');
    } finally {
      setDownloading(false);
    }
  };

  // 导入题录文件（RIS / EndNote / PubMed 文本 / WoS），先预览再按批导入
  const handleImportReferences = async (file: File) => {
    if (!file) return false;
    try {
      const refText = await file.text();
      if (!refText.trim()) {
        message.warning('题录文件内容为空');
        return false;
      }
      setImportingRef(true);
      // 1. 预览：统计总条数、重复条数、可导入条数
      const previewResp = await api.post('/literatures/import-references/preview', {
        ref_text: refText,
        fmt: REF_FMT_MAP[refFmt] || 'auto',
      });
      const previewData = previewResp.data as { total?: number; skipped?: number; imported?: number; importable_indices?: number[] } || {};
      const total = previewData.total ?? 0;
      const skipped = previewData.skipped ?? 0;
      const imported = previewData.imported ?? 0;
      // 可导入记录的真实行号（后端 /preview 返回，去重后按实际位置分批，避免重复记录散落时漏导）
      const importableIndices: number[] = previewData.importable_indices ?? [];

      if (imported === 0) {
        message.info('所有题录均已存在，无需导入');
        // 不提前返回，后续仍调用一次导入接口以记录日志
      }

      // 2. 显示确认对话框（仅当有实际可导入记录时）
      if (imported > 0) {
        const confirmed = await new Promise<boolean>((resolve) => {
          Modal.confirm({
            title: '确认导入题录',
            content: (
              <div style={{ lineHeight: 2 }}>
                <p>本次共解析 <strong>{total}</strong> 条题录记录</p>
                <p>其中重复/无效 <strong>{skipped}</strong> 条（自动剔除）</p>
                <p>实际将导入 <strong style={{ color: '#1890ff' }}>{imported}</strong> 条</p>
              </div>
            ),
            okText: `确认导入 ${imported} 条`,
            cancelText: '取消',
            onOk: () => resolve(true),
            onCancel: () => resolve(false),
          });
        });
        if (!confirmed) {
          setImportingRef(false);
          return false;
        }
      }

      // 3. 分批导入，进度条从 0 逐渐增加到 100；按真实可导入行号分批，避免重复记录散落时漏导
      const BATCH = 25;
      // 旧版后端无 importable_indices：回退到按 count 连续切片（与旧行为一致）
      const targetIndices: number[] = importableIndices.length > 0
        ? importableIndices
        : Array.from({ length: imported }, (_, i) => i);
      setImportRefProgress({ done: 0, total: targetIndices.length > 0 ? targetIndices.length : 1 });
      let totalImported = 0;
      let totalSkipped = 0;

      if (targetIndices.length > 0) {
        for (let i = 0; i < targetIndices.length; i += BATCH) {
          const chunk = targetIndices.slice(i, i + BATCH);
          try {
            const resp = await api.post('/literatures/import-references', {
              ref_text: refText,
              fmt: REF_FMT_MAP[refFmt] || 'auto',
              file_name: file.name,
              indices: chunk,
              skip_log: true,
            });
            const data = resp.data as { imported?: number; skipped?: number } || {};
            totalImported += data.imported ?? 0;
            totalSkipped += data.skipped ?? 0;
          } catch (err: any) {
            totalSkipped += chunk.length;
          }

          setImportRefProgress((p) => ({
            ...p,
            done: Math.min(p.done + chunk.length, targetIndices.length),
          }));
        }
      } else {
        totalSkipped = total;
        setImportRefProgress((p) => ({ ...p, done: 1 }));
      }

      // 汇总写一条导入日志（不分批，只写一次）
      try {
        await api.post('/literatures/import-references/log', {
          file_name: file.name,
          total_count: total,
          skipped_count: totalSkipped,
          imported_count: totalImported,
          fmt: REF_FMT_MAP[refFmt] || 'auto',
        });
      } catch (_err: any) { /* ignore */ }

      if (imported === 0) {
        message.info(`所有 ${total} 条题录均为重复/无效，已记录至导入日志`);
      } else {
        message.success(`成功导入 ${totalImported} 篇，跳过 ${totalSkipped} 篇（共 ${imported} 条）`);
      }
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '导入题录失败，请检查文件格式');
    } finally {
      setImportingRef(false);
      setImportRefProgress({ done: 0, total: 0 });
    }
    return false; // 阻止 antd 自动上传
  };

  const columns: ColumnsType<PubmedItem> = [
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
      render: (v: string | undefined) => v || '-',
    },
    {
      title: '摘要',
      key: 'abstract',
      width: 80,
      render: (_: unknown, record: PubmedItem) => {
        const pmid = record.pmid;
        if (!pmid) return <span style={{ color: '#ccc' }}>-</span>;
        const cached = abstractCache[pmid];
        const isExpanded = expandedPmids.includes(pmid);
        if (isExpanded) {
          return <span style={{ color: '#1890ff' }}>已展开</span>;
        }
        if (cached) {
          return <Button type="link" size="small" onClick={() => setExpandedPmids(prev => [...prev, pmid])}>查看摘要</Button>;
        }
        return <Button type="link" size="small" onClick={() => setExpandedPmids(prev => [...prev, pmid])}>查看摘要</Button>;
      },
    },
    {
      title: '年份',
      dataIndex: 'year',
      key: 'year',
      width: 80,
      render: (v: string | null) => v || '-',
    },
    {
      title: '期刊',
      dataIndex: 'journal',
      key: 'journal',
      width: 220,
      ellipsis: true,
    },
    {
      title: '来源',
      dataIndex: 'source',
      key: 'source',
      width: 100,
      render: (v: string | undefined, record: PubmedItem) => (
        <span>{record.source || source}</span>
      ),
    },
    {
      title: 'PMID',
      dataIndex: 'pmid',
      key: 'pmid',
      width: 110,
      render: (v: string) => <span style={{ fontFamily: 'monospace' }}>{v}</span>,
    },
  ];

  return (
    <Card>
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ margin: 0, fontSize: 18 }}>PubMed 检索</h2>
      </div>
      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          value={source}
          onChange={(v) => setSource(v)}
          options={SOURCE_OPTIONS}
          style={{ width: 130 }}
        />
        <Input.Search
          placeholder="输入检索词，如 measles China"
          allowClear
          enterButton="检索"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onSearch={() => {
            setPage(1);
            doSearch(1, pageSize);
          }}
          style={{ width: 420 }}
        />
      </Space>
      <Table
        rowKey={(record) => record.id || record.pmid || record.title || String(Math.random())}
        columns={columns}
        dataSource={items}
        loading={loading}
        size="small"
        rowSelection={{
          selectedRowKeys,
          onChange: (keys) => setSelectedRowKeys(keys),
        }}
        expandable={{
          expandedRowKeys: expandedPmids,
          onExpandedRowsChange: (keys: readonly React.Key[]) => setExpandedPmids([...keys]),
          expandedRowRender: (record) => {
            const pmid = record.pmid;
            if (!pmid) return <span style={{ color: '#999' }}>无 PMID</span>;
            const cached = abstractCache[pmid];
            if (cached) {
              return (
                <div style={{ padding: '8px 16px', lineHeight: 1.8, fontSize: 13, color: '#333', whiteSpace: 'pre-wrap', maxHeight: 300, overflow: 'auto' }}>
                  {cached}
                </div>
              );
            }
            // 异步加载摘要（注意：响应拦截器已自动解包 ApiResponse.data）
            if (!loadingAbstracts[pmid]) {
              setLoadingAbstracts(prev => ({ ...prev, [pmid]: true }));
              api.get(`/pubmed/abstract/${pmid}`).then(resp => {
                // resp.data 已被拦截器解包为 { pmid, abstract }
                const abstract = (resp.data as any)?.abstract || '';
                setAbstractCache(prev => ({ ...prev, [pmid]: abstract || '（无摘要）' }));
              }).catch(() => {
                setAbstractCache(prev => ({ ...prev, [pmid]: '（获取摘要失败）' }));
              }).finally(() => {
                setLoadingAbstracts(prev => ({ ...prev, [pmid]: false }));
              });
            }
            return <span style={{ color: '#999' }}>加载摘要中...</span>;
          },
        }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
            doSearch(p, ps);
          },
        }}
      />
      <Space style={{ marginTop: 16 }}>
        <Button
          type="primary"
          icon={<ImportOutlined />}
          disabled={selectedPmids.length === 0}
          loading={importing}
          onClick={handleImport}
        >
          纳入数据库
        </Button>
        <Button
          icon={<DownloadOutlined />}
          disabled={selectedPmids.length === 0}
          loading={downloading}
          onClick={handleDownloadPdf}
        >
          下载 PDF
        </Button>
        <span style={{ color: '#999' }}>已选择 {selectedRowKeys.length} 条</span>
      </Space>
      {importing && importProgress.total > 0 && (
        <div style={{ marginTop: 12, maxWidth: 360 }}>
          <Progress
            percent={Math.round((importProgress.done / importProgress.total) * 100)}
            size="small"
            status="active"
          />
          <span style={{ color: '#8c8c8c', fontSize: 12 }}>
            正在纳入数据库：{importProgress.done}/{importProgress.total}
          </span>
        </div>
      )}
      <Space style={{ marginTop: 12 }}>
        <Select
          value={refFmt}
          onChange={(v) => setRefFmt(v)}
          options={REF_FMT_OPTIONS}
          style={{ width: 140 }}
        />
        <Upload
          accept=".ris,.enw,.txt,.csv,.tsv,.nbib"
          showUploadList={false}
          beforeUpload={handleImportReferences}
        >
          <Button icon={<FileTextOutlined />} loading={importingRef}>
            导入题录
          </Button>
        </Upload>
        {importingRef && (
          <div style={{ marginTop: 8, maxWidth: 360 }}>
            <Progress
              percent={importRefProgress.total > 0 ? Math.round((importRefProgress.done / importRefProgress.total) * 100) : 0}
              size="small"
              status="active"
            />
            <span style={{ color: '#8c8c8c', fontSize: 12, display: 'inline-block', marginTop: 2 }}>
              {importRefProgress.total > 0
                ? `正在导入题录：${importRefProgress.done}/${importRefProgress.total}`
                : '正在导入题录...'}
            </span>
          </div>
        )}
        <Button icon={<OrderedListOutlined />} onClick={() => {
          setImportLogModalOpen(true);
          setImportLogsLoading(true);
          listImportLogs(1, 20).then((res) => {
            setImportLogs(res.items || []);
            setImportLogsTotal(res.total || 0);
            setImportLogsPage(1);
          }).catch(() => {
            message.error('获取导入日志失败');
          }).finally(() => {
            setImportLogsLoading(false);
          });
        }}>
          导入日志
        </Button>
        <span style={{ color: '#999' }}>支持 RIS / EndNote / PubMed 文本 / WoS 文件</span>
      </Space>

      {/* 导入日志模态框 */}
      <Modal
        title="题录导入日志"
        width={800}
        open={importLogModalOpen}
        onCancel={() => setImportLogModalOpen(false)}
        footer={null}
      >
        <Table
          rowKey="id"
          dataSource={importLogs}
          loading={importLogsLoading}
          size="small"
          pagination={{
            current: importLogsPage,
            pageSize: 20,
            total: importLogsTotal,
            onChange: (p) => {
              setImportLogsPage(p);
              setImportLogsLoading(true);
              listImportLogs(p, 20).then((res) => {
                setImportLogs(res.items || []);
                setImportLogsTotal(res.total || 0);
              }).catch(() => {
                message.error('获取导入日志失败');
              }).finally(() => {
                setImportLogsLoading(false);
              });
            },
          }}
          columns={[
            { title: '文件名', dataIndex: 'file_name', key: 'file_name', ellipsis: true, width: 200 },
            { title: '导入时间', dataIndex: 'imported_at', key: 'imported_at', width: 180,
              render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
            },
            { title: '识别数', dataIndex: 'total_count', key: 'total_count', width: 70 },
            { title: '剔除数', dataIndex: 'skipped_count', key: 'skipped_count', width: 70 },
            { title: '导入数', dataIndex: 'imported_count', key: 'imported_count', width: 70 },
            { title: '操作人', dataIndex: 'operator_name', key: 'operator_name', width: 100 },
            { title: '格式', dataIndex: 'fmt', key: 'fmt', width: 80 },
          ]}
        />
      </Modal>
    </Card>
  );
};

export default PubmedSearchPage;
