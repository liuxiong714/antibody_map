import { getModels, listRemoteModels } from '../services/map';
import { MODEL_OPTIONS, ModelOption } from './constants';

export interface ExtendedModelOption extends ModelOption {
  group?: 'local' | 'remote';
  is_default?: boolean;
  // 远程 API 模型：model_config_id 为 api_model_config 表的配置 ID，model_name 为真实模型名
  model_config_id?: string;
  model_name?: string;
}

// 静态内置远程模型（不含本地 Ollama 项；本地统一由后端 /models 提供，保证各功能一致）
const STATIC_REMOTE_OPTIONS: ModelOption[] = MODEL_OPTIONS.filter(
  (o) => o.value !== '' && o.vendor !== 'ollama'
);

// 静态本地回退模型（后端 /models 拉取失败时兜底，保证原有功能不受影响）
const FALLBACK_LOCAL_OPTIONS: ModelOption[] = MODEL_OPTIONS.filter(
  (o) => o.vendor === 'ollama' && o.value !== 'ollama:custom'
);

const DEFAULT_OPTION: ModelOption = {
  value: '',
  label: '默认配置（后端配置的模型）',
  vendor: '',
  description: '使用后端 .env 中 LLM_MODEL 配置的默认模型',
};

const CUSTOM_LOCAL_OPTION: ModelOption = {
  value: 'ollama:custom',
  label: '自定义本地模型（Ollama）',
  vendor: 'ollama',
  description: '手动输入 Ollama 模型名称，如 glm4:9b、phi3:14b 等，需先在本地 ollama pull 该模型',
};

/**
 * 构建统一的模型选择候选项（默认配置 + 静态远程 + 动态本地 + 自定义本地）。
 *
 * 本地模型统一来自后端 /models（在系统设置「本地模型配置」中维护），
 * 因此文献提取、报告生成等各功能模块的本地模型候选项始终一致。
 * 本地模型值统一带 ollama: 前缀，与文献模块原有的 vendor 判定逻辑兼容。
 */
export async function buildModelOptions(): Promise<ExtendedModelOption[]> {
  const options: ExtendedModelOption[] = [
    { ...DEFAULT_OPTION },
    ...STATIC_REMOTE_OPTIONS,
  ];
  try {
    const data = await getModels();
    const locals = (data.local || []).filter((m) => m.value !== '');
    if (locals.length > 0) {
      options.push(
        ...locals.map((m) => ({
          value: `ollama:${m.value}`,
          label: `${m.label}（本地·Ollama）`,
          vendor: 'ollama' as const,
          group: 'local' as const,
          is_default: m.is_default,
          description: '通过 Ollama 本地部署的模型，无需 API Key，需先在本地运行 ollama serve',
        })),
      );
    } else {
      options.push(...FALLBACK_LOCAL_OPTIONS);
    }
  } catch (err) {
    console.error('[modelOptions] 加载本地模型失败，回退到静态列表:', err);
    options.push(...FALLBACK_LOCAL_OPTIONS);
  }
  // 远程 API 模型（系统设置「远程模型配置」中维护的启用项）。
  // value 用 remote:<配置id> 作为唯一标识，model_name 与 model_config_id 随选项携带，
  // 提交提取时按 model_config_id 让后端读取对应配置的 API Key / Base URL。
  try {
    const remotes = await listRemoteModels();
    const active = (remotes || []).filter((r) => r && r.is_active !== false);
    if (active.length > 0) {
      options.push(
        ...active.map((r) => ({
          value: `remote:${r.id}`,
          label: `${r.name || r.model_name}（远程·API）`,
          vendor: '' as const,
          group: 'remote' as const,
          model_config_id: r.id,
          model_name: r.model_name,
          description: `通过系统配置的远程 API 调用模型 ${r.model_name}，API Key 由系统设置安全存储`,
        })),
      );
    }
  } catch (err) {
    console.error('[modelOptions] 加载远程模型配置失败:', err);
  }
  options.push({ ...CUSTOM_LOCAL_OPTION });
  return options;
}
