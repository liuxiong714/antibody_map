import React, { useEffect, useState } from 'react';
import { Card, Row, Col, Button, Input, Select, Tag, Space } from 'antd';
import { FileTextOutlined, RobotOutlined, SettingOutlined, ProfileOutlined } from '@ant-design/icons';
import DiseaseSelector from './DiseaseSelector';
import ProvinceSelector from './ProvinceSelector';
import MapSelector from './MapSelector';
import ModelManager from './ModelManager';
import { getModels } from '../services/map';
import { ModelOption } from '../types';

interface TemplateOption {
  value: string;
  label: string;
}

interface Props {
  disease: string;
  dataType: string;
  province: string;
  language: string;
  title: string;
  model: string;
  loading: boolean;
  templateId?: string;
  templates?: TemplateOption[];
  isAdmin?: boolean;
  onDiseaseChange: (v: string) => void;
  onDataTypeChange: (v: string) => void;
  onProvinceChange: (v: string) => void;
  onLanguageChange: (v: string) => void;
  onTitleChange: (v: string) => void;
  onModelChange: (v: string) => void;
  onTemplateChange?: (v: string) => void;
  onManageTemplates?: () => void;
  onGenerate: () => void;
}

const AntibodyReportForm: React.FC<Props> = ({
  disease, dataType, province, language, title, model, loading,
  templateId, templates = [], isAdmin = false,
  onDiseaseChange, onDataTypeChange, onProvinceChange,
  onLanguageChange, onTitleChange, onModelChange,
  onTemplateChange, onManageTemplates, onGenerate,
}) => {
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([]);
  const [modelManagerVisible, setModelManagerVisible] = useState(false);

  const fetchModels = async () => {
    try {
      const data = await getModels();
      const options: ModelOption[] = [
        ...data.local,
        ...data.remote,
      ];
      setModelOptions(options);
    } catch (err) {
      console.error('[AntibodyReportForm] 获取模型列表失败:', err);
    }
  };

  useEffect(() => { fetchModels(); }, []);

  // 分组选项用于 Select OptGroup
  const localOptions = modelOptions.filter(m => m.group === 'local');
  const remoteOptions = modelOptions.filter(m => m.group === 'remote');

  const selectOptions: any[] = [];
  if (localOptions.length > 0) {
    selectOptions.push({
      label: <span><RobotOutlined /> 本地模型</span>,
      options: localOptions.map(m => ({ value: m.value, label: m.label })),
    });
  }
  if (remoteOptions.length > 0) {
    selectOptions.push({
      label: <span><SettingOutlined /> 远程模型</span>,
      options: remoteOptions.map(m => ({ value: m.value, label: m.label })),
    });
  }

  // 找到当前选中的模型标签
  const selectedOption = modelOptions.find(m => m.value === model);
  const selectedLabel = selectedOption ? selectedOption.label : undefined;

  return (
    <>
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={[16, 12]} align="middle">
          <Col><DiseaseSelector value={disease} onChange={onDiseaseChange} /></Col>
          <Col><MapSelector value={dataType} onChange={onDataTypeChange} /></Col>
          <Col><ProvinceSelector value={province} onChange={onProvinceChange} /></Col>
          <Col>
            <Select value={language} onChange={onLanguageChange} style={{ width: 120 }}
              options={[{ value: 'zh', label: '中文' }, { value: 'en', label: 'English' }]} />
          </Col>
          <Col>
            <Select
              value={model || undefined}
              onChange={onModelChange}
              style={{ width: 220 }}
              placeholder="选择模型"
              options={selectOptions}
              prefix={<RobotOutlined />}
              allowClear
            />
          </Col>
          <Col>
            <Button icon={<SettingOutlined />} onClick={() => setModelManagerVisible(true)}>
              管理远程模型
            </Button>
          </Col>
          <Col><Input placeholder="自定义报告标题（选填）" value={title} onChange={(e) => onTitleChange(e.target.value)} style={{ width: 260 }} /></Col>
          <Col><Button type="primary" icon={<FileTextOutlined />} onClick={onGenerate} loading={loading}>生成报告</Button></Col>
          <Col span={24}>
            <Space wrap>
              <Select
                value={templateId || undefined}
                onChange={onTemplateChange}
                style={{ width: 300 }}
                placeholder="选择报告模板（默认使用默认模板）"
                prefix={<ProfileOutlined />}
                allowClear
                options={templates}
              />
              {isAdmin && (
                <Button icon={<ProfileOutlined />} onClick={onManageTemplates}>管理模板</Button>
              )}
            </Space>
          </Col>
        </Row>
        {selectedLabel && (
          <div style={{ marginTop: 8, color: '#888' }}>
            <Tag icon={<RobotOutlined />} color="blue">{selectedLabel}</Tag>
          </div>
        )}
      </Card>

      <ModelManager
        visible={modelManagerVisible}
        onClose={() => setModelManagerVisible(false)}
        onSaved={fetchModels}
      />
    </>
  );
};

export default AntibodyReportForm;