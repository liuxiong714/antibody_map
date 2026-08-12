// options.js - 设置页逻辑
document.addEventListener('DOMContentLoaded', async () => {
  const $ = (id) => document.getElementById(id);

  const DEFAULT_SETTINGS = {
    backend_url: 'http://localhost:8000',
    auto_extract: true,
    llm_model: '',
    llm_api_key: '',
    llm_base_url: '',
    default_province: '',
  };

  // 加载已存配置
  const { settings } = await chrome.storage.local.get('settings');
  const s = { ...DEFAULT_SETTINGS, ...(settings || {}) };
  $('backend_url').value = s.backend_url;
  $('default_province').value = s.default_province;
  $('auto_extract').checked = !!s.auto_extract;
  $('llm_model').value = s.llm_model;
  $('llm_api_key').value = s.llm_api_key;
  $('llm_base_url').value = s.llm_base_url;

  function showStatus(type, msg) {
    const el = $('statusMsg');
    el.className = 'status-msg ' + (type === 'ok' ? 'ok' : 'err');
    el.textContent = msg;
    el.style.display = 'block';
    setTimeout(() => { el.style.display = 'none'; }, 5000);
  }

  // 保存设置
  $('saveBtn').addEventListener('click', async () => {
    const newSettings = {
      backend_url: $('backend_url').value.trim() || DEFAULT_SETTINGS.backend_url,
      default_province: $('default_province').value.trim(),
      auto_extract: $('auto_extract').checked,
      llm_model: $('llm_model').value.trim(),
      llm_api_key: $('llm_api_key').value.trim(),
      llm_base_url: $('llm_base_url').value.trim(),
    };
    if (!/^https?:\/\/.+/.test(newSettings.backend_url)) {
      showStatus('err', '后端地址格式错误，需以 http:// 或 https:// 开头');
      return;
    }
    await chrome.storage.local.set({ settings: newSettings });
    showStatus('ok', '设置已保存');
  });

  // 测试连通性（先保存当前输入，再 ping，确保测试的是用户填写的地址）
  $('testBtn').addEventListener('click', async () => {
    const url = $('backend_url').value.trim();
    if (!url) { showStatus('err', '请填写后端地址'); return; }
    if (!/^https?:\/\/.+/.test(url)) { showStatus('err', '后端地址格式错误'); return; }
    // 先保存
    await chrome.storage.local.set({
      settings: {
        backend_url: url,
        default_province: $('default_province').value.trim(),
        auto_extract: $('auto_extract').checked,
        llm_model: $('llm_model').value.trim(),
        llm_api_key: $('llm_api_key').value.trim(),
        llm_base_url: $('llm_base_url').value.trim(),
      },
    });
    $('testBtn').disabled = true;
    $('testBtn').textContent = '测试中...';
    chrome.runtime.sendMessage({ type: 'PING_BACKEND' }, (resp) => {
      $('testBtn').disabled = false;
      $('testBtn').textContent = '测试后端连通性';
      if (chrome.runtime.lastError) {
        showStatus('err', '通信异常：' + chrome.runtime.lastError.message);
        return;
      }
      if (resp && resp.success) {
        showStatus('ok', '连接成功！后端响应正常');
      } else {
        showStatus('err', '连接失败：' + (resp?.error || '请检查地址和后端服务'));
      }
    });
  });
});
