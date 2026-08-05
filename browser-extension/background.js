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
  llm_api_key: '',
  llm_base_url: '',
  default_province: '',
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
async function getSettings() {
  const { settings } = await chrome.storage.local.get('settings');
  return { ...DEFAULT_SETTINGS, ...(settings || {}) };
}

function apiUrl(path, settings) {
  const base = (settings.backend_url || '').replace(/\/+$/, '');
  return `${base}${path}`;
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
    body: fd,
  });
  if (!uploadResp.ok) {
    const txt = await uploadResp.text().catch(() => '');
    return { success: false, error: `上传失败：HTTP ${uploadResp.status} ${txt.slice(0, 200)}` };
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
  const fd = new FormData();
  fd.append('url', fields.url);
  if (fields.title) fd.append('title', fields.title);
  if (fields.province) fd.append('province', fields.province);

  const resp = await fetch(apiUrl('/api/v1/literatures/from-url', settings), {
    method: 'POST',
    body: fd,
  });
  if (!resp.ok) {
    const txt = await resp.text().catch(() => '');
    return { success: false, error: `URL 导入失败：HTTP ${resp.status} ${txt.slice(0, 200)}` };
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
  const body = {};
  if (settings.llm_model) body.model = settings.llm_model;
  if (settings.llm_api_key) body.api_key = settings.llm_api_key;
  if (settings.llm_base_url) body.base_url = settings.llm_base_url;

  try {
    const resp = await fetch(apiUrl(`/api/v1/literatures/${literatureId}/extraction`, settings), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      const txt = await resp.text().catch(() => '');
      notify('提取任务提交失败', `HTTP ${resp.status} ${txt.slice(0, 120)}`);
      return { success: false, error: `触发提取失败：HTTP ${resp.status}` };
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
  try {
    const resp = await fetch(apiUrl(`/api/v1/literatures/${id}/extraction/status`, settings), { method: 'GET' });
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
