// popup.js
// 弹窗逻辑：加载元数据 → 提交 → 显示进度

document.addEventListener('DOMContentLoaded', async () => {
  const $ = (id) => document.getElementById(id);

  // ===== 1. 后端连通性检测 =====
  setStatus('detecting');
  chrome.runtime.sendMessage({ type: 'PING_BACKEND' }, (resp) => {
    if (chrome.runtime.lastError) {
      setStatus('error', '插件通信异常');
      return;
    }
    if (resp && resp.success) setStatus('ok');
    else setStatus('error', resp?.error || '后端不可达');
  });

  // ===== 2. 加载当前标签页元数据 =====
  let currentMeta = null;
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.id) {
      $('pageInfo').textContent = '无法获取当前标签页';
      return;
    }
    $('pageInfo').textContent = truncate(tab.url || '', 60);

    // PDF 文件直接走另一路径（chrome 内置 PDF 查看器无 content-script）
    if (tab.url && /\.pdf(\?|$)/i.test(tab.url)) {
      currentMeta = {
        url: tab.url,
        title: decodeURIComponent(tab.url.split('/').pop() || '').replace(/\.pdf.*$/i, '') || tab.title || 'Untitled PDF',
        authors: [], journal: '', pub_year: null, doi: '', pmid: '', abstract: '',
        is_pdf: true, page_type: 'pdf', pdf_links: [tab.url],
      };
      fillForm(currentMeta);
      $('submitBtn').disabled = false;
      return;
    }

    // 向 content-script 请求元数据
    chrome.tabs.sendMessage(tab.id, { type: 'EXTRACT_METADATA' }, (resp) => {
      if (chrome.runtime.lastError || !resp || !resp.success) {
        // content-script 可能未注入（如 chrome:// 页面）
        currentMeta = {
          url: tab.url,
          title: tab.title || '',
          authors: [], journal: '', pub_year: null, doi: '', pmid: '', abstract: '',
          is_pdf: false, page_type: 'generic', pdf_links: [],
        };
        fillForm(currentMeta);
        $('methodInfo').textContent = 'URL 导入（无法提取页面元数据）';
        $('submitBtn').disabled = !!currentMeta.url && currentMeta.url.startsWith('chrome://') ? true : false;
        return;
      }
      currentMeta = resp.data;
      fillForm(currentMeta);
      $('submitBtn').disabled = false;
    });
  } catch (e) {
    setError('初始化失败：' + String(e && e.message || e));
  }

  // ===== 3. 加载默认省份 =====
  const { settings } = await chrome.storage.local.get('settings');
  if (settings && settings.default_province) {
    $('province').value = settings.default_province;
  }

  // ===== 4. 提交按钮 =====
  $('submitBtn').addEventListener('click', async () => {
    if (!currentMeta) return;
    // 同步用户编辑过的字段
    currentMeta.title = $('title').value.trim() || currentMeta.title;
    currentMeta.doi = $('doi').value.trim();
    const province = $('province').value.trim();
    const autoExtract = $('autoExtract').checked;

    // 临时覆盖 auto_extract 设置
    const cur = await chrome.storage.local.get('settings');
    const newSettings = { ...(cur.settings || {}), auto_extract: autoExtract };
    await chrome.storage.local.set({ settings: newSettings });

    showPanel('progress');
    setStep(1, 'running', '提交中...');

    const resp = await sendMessage({
      type: 'SUBMIT_FROM_METADATA',
      metadata: currentMeta,
      province,
    });

    if (!resp || !resp.success) {
      setStep(1, 'error', '失败');
      setError(resp?.error || '提交失败');
      return;
    }
    setStep(1, 'done', '已提交');
    const lit = resp.data;
    $('progressInfo').textContent = `文献 ID: ${String(lit.id).slice(0, 8)}... | 状态: ${lit.extraction_status}`;

    if (!autoExtract || resp.action !== 'uploaded_and_extracting' && resp.action !== 'imported_and_extracting') {
      setStep(2, 'skipped', '未启用');
      setStep(3, 'done', '完成');
      $('openDetailBtn').classList.remove('hidden');
      $('openDetailBtn').dataset.litId = lit.id;
      return;
    }

    // 轮询提取状态
    setStep(2, 'running', '提取中...');
    const finalStatus = await pollExtraction(lit.id);
    if (finalStatus && (finalStatus.status === 'done')) {
      setStep(2, 'done', `提取 ${finalStatus.extracted_count || 0} 个数据点`);
      setStep(3, 'done', '完成');
      $('openDetailBtn').classList.remove('hidden');
      $('openDetailBtn').dataset.litId = lit.id;
    } else if (finalStatus && finalStatus.status === 'failed') {
      setStep(2, 'error', '提取失败');
      setStep(3, 'error', '失败');
      $('progressInfo').textContent += '（提取失败，请到 Web 端查看日志）';
      $('openDetailBtn').classList.remove('hidden');
      $('openDetailBtn').dataset.litId = lit.id;
    } else {
      setStep(2, 'error', '状态未知');
    }
  });

  // ===== 5. 查看详情按钮 =====
  $('openDetailBtn').addEventListener('click', async () => {
    const litId = $('openDetailBtn').dataset.litId;
    if (!litId) return;
    const { settings: s } = await chrome.storage.local.get('settings');
    const base = (s?.backend_url || 'http://localhost:8000').replace(/\/+$/, '');
    // 前端 web 详情页路径（假设前端在 5173 或与后端同域）
    // 优先打开后端 docs，让用户从文献列表进入
    chrome.tabs.create({ url: `${base}/docs` });
  });

  // ===== 6. 重试/重置 =====
  $('retryBtn').addEventListener('click', () => { showPanel('main'); });
  $('resetBtn').addEventListener('click', () => {
    setStep(1, 'pending', '等待中');
    setStep(2, 'pending', '等待中');
    setStep(3, 'pending', '等待中');
    $('progressInfo').textContent = '';
    $('openDetailBtn').classList.add('hidden');
    $('resetBtn').classList.add('hidden');
    showPanel('main');
  });

  // ===== 7. 打开设置 =====
  $('openOptions').addEventListener('click', (e) => {
    e.preventDefault();
    chrome.runtime.openOptionsPage();
  });

  // ===== 辅助函数 =====
  function fillForm(meta) {
    $('title').value = meta.title || '';
    $('doi').value = meta.doi || '';
    $('authors').textContent = meta.authors && meta.authors.length > 0
      ? meta.authors.slice(0, 5).join(', ') + (meta.authors.length > 5 ? ` 等 ${meta.authors.length} 人` : '')
      : '—';
    $('year').textContent = meta.pub_year || '—';
    $('journal').textContent = truncate(meta.journal || '—', 40);

    // 提交方式提示
    if (meta.is_pdf) {
      $('methodInfo').innerHTML = '<span class="tag tag-blue">PDF 文件抓取</span> 直接上传 PDF';
    } else if (meta.pdf_links && meta.pdf_links.length > 0) {
      $('methodInfo').innerHTML = `<span class="tag tag-blue">PDF 抓取</span> 从页面发现 PDF 链接`;
    } else {
      $('methodInfo').innerHTML = '<span class="tag tag-green">URL 导入</span> 保存网页内容';
    }
  }

  function setStatus(state, msg) {
    const dot = $('statusDot');
    const text = $('statusText');
    dot.className = 'status-dot ' + state;
    if (state === 'ok') text.textContent = '后端已连接';
    else if (state === 'detecting') text.textContent = '检测中...';
    else if (state === 'error') text.textContent = msg || '后端不可达';
  }

  function showPanel(name) {
    $('mainPanel').classList.toggle('hidden', name !== 'main');
    $('progressPanel').classList.toggle('hidden', name !== 'progress');
    $('errorPanel').classList.toggle('hidden', name !== 'error');
  }

  function setStep(n, state, msg) {
    const step = $('step' + n);
    const status = $('step' + n + 'Status');
    step.className = 'step ' + state;
    status.textContent = msg;
  }

  function setError(msg) {
    $('errorMsg').textContent = msg;
    showPanel('error');
  }

  function sendMessage(msg) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage(msg, (resp) => {
        if (chrome.runtime.lastError) {
          resolve({ success: false, error: chrome.runtime.lastError.message });
        } else {
          resolve(resp);
        }
      });
    });
  }

  async function pollExtraction(litId) {
    const maxAttempts = 60; // 最多轮询 60 次
    const intervalMs = 3000; // 每 3 秒一次
    for (let i = 0; i < maxAttempts; i++) {
      await sleep(intervalMs);
      const resp = await sendMessage({ type: 'POLL_EXTRACTION', literatureId: litId });
      if (!resp || !resp.success) continue;
      const s = resp.data;
      $('progressInfo').textContent = `状态: ${s.status} | 已提取: ${s.extracted_count || 0} 个数据点`;
      if (s.status === 'done' || s.status === 'failed') return s;
    }
    return null;
  }

  function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
  function truncate(s, n) { return (s && s.length > n) ? s.slice(0, n) + '...' : (s || ''); }
});
