import React from 'react';
import { Card, Row, Col, Button, Input, Select, Divider, InputNumber } from 'antd';
import { FileTextOutlined } from '@ant-design/icons';
import ProvinceSelector from './ProvinceSelector';

interface Props {
  taskType: string;
  taskTime: string;
  taskLocation: string;
  personnelCount: number | null;
  personnelGender: string;
  personnelAge: string;
  personnelVaccinationHistory: string;
  strategyTitle: string;
  loading: boolean;
  onTaskTypeChange: (v: string) => void;
  onTaskTimeChange: (v: string) => void;
  onTaskLocationChange: (v: string) => void;
  onPersonnelCountChange: (v: number | null) => void;
  onPersonnelGenderChange: (v: string) => void;
  onPersonnelAgeChange: (v: string) => void;
  onPersonnelVaccinationHistoryChange: (v: string) => void;
  onStrategyTitleChange: (v: string) => void;
  onGenerate: () => void;
}

const StrategyReportForm: React.FC<Props> = ({
  taskType, taskTime, taskLocation, personnelCount,
  personnelGender, personnelAge, personnelVaccinationHistory,
  strategyTitle, loading,
  onTaskTypeChange, onTaskTimeChange, onTaskLocationChange,
  onPersonnelCountChange, onPersonnelGenderChange, onPersonnelAgeChange,
  onPersonnelVaccinationHistoryChange, onStrategyTitleChange,
  onGenerate,
}) => (
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
    <Row style={{ marginTop: 16 }}>
      <Col>
        <Button type="primary" icon={<FileTextOutlined />} onClick={onGenerate} loading={loading}>生成疫苗接种策略报告</Button>
      </Col>
    </Row>
  </Card>
);

export default StrategyReportForm;
