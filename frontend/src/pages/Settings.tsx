import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Card, Tabs, Button, Space, Tag, Select, Input, Alert, Typography, Empty, Spin, Tooltip,
} from 'antd';
import {
  SettingOutlined, RobotOutlined, SafetyOutlined, FileTextOutlined, ReloadOutlined,
  SearchOutlined, DownOutlined, ClearOutlined, DesktopOutlined,
} from '@ant-design/icons';
import ModelManager from '../components/ModelManager';
import LocalModelManager from '../components/LocalModelManager';
import { getSystemInfo, listLogFiles, getLogContent, SystemInfo, LogFile, LogEntry } from '../services/system';
import './Settings.css';

const { Text } = Typography;

const LEVEL_OPTIONS = [
  { value: '', label: '全部级别' },
  { value: 'INFO', label: 'INFO' },
  { value: 'SUCCESS', label: 'SUCCESS' },
  { value: 'WARNING', label: 'WARNING' },
  { value: 'ERROR', label: 'ERROR' },
  { value: 'DEBUG', label: 'DEBUG' },
];

const LEVEL_COLOR: Record<string, string> = {
  INFO: '#1677ff',
  SUCCESS: '#52c41a',
  WARNING: '#faad14',
  ERROR: '#ff4d4f',
  DEBUG: '#8c8c8c',
  TRACE: '#8c8c8c',
  CRITICAL: '#f5222d',
};

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + ' MB';
  if (bytes >= 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return bytes + ' B';
}

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

const Settings: React.FC = () => {
  const [modelModalVisible, setModelModalVisible] = useState(false);
  const [localModelModalVisible, setLocalModelModalVisible] = useState(false);
  const [activeTab, setActiveTab] = useState('models');

  // ── 系统信息（动态）──
  const [sysInfo, setSysInfo] = useState<SystemInfo | null>(null);
  const [sysLoading, setSysLoading] = useState(false);

  // ── 后台日志 ──
  const [logFiles, setLogFiles] = useState<LogFile[]>([]);
  const [logDir, setLogDir] = useState('');
  const [selectedFile, setSelectedFile] = useState<string>('');
  const [logLines, setLogLines] = useState<LogEntry[]>([]);
  const [logTotal, setLogTotal] = useState(0);
  const [levelFilter, setLevelFilter] = useState('');
  const [keyword, setKeyword] = useState('');
  const [logLoading, setLogLoading] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const [logError, setLogError] = useState('');
  const logBodyRef = useRef<HTMLDivElement>(null);
  const keywordRef = useRef<any>(null);

  const loadSystemInfo = useCallback(async () => {
    setSysLoading(true);
    try {
      const info = await getSystemInfo();
      setSysInfo(info);
    } catch (err) {
      console.error('[Settings] 加载系统信息失败:', err);
    } finally {
      setSysLoading(false);
    }
  }, []);

  const loadLogFiles = useCallback(async () => {
    try {
      const { dir, files } = await listLogFiles();
      setLogDir(dir);
      setLogFiles(files);
      if (files.length > 0) {
        // 保持当前选择；未选择或已失效时默认选最新文件
        setSelectedFile((cur) => {
          const exists = files.some((f) => f.name === cur);
          return exists ? cur : files[0].name;
        });
      } else {
        setSelectedFile('');
        setLogLines([]);
      }
    } catch (err) {
      console.error('[Settings] 加载日志文件列表失败:', err);
    }
  }, []);

  const loadLogContent = useCallback(async (file?: string, lv?: string, kw?: string) => {
    const target = file !== undefined ? file : selectedFile;
    if (!target) return;
    setLogLoading(true);
    setLogError('');
    try {
      const data = await getLogContent({
        file: target,
        lines: 500,
        level: lv !== undefined ? lv : levelFilter,
        keyword: kw !== undefined ? kw : keyword,
      });
      setLogLines(data.entries);
      setLogTotal(data.matched_lines);
    } catch (err: any) {
      console.error('[Settings] 读取日志失败:', err);
      setLogError(err?.response?.data?.detail || '读取日志失败');
      setLogLines([]);
    } finally {
      setLogLoading(false);
    }
  }, [selectedFile, levelFilter, keyword]);

  // 首次加载：系统信息 + 日志文件列表
  useEffect(() => {
    loadSystemInfo();
    loadLogFiles();
  }, [loadSystemInfo, loadLogFiles]);

  // 选中文件或筛选变化时重新读取日志
  useEffect(() => {
    if (selectedFile) {
      loadLogContent(selectedFile, levelFilter, keyword);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedFile, levelFilter]);

  // 自动滚动到底部（最新日志）
  useEffect(() => {
    if (autoScroll && logBodyRef.current) {
      logBodyRef.current.scrollTop = logBodyRef.current.scrollHeight;
    }
  }, [logLines, autoScroll]);

  const handleKeywordSearch = () => {
    loadLogContent(selectedFile, levelFilter, keyword);
  };

  const handleClearKeyword = () => {
    setKeyword('');
    loadLogContent(selectedFile, levelFilter, '');
    if (keywordRef.current) keywordRef.current.focus();
  };

  const handleRefresh = () => {
    loadLogFiles();
    if (selectedFile) loadLogContent(selectedFile, levelFilter, keyword);
  };

  const handleModelSaved = () => {
    // 模型保存后不需要额外操作，表格已在内部刷新
  };

  const handleScroll = () => {
    if (!logBodyRef.current) return;
    const el = logBodyRef.current;
    // 距底部超过 60px 视为用户在向上查看历史，暂停自动滚动
    setAutoScroll(el.scrollHeight - el.scrollTop - el.clientHeight < 60);
  };

  const tabItems = [
    {
      key: 'models',
      label: (
        <span>
          <RobotOutlined /> 远程模型配置
        </span>
      ),
      children: (
        <Card>
          <div className="settings-section">
            <p className="settings-desc">
              配置远程LLM模型用于文献智能提取。支持OpenAI兼容API（包括OpenAI、DeepSeek、Ollama等）。
              创建/更新/删除操作仅限管理员访问。
            </p>
            <Button type="primary" onClick={() => setModelModalVisible(true)}>
              管理远程模型
            </Button>
          </div>
        </Card>
      ),
    },
    {
      key: 'localModels',
      label: (
        <span>
          <DesktopOutlined /> 本地模型配置
        </span>
      ),
      children: (
        <Card>
          <div className="settings-section">
            <p className="settings-desc">
              配置本地大模型（Ollama 等）供文献智能提取、报告生成等各功能选择。
              本地模型候选项统一来源于此配置，各功能模块保持一致。
              创建/更新/删除操作仅限管理员访问。
            </p>
            <Button type="primary" icon={<DesktopOutlined />} onClick={() => setLocalModelModalVisible(true)}>
              管理本地模型
            </Button>
          </div>
        </Card>
      ),
    },
    {
      key: 'logs',
      label: (
        <span>
          <FileTextOutlined /> 后台日志
        </span>
      ),
      children: (
        <Card>
          <div className="settings-section">
            <p className="settings-desc">
              后台运行日志（含 AI 文献提取过程记录）持久化保存于 <Text code>{logDir || 'backend/logs/'}</Text> 目录。
              此处可在线查看最近 500 行日志，按级别 / 关键字过滤，便于排查提取失败等问题原因。
            </p>
            <div className="log-toolbar">
              <Select
                style={{ width: 280 }}
                placeholder="选择日志文件"
                value={selectedFile || undefined}
                onChange={(v) => setSelectedFile(v)}
                options={logFiles.map((f) => ({
                  value: f.name,
                  label: `${f.name}（${formatSize(f.size)} · ${formatTime(f.mtime)}）`,
                }))}
                notFoundContent="暂无日志文件"
              />
              <Select
                style={{ width: 140 }}
                value={levelFilter}
                onChange={setLevelFilter}
                options={LEVEL_OPTIONS}
              />
              <Input
                ref={keywordRef}
                style={{ width: 200 }}
                placeholder="关键字过滤，回车搜索"
                value={keyword}
                allowClear
                onChange={(e) => setKeyword(e.target.value)}
                onPressEnter={handleKeywordSearch}
                prefix={<SearchOutlined />}
              />
              <Button icon={<SearchOutlined />} onClick={handleKeywordSearch}>搜索</Button>
              <Button icon={<ClearOutlined />} onClick={handleClearKeyword}>清空</Button>
              <Tooltip title="刷新日志文件列表与内容">
                <Button icon={<ReloadOutlined />} onClick={handleRefresh}>刷新</Button>
              </Tooltip>
              <Tooltip title="开启后新日志自动滚动到底部；向上滚动查看历史时自动暂停">
                <Button
                  type={autoScroll ? 'primary' : 'default'}
                  icon={<DownOutlined />}
                  onClick={() => setAutoScroll((v) => !v)}
                >
                  {autoScroll ? '自动滚动' : '已暂停'}
                </Button>
              </Tooltip>
            </div>

            {logError && (
              <Alert style={{ margin: '12px 0' }} type="error" showIcon message={logError} />
            )}

            <div className="log-summary">
              <Text type="secondary">
                {selectedFile
                  ? `显示 ${logLines.length} 条（匹配 ${logTotal} 条）日志`
                  : '请选择日志文件'}
              </Text>
            </div>

            <div className="log-body" ref={logBodyRef} onScroll={handleScroll}>
              {logLoading ? (
                <div className="log-empty"><Spin /> 加载日志中...</div>
              ) : logLines.length === 0 ? (
                <Empty description={selectedFile ? '无匹配的日志内容' : '暂无日志'} />
              ) : (
                logLines.map((entry) => (
                  <div key={`${entry.line}-${entry.text.length}-${entry.text.slice(0, 20)}`} className="log-line">
                    <span className="log-level" style={{ color: LEVEL_COLOR[entry.level] || '#8c8c8c' }}>
                      {entry.level}
                    </span>
                    <span className="log-text">{entry.text}</span>
                  </div>
                ))
              )}
            </div>
          </div>
        </Card>
      ),
    },
    {
      key: 'system',
      label: (
        <span>
          <SafetyOutlined /> 系统信息
        </span>
      ),
      children: (
        <Card>
          <div className="system-info">
            <div className="system-info-item">
              <span className="label">项目名称</span>
              <span className="value">{sysInfo?.name || 'Antibody Map'}</span>
            </div>
            <div className="system-info-item">
              <span className="label">版本</span>
              <span className="value">
                {sysLoading ? <Spin size="small" /> : <Tag color="blue">v{sysInfo?.version || '...'}</Tag>}
              </span>
            </div>
            <div className="system-info-item">
              <span className="label">运行环境</span>
              <span className="value">
                <Tag color={sysInfo?.environment === 'production' ? 'red' : 'orange'}>
                  {sysInfo?.environment || '...'}
                </Tag>
              </span>
            </div>
            <div className="system-info-item">
              <span className="label">功能特性</span>
              <div className="value">
                {sysInfo?.features?.length ? (
                  <Space wrap>
                    {sysInfo.features.map((f) => <Tag color="green" key={f}>{f}</Tag>)}
                  </Space>
                ) : (
                  <Spin size="small" />
                )}
              </div>
            </div>
            <div className="system-info-item">
              <span className="label">日志目录</span>
              <span className="value"><Text code>{sysInfo?.log_dir || '...'}</Text></span>
            </div>
            <div className="system-info-item">
              <span className="label">项目地址</span>
              <span className="value">
                <a href={sysInfo?.repo_url || 'https://github.com/liuxiong714/antibody_map'} target="_blank" rel="noopener noreferrer">
                  {sysInfo?.repo_url || 'github.com/liuxiong714/antibody_map'}
                </a>
              </span>
            </div>
          </div>
        </Card>
      ),
    },
  ];

  return (
    <div className="settings-page">
      <Card
        title={<><SettingOutlined /> 系统设置</>}
        className="settings-card"
      >
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={tabItems}
        />
      </Card>

      <ModelManager
        visible={modelModalVisible}
        onClose={() => setModelModalVisible(false)}
        onSaved={handleModelSaved}
      />

      <LocalModelManager
        visible={localModelModalVisible}
        onClose={() => setLocalModelModalVisible(false)}
        onSaved={() => {
          // 本地模型变更后刷新一次系统信息（无状态刷新即可）
        }}
      />
    </div>
  );
};

export default Settings;
