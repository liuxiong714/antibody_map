import React, { useEffect, useState } from 'react';
import { Card, Row, Col, Button, Input, Select, Divider, InputNumber, Space, Tag } from 'antd';
import { FileTextOutlined, RobotOutlined, SettingOutlined, ProfileOutlined } from '@ant-design/icons';
import ProvinceSelector from './ProvinceSelector';
import ModelManager from './ModelManager';
import { getModels } from '../services/map';
import { ModelOption } from '../types';

interface TemplateOption {
  value: string;
  label: string;
}

interface Props {
  taskType: string;
  taskTime: string;
  taskLocation: string;
  personnelCount: number | null;
  personnelGender: string;
  personnelAge: string;
  personnelVaccinationHistory: string;
  strategyTitle: string;
  model: string;
  loading: boolean;
  templateId?: string;
  templates?: TemplateOption[];
  isAdmin?: boolean;
  onTaskTypeChange: (v: string) => void;
  onTaskTimeChange: (v: string) => void;
  onTaskLocationChange: (v: string) => void;
  onPersonnelCountChange: (v: number | null) => void;
  onPersonnelGenderChange: (v: string) => void;
  onPersonnelAgeChange: (v: string) => void;
  onPersonnelVaccinationHistoryChange: (v: string) => void;
  onStrategyTitleChange: (v: string) => void;
  onModelChange: (v: string) => void;
  onTemplateChange?: (v: string) => void;
  onManageTemplates?: () => void;
  onGenerate: () => void;
}

const StrategyReportForm: React.FC<Props> = ({
  taskType, taskTime, taskLocation, personnelCount,
  personnelGender, personnelAge, personnelVaccinationHistory,
  strategyTitle, model, loading, templateId, templates = [], isAdmin = false,
  onTaskTypeChange, onTaskTimeChange, onTaskLocationChange,
  onPersonnelCountChange, onPersonnelGenderChange, onPersonnelAgeChange,
  onPersonnelVaccinationHistoryChange, onStrategyTitleChange, onModelChange,
  onTemplateChange, onManageTemplates, onGenerate,
}) => {
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([]);
  const [modelManagerVisible, setModelManagerVisible] = useState(false);

  const fetchModels = async () => {
    try {
      const data = await getModels();
      setModelOptions([...data.local, ...data.remote]);
    } catch (err) {
      console.error('[StrategyReportForm] 获取模型列表失败:', err);
    }
  };

  useEffect(() => { fetchModels(); }, []);

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

  const selectedOption = modelOptions.find(m => m.value === model);
  const selectedLabel = selectedOption ? selectedOption.label : undefined;

  return (
    <>
      <Card title="任务信息配置" style={{ marginBottom: 16 }}>
        <Row gutter={[16, 12]}>
          <Col span={8}>
            <div style={{ marginBottom: 4, fontWeight: 500 }}>任务类型 <span style={{ color: 'red' }}>*</span></div>
            <Select value={taskType || undefined} onChange={onTaskTypeChange} placeholder="选择任务类型" style={{ width: '100%' }}
              options={[
                { value: '维和行动', label: '维和行动' }, { value: '抗震救灾', label: '抗震救灾' },
                { value: '抗洪抢险', label: '抗洪抢险' }, { value: '国际救援', label: '国际救援' },
                { value: '野外驻训', label: '野外驻训' }, { value: '军事演习', label: '军事演习' },
                { value: '海外护航', label: '海外护航' }, { value: '联合国任务', label: '联合国任务' },
                { value: '疫情防控', label: '疫情防控' }, { value: '其他', label: '其他' },
              ]} />
          </Col>
          <Col span={8}>
            <div style={{ marginBottom: 4, fontWeight: 500 }}>任务时间 <span style={{ color: 'red' }}>*</span></div>
            <Input placeholder="如：2026年8-10月" value={taskTime} onChange={(e) => onTaskTimeChange(e.target.value)} />
          </Col>
          <Col span={8}>
            <div style={{ marginBottom: 4, fontWeight: 500 }}>任务地点 <span style={{ color: 'red' }}>*</span></div>
            <ProvinceSelector value={taskLocation} onChange={onTaskLocationChange} />
          </Col>
        </Row>
        <Divider />
        <Row gutter={[16, 12]}>
          <Col span={6}>
            <div style={{ marginBottom: 4, fontWeight: 500 }}>人员人数 <span style={{ color: 'red' }}>*</span></div>
            <InputNumber min={1} max={100000} value={personnelCount} onChange={onPersonnelCountChange} placeholder="人数" style={{ width: '100%' }} />
          </Col>
          <Col span={6}>
            <div style={{ marginBottom: 4, fontWeight: 500 }}>人员性别分布</div>
            <Input placeholder="如：男性80人，女性20人" value={personnelGender} onChange={(e) => onPersonnelGenderChange(e.target.value)} />
          </Col>
          <Col span={6}>
            <div style={{ marginBottom: 4, fontWeight: 500 }}>人员年龄范围</div>
            <Input placeholder="如：18-35岁" value={personnelAge} onChange={(e) => onPersonnelAgeChange(e.target.value)} />
          </Col>
          <Col span={6}>
            <div style={{ marginBottom: 4, fontWeight: 500 }}>自定义标题（选填）</div>
            <Input placeholder="报告标题" value={strategyTitle} onChange={(e) => onStrategyTitleChange(e.target.value)} />
          </Col>
        </Row>
        <Row style={{ marginTop: 12 }}>
          <Col span={24}>
            <div style={{ marginBottom: 4, fontWeight: 500 }}>人员疫苗接种史</div>
            <Input.TextArea rows={3} placeholder="如：已完成基础免疫，近2年未接种流感疫苗，乙肝表面抗体阳性..." value={personnelVaccinationHistory} onChange={(e) => onPersonnelVaccinationHistoryChange(e.target.value)} />
          </Col>
        </Row>
        <Divider />
        <Row gutter={[16, 12]} align="middle">
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
          <Col>
            <Button type="primary" icon={<FileTextOutlined />} onClick={onGenerate} loading={loading}>生成疫苗接种策略报告</Button>
          </Col>
        </Row>
        {selectedLabel && (
          <div style={{ marginTop: 8, color: '#888' }}>
            <Tag icon={<RobotOutlined />} color="blue">{selectedLabel}</Tag>
          </div>
        )}
        <Divider style={{ margin: '12px 0' }} />
        <Row>
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
      </Card>

      <ModelManager
        visible={modelManagerVisible}
        onClose={() => setModelManagerVisible(false)}
        onSaved={fetchModels}
      />
    </>
  );
};

export default StrategyReportForm;