import { DiseaseKey } from '../types';

export interface DiseaseOption {
  key: DiseaseKey | '';
  name_cn: string;
  name_en: string;
  category: string;
}

export const DISEASES: DiseaseOption[] = [
  { key: 'measles', name_cn: '麻疹', name_en: 'Measles', category: '疫苗可预防' },
  { key: 'mumps', name_cn: '腮腺炎', name_en: 'Mumps', category: '疫苗可预防' },
  { key: 'rubella', name_cn: '风疹', name_en: 'Rubella', category: '疫苗可预防' },
  { key: 'pertussis', name_cn: '百日咳', name_en: 'Pertussis', category: '疫苗可预防' },
  { key: 'diphtheria', name_cn: '白喉', name_en: 'Diphtheria', category: '疫苗可预防' },
  { key: 'tetanus', name_cn: '破伤风', name_en: 'Tetanus', category: '疫苗可预防' },
  { key: 'hepatitis_b', name_cn: '乙肝', name_en: 'Hepatitis B', category: '疫苗可预防' },
  { key: 'hepatitis_a', name_cn: '甲肝', name_en: 'Hepatitis A', category: '疫苗可预防' },
  { key: 'polio', name_cn: '脊灰', name_en: 'Polio', category: '疫苗可预防' },
  { key: 'influenza', name_cn: '流感', name_en: 'Influenza', category: '呼吸道' },
  { key: 'covid19', name_cn: '新冠', name_en: 'COVID-19', category: '呼吸道' },
  { key: 'meningitis', name_cn: '流脑', name_en: 'Meningococcal Meningitis', category: '疫苗可预防' },
  { key: 'varicella', name_cn: '水痘', name_en: 'Varicella', category: '疫苗可预防' },
  { key: 'hfmd', name_cn: '手足口', name_en: 'HFMD', category: '其他传染病' },
  { key: 'rotavirus', name_cn: '轮状病毒', name_en: 'Rotavirus', category: '疫苗可预防' },
];

export const DATA_TYPE_LABEL: Record<string, string> = {
  seroprevalence: '血清阳性率',
  gmc: 'GMC 几何平均浓度',
};

export const CONFIDENCE_META: Record<string, { color: string; label: string }> = {
  high: { color: 'green', label: '高' },
  medium: { color: 'gold', label: '中' },
  low: { color: 'red', label: '低' },
};

export const REVIEW_META: Record<string, { color: string; label: string }> = {
  pending: { color: 'default', label: '待审核' },
  approved: { color: 'green', label: '已通过' },
  rejected: { color: 'red', label: '已驳回' },
};

export const EXTRACTION_STATUS_META: Record<string, { color: string; label: string }> = {
  pending: { color: 'default', label: '待处理' },
  processing: { color: 'processing', label: '提取中' },
  done: { color: 'green', label: '已完成' },
  failed: { color: 'red', label: '失败' },
};

export interface ModelOption {
  value: string;
  label: string;
  vendor: 'deepseek' | 'openai' | 'qwen' | 'ollama' | '';
  description?: string;
}

export const MODEL_OPTIONS: ModelOption[] = [
  { value: '', label: '默认配置（后端配置的模型）', vendor: '', description: '使用后端 .env 中 LLM_MODEL 配置的默认模型，当前为 DeepSeek Chat（远程 API），无需额外填写 API Key' },
  { value: 'deepseek-chat', label: 'DeepSeek Chat（推荐·远程API）', vendor: 'deepseek', description: 'DeepSeek 远程 API，性价比高，需填写 DeepSeek API Key' },
  { value: 'deepseek-reasoner', label: 'DeepSeek R1（远程API）', vendor: 'deepseek', description: 'DeepSeek R1 推理模型，适合复杂表格，速度较慢，需填写 API Key' },
  { value: 'gpt-4o-mini', label: 'GPT-4o-mini（远程API）', vendor: 'openai', description: 'OpenAI GPT-4o-mini，速度快成本低，需填写 OpenAI API Key' },
  { value: 'gpt-4o', label: 'GPT-4o（远程API）', vendor: 'openai', description: 'OpenAI GPT-4o，提取精度最高，成本较高，需填写 OpenAI API Key' },
  { value: 'qwen2.5-7b', label: 'Qwen2.5-7B（远程API）', vendor: 'qwen', description: '阿里通义千问远程 API，需填写 DashScope API Key' },
  { value: 'ollama:qwen3:32b', label: 'Qwen3:32B（本地·Ollama）', vendor: 'ollama', description: '通过 Ollama 本地部署的 Qwen3:32B 模型，无需 API Key，需先在本地运行 ollama serve' },
  { value: 'ollama:qwen2.5:14b', label: 'Qwen2.5:14B（本地·Ollama）', vendor: 'ollama', description: '通过 Ollama 本地部署的 Qwen2.5:14B 模型，无需 API Key，需先在本地运行 ollama serve' },
  { value: 'ollama:llama3.1:8b', label: 'Llama3.1:8B（本地·Ollama）', vendor: 'ollama', description: '通过 Ollama 本地部署的 Llama3.1:8B 模型，无需 API Key，需先在本地运行 ollama serve' },
  { value: 'ollama:custom', label: '自定义本地模型（Ollama）', vendor: 'ollama', description: '手动输入 Ollama 模型名称，如 glm4:9b、phi3:14b 等，需先在本地 ollama pull 该模型' },
];

export const VENDOR_INFO: Record<string, { name: string; apiKeyLabel: string; baseUrlLabel: string; defaultBaseUrl: string; isLocal?: boolean }> = {
  deepseek: { name: 'DeepSeek', apiKeyLabel: 'DeepSeek API Key', baseUrlLabel: 'API Base URL', defaultBaseUrl: 'https://api.deepseek.com' },
  openai: { name: 'OpenAI', apiKeyLabel: 'OpenAI API Key', baseUrlLabel: 'API Base URL', defaultBaseUrl: 'https://api.openai.com/v1' },
  qwen: { name: 'Qwen', apiKeyLabel: 'Qwen API Key（DashScope）', baseUrlLabel: 'API Base URL', defaultBaseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  ollama: { name: 'Ollama（本地）', apiKeyLabel: 'API Key（本地部署通常无需填写）', baseUrlLabel: 'Ollama 服务地址', defaultBaseUrl: 'http://localhost:11434/v1', isLocal: true },
  '': { name: '', apiKeyLabel: '', baseUrlLabel: '', defaultBaseUrl: '' },
};

export const SERO_COLOR_STOPS = [
  { min: 0, color: '#f0f9e8' },
  { min: 20, color: '#bae4bc' },
  { min: 40, color: '#7bccc4' },
  { min: 60, color: '#43a2ca' },
  { min: 80, color: '#0868ac' },
];

export const GMC_COLOR_STOPS = [
  { min: 0, color: '#fff7ec' },
  { min: 10, color: '#fdd49e' },
  { min: 50, color: '#fdbb84' },
  { min: 200, color: '#fc8d59' },
  { min: 1000, color: '#d7301f' },
];

export const AGE_GROUP_OPTIONS = [
  { value: '', label: '全部年龄' },
  { value: '<1岁', label: '<1岁' },
  { value: '1-4岁', label: '1-4岁' },
  { value: '5-14岁', label: '5-14岁' },
  { value: '15-59岁', label: '15-59岁' },
  { value: '>=60岁', label: '>=60岁' },
];

export const GENDER_OPTIONS = [
  { value: '', label: '全部性别' },
  { value: '男性', label: '男性' },
  { value: '女性', label: '女性' },
];

export const OCCUPATION_OPTIONS = [
  { value: '', label: '全部职业' },
  { value: '儿童', label: '儿童' },
  { value: '学生', label: '学生' },
  { value: '医护人员', label: '医护人员' },
  { value: '孕妇', label: '孕妇' },
  { value: '老年人', label: '老年人' },
  { value: '军人', label: '军人' },
  { value: '农民', label: '农民' },
  { value: '工人', label: '工人' },
];

export const PROVINCES = [
  '北京', '天津', '河北', '山西', '内蒙古', '辽宁', '吉林', '黑龙江',
  '上海', '江苏', '浙江', '安徽', '福建', '江西', '山东', '河南',
  '湖北', '湖南', '广东', '广西', '海南', '重庆', '四川', '贵州',
  '云南', '西藏', '陕西', '甘肃', '青海', '宁夏', '新疆',
  '台湾', '香港', '澳门',
];

// 数据库短名称 → DataV GeoJSON 全名的映射（ECharts 需要精确匹配 GeoJSON 中的 name）
export const PROVINCE_GEOJSON_NAME: Record<string, string> = {
  '北京': '北京市',
  '天津': '天津市',
  '河北': '河北省',
  '山西': '山西省',
  '内蒙古': '内蒙古自治区',
  '辽宁': '辽宁省',
  '吉林': '吉林省',
  '黑龙江': '黑龙江省',
  '上海': '上海市',
  '江苏': '江苏省',
  '浙江': '浙江省',
  '安徽': '安徽省',
  '福建': '福建省',
  '江西': '江西省',
  '山东': '山东省',
  '河南': '河南省',
  '湖北': '湖北省',
  '湖南': '湖南省',
  '广东': '广东省',
  '广西': '广西壮族自治区',
  '海南': '海南省',
  '重庆': '重庆市',
  '四川': '四川省',
  '贵州': '贵州省',
  '云南': '云南省',
  '西藏': '西藏自治区',
  '陕西': '陕西省',
  '甘肃': '甘肃省',
  '青海': '青海省',
  '宁夏': '宁夏回族自治区',
  '新疆': '新疆维吾尔自治区',
  '台湾': '台湾省',
  '香港': '香港特别行政区',
  '澳门': '澳门特别行政区',
};
