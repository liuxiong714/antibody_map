import React, { useState } from 'react';
import { Button, Card, Input, Select, Space, Table, Upload, message } from 'antd';
import { DownloadOutlined, FileTextOutlined, ImportOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import api from '../services/api';

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
  const [refFmt, setRefFmt] = useState('auto');
  const [importingRef, setImportingRef] = useState(false);

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
    try {
      const resp = await api.post('/pubmed/import', { pmids });
      const data = resp.data as { success_count?: number; fail_count?: number };
      message.success(`成功纳入 ${data.success_count ?? 0} 篇，失败 ${data.fail_count ?? 0} 篇`);
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '纳入数据库失败');
    } finally {
      setImporting(false);
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

  // 导入题录文件（RIS / EndNote / PubMed 文本 / WoS），读取文本后按所选来源上传
  const handleImportReferences = async (file: File) => {
    if (!file) return false;
    try {
      const refText = await file.text();
      if (!refText.trim()) {
        message.warning('题录文件内容为空');
        return false;
      }
      setImportingRef(true);
      const resp = await api.post('/literatures/import-references', {
        ref_text: refText,
        fmt: REF_FMT_MAP[refFmt] || 'auto',
      });
      const data = resp.data as { imported?: number; skipped?: number; total?: number };
      message.success(`成功导入 ${data.imported ?? 0} 篇，跳过 ${data.skipped ?? 0} 篇`);
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '导入题录失败，请检查文件格式');
    } finally {
      setImportingRef(false);
    }
    return false; // 阻止 antd 自动上传
  };

  const columns: ColumnsType<PubmedItem> = [
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
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
        <span style={{ color: '#999' }}>支持 RIS / EndNote / PubMed 文本 / WoS 文件</span>
      </Space>
    </Card>
  );
};

export default PubmedSearchPage;
