// background.js
// Service worker (Manifest V3)
// 职责：
//   1. 管理右键菜单
//   2. 调用后端 API（绕过 CORS，因 host_permissions 已声明）
//   3. PDF 文件抓取与上传
//   4. 触发 AI 提取并轮询状态
//   5. 桌面通知

const DEFAULT_SETTINGS = {
  backend_url: 'http://localhost:8000',
  auto_extract: true,
  llm_model: '',
  llm_base_url: '',
  default_province: '',
  api_token: '',
};

// ============ 初始化 ============
chrome.runtime.onInstalled.addListener(async () => {
  // 写入默认配置
  const cur = await chrome.storage.local.get('settings');
  if (!cur.settings) {
    await chrome.storage.local.set({ settings: DEFAULT_SETTINGS });
  }
  // 创建右键菜单
  chrome.contextMenus.create({
    id: 'add-to-antibody-map',
    title: '添加到抗体图谱数据库',
    contexts: ['page', 'link', 'image'],
  });
  console.log('[AntibodyMap] 插件已安装');
});

// ============ 配置读取 ============
// API Token 属于敏感凭据：存放在 chrome.storage.session（仅扩展可访问，浏览器重启/扩展卸载即清空），
// 不写入 chrome.storage.local 明文留存。其余非敏感设置仍存 local。
const SESSION_TOKEN_KEY = 'api_token';

async function getSettings() {
  const { settings } = await chrome.storage.local.get('settings');
  const merged = { ...DEFAULT_SETTINGS, ...(settings || {}) };
  let token = '';
  try {
    const s = await chrome.storage.session.get(SESSION_TOKEN_KEY);
    token = s[SESSION_TOKEN_KEY] || '';
    // 一次性迁移：老版本把 token 写进了 local.settings，首次读取时搬入 session 并清掉明文
    if (!token && merged.api_token) {
      await chrome.storage.session.set({ [SESSION_TOKEN_KEY]: merged.api_token });
      const safe = { ...merged, api_token: '' };
      await chrome.storage.local.set({ settings: safe });
      token = merged.api_token;
    }
  } catch (e) {
    // session 存储不可用时退化为读取 local 既有值（不写回）
    console.warn('[AntibodyMap] 读取会话存储失败，回退 local:', e);
    token = merged.api_token;
  }
  return { ...merged, api_token: token };
}

function apiUrl(path, settings) {
  const base = (settings.backend_url || '').replace(/\/+$/, '');
  return `${base}${path}`;
}

// 生成后端 API 认证头（JWT）。返回 null 表示未配置 token
function authHeaders(settings) {
  if (!settings.api_token) return null;
  return { 'Authorization': `Bearer ${settings.api_token}` };
}

// 校验 token 是否已配置，未配置时返回统一错误
function requireAuth(settings) {
  if (!settings.api_token) {
    return { success: false, error: '未配置 API Token，请在扩展设置页填写登录后获取的 JWT' };
  }
  return null;
}

// ============ 右键菜单 ============
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== 'add-to-antibody-map') return;
  // 转发给 popup 流程（这里直接调用处理函数）
  const targetUrl = info.linkUrl || info.pageUrl || (tab && tab.url);
  if (!targetUrl) return;
  // 激活 popup（MV3 不支持编程打开 popup，改用通知引导）
  notify('已捕获链接', '点击插件图标完成提交：' + targetUrl.slice(0, 80));
  // 暂存到 storage，popup 打开后可读取
  await chrome.storage.local.set({ pendingUrl: targetUrl });
});

// ============ 消息路由 ============
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || !msg.type) return;
  switch (msg.type) {
    case 'PING_BACKEND':
      handlePingBackend(msg).then(sendResponse).catch((e) => sendResponse({ success: false, error: String(e) }));
      return true;
    case 'SUBMIT_FROM_METADATA':
      handleSubmitFromMetadata(msg).then(sendResponse).catch((e) => sendResponse({ success: false, error: String(e) }));
      return true;
    case 'SUBMIT_PDF_URL':
      handleSubmitPdfUrl(msg).then(sendResponse).catch((e) => sendResponse({ success: false, error: String(e) }));
      return true;
    case 'POLL_EXTRACTION':
      handlePollExtraction(msg).then(sendResponse).catch((e) => sendResponse({ success: false, error: String(e) }));
      return true;
    default:
      return;
  }
});

// ============ 1. 后端连通性检测 ============
async function handlePingBackend() {
  const settings = await getSettings();
  try {
    const resp = await fetch(apiUrl('/api/v1/health', settings), { method: 'GET' });
    if (!resp.ok) return { success: false, error: `HTTP ${resp.status}` };
    const json = await resp.json();
    return { success: true, data: json };
  } catch (e) {
    return { success: false, error: String(e && e.message || e) };
  }
}

// ============ 2. 元数据驱动提交 ============
// 优先级：① 页面是 PDF → 抓取上传 ② 页面有 PDF 链接 → 抓取上传
//         ③ 否则按 URL 导入（保存 HTML）
async function handleSubmitFromMetadata(msg) {
  const meta = msg.metadata;
  if (!meta || !meta.url) return { success: false, error: '缺少元数据' };
  const settings = await getSettings();

  // 选择上传策略
  let pdfTargetUrl = null;
  if (meta.is_pdf) {
    pdfTargetUrl = meta.url;
  } else if (meta.pdf_links && meta.pdf_links.length > 0) {
    pdfTargetUrl = meta.pdf_links[0];
  }

  if (pdfTargetUrl) {
    // 抓取 PDF 二进制并上传
    const result = await fetchAndUploadPdf(pdfTargetUrl, {
      title: meta.title, doi: meta.doi, province: settings.default_province || msg.province || '',
    }, settings);
    return result;
  }
  // 走 URL 导入
  return await importFromUrl({
    url: meta.url,
    title: meta.title || '',
    province: settings.default_province || msg.province || '',
  }, settings);
}

// ============ 3. PDF 抓取 + 上传 ============
async function handleSubmitPdfUrl(msg) {
  const settings = await getSettings();
  return await fetchAndUploadPdf(msg.pdfUrl, {
    title: msg.title || '',
    doi: msg.doi || '',
    province: settings.default_province || msg.province || '',
  }, settings);
}

async function fetchAndUploadPdf(pdfUrl, fields, settings) {
  const noAuth = requireAuth(settings);
  if (noAuth) return noAuth;
  // 1. 抓取 PDF 二进制（带 referer，规避部分站点防盗链）
  const referer = (() => { try { return new URL(pdfUrl).origin; } catch { return ''; } })();
  let fetchResp;
  try {
    fetchResp = await fetch(pdfUrl, {
      method: 'GET',
      redirect: 'follow',
      headers: referer ? { 'Referer': referer } : undefined,
    });
  } catch (e) {
    return { success: false, error: '抓取 PDF 失败：' + String(e && e.message || e) };
  }
  if (!fetchResp.ok) {
    return { success: false, error: `抓取 PDF 失败：HTTP ${fetchResp.status}` };
  }
  const blob = await fetchResp.blob();
  // 校验大小（50 MB）
  if (blob.size > 50 * 1024 * 1024) {
    return { success: false, error: 'PDF 文件超过 50MB 限制' };
  }
  // 推断文件名
  let filename = 'literature.pdf';
  try {
    const u = new URL(pdfUrl);
    const last = u.pathname.split('/').filter(Boolean).pop();
    if (last && /\.pdf$/i.test(last)) filename = decodeURIComponent(last);
  } catch { /* ignore */ }
  // 若用户填了 title，使用 title 作为文件名前缀
  if (fields.title) {
    const safeTitle = fields.title.replace(/[\\/:*?"<>|]/g, '_').slice(0, 80);
    filename = `${safeTitle}.pdf`;
  }

  // 2. 上传到后端
  const fd = new FormData();
  const file = new File([blob], filename, { type: blob.type || 'application/pdf' });
  fd.append('file', file);
  if (fields.title) fd.append('title', fields.title);
  if (fields.doi) fd.append('doi', fields.doi);
  if (fields.province) fd.append('province', fields.province);

  // 不要手动设置 Content-Type，让浏览器自动加 boundary
  const uploadResp = await fetch(apiUrl('/api/v1/literatures/upload', settings), {
    method: 'POST',
    headers: authHeaders(settings),
    body: fd,
  });
  if (!uploadResp.ok) {
    const txt = await uploadResp.text().catch(() => '');
    const hint = uploadResp.status === 401 ? '（API Token 无效或已过期，请在设置页更新）' : '';
    return { success: false, error: `上传失败：HTTP ${uploadResp.status}${hint} ${txt.slice(0, 200)}` };
  }
  const json = await uploadResp.json();
  if (!json || !json.success || !json.data) {
    return { success: false, error: '上传失败：' + (json && json.message || '响应异常') };
  }
  const lit = json.data;
  notify('文献已上传', `${lit.title || filename}（ID: ${String(lit.id).slice(0, 8)}...）`);

  // 3. 触发 AI 提取（可选）
  if (settings.auto_extract) {
    await triggerExtraction(lit.id, settings);
  }
  return { success: true, data: lit, action: settings.auto_extract ? 'uploaded_and_extracting' : 'uploaded' };
}

// ============ 4. URL 导入 ============
async function importFromUrl(fields, settings) {
  const noAuth = requireAuth(settings);
  if (noAuth) return noAuth;
  const fd = new FormData();
  fd.append('url', fields.url);
  if (fields.title) fd.append('title', fields.title);
  if (fields.province) fd.append('province', fields.province);

  const resp = await fetch(apiUrl('/api/v1/literatures/from-url', settings), {
    method: 'POST',
    headers: authHeaders(settings),
    body: fd,
  });
  if (!resp.ok) {
    const txt = await resp.text().catch(() => '');
    const hint = resp.status === 401 ? '（API Token 无效或已过期，请在设置页更新）' : '';
    return { success: false, error: `URL 导入失败：HTTP ${resp.status}${hint} ${txt.slice(0, 200)}` };
  }
  const json = await resp.json();
  if (!json || !json.success || !json.data) {
    return { success: false, error: 'URL 导入失败：' + (json && json.message || '响应异常') };
  }
  const lit = json.data;
  notify('网页已导入', `${lit.title || fields.url.slice(0, 60)}（ID: ${String(lit.id).slice(0, 8)}...）`);

  if (settings.auto_extract) {
    await triggerExtraction(lit.id, settings);
  }
  return { success: true, data: lit, action: settings.auto_extract ? 'imported_and_extracting' : 'imported' };
}

// ============ 5. 触发 AI 提取 ============
async function triggerExtraction(literatureId, settings) {
  const noAuth = requireAuth(settings);
  if (noAuth) return noAuth;
  const body = {};
  if (settings.llm_model) body.model = settings.llm_model;
  if (settings.llm_base_url) body.base_url = settings.llm_base_url;

  try {
    const resp = await fetch(apiUrl(`/api/v1/literatures/${literatureId}/extraction`, settings), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders(settings) },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      const txt = await resp.text().catch(() => '');
      const hint = resp.status === 401 ? '（API Token 无效或已过期，请在设置页更新）' : '';
      notify('提取任务提交失败', `HTTP ${resp.status}${hint} ${txt.slice(0, 120)}`);
      return { success: false, error: `触发提取失败：HTTP ${resp.status}${hint}` };
    }
    const json = await resp.json();
    notify('AI 提取已启动', `文献 ID: ${String(literatureId).slice(0, 8)}...`);
    return { success: true, data: json.data };
  } catch (e) {
    notify('提取任务提交失败', String(e && e.message || e));
    return { success: false, error: String(e && e.message || e) };
  }
}

// ============ 6. 轮询提取状态 ============
async function handlePollExtraction(msg) {
  const settings = await getSettings();
  const id = msg.literatureId;
  if (!id) return { success: false, error: '缺少 literatureId' };
  const noAuth = requireAuth(settings);
  if (noAuth) return noAuth;
  try {
    const resp = await fetch(apiUrl(`/api/v1/literatures/${id}/extraction/status`, settings), { method: 'GET', headers: authHeaders(settings) });
    if (!resp.ok) return { success: false, error: `HTTP ${resp.status}` };
    const json = await resp.json();
    return { success: true, data: json.data };
  } catch (e) {
    return { success: false, error: String(e && e.message || e) };
  }
}

// ============ 7. 桌面通知 ============
function notify(title, message) {
  try {
    chrome.notifications.create({
      type: 'basic',
      iconUrl: 'icons/icon128.png',
      title: '[抗体图谱] ' + title,
      message: message,
      priority: 2,
    });
  } catch (e) {
    console.warn('[AntibodyMap] 通知失败:', e);
  }
}
