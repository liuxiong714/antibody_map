import React from 'react';
import { Card, Row, Col, Button, Input, Select } from 'antd';
import { FileTextOutlined } from '@ant-design/icons';
import DiseaseSelector from './DiseaseSelector';
import ProvinceSelector from './ProvinceSelector';
import MapSelector from './MapSelector';

interface Props {
  disease: string;
  dataType: string;
  province: string;
  language: string;
  title: string;
  loading: boolean;
  onDiseaseChange: (v: string) => void;
  onDataTypeChange: (v: string) => void;
  onProvinceChange: (v: string) => void;
  onLanguageChange: (v: string) => void;
  onTitleChange: (v: string) => void;
  onGenerate: () => void;
}

const AntibodyReportForm: React.FC<Props> = ({
  disease, dataType, province, language, title, loading,
  onDiseaseChange, onDataTypeChange, onProvinceChange,
  onLanguageChange, onTitleChange, onGenerate,
}) => (
  <Card style={{ marginBottom: 16 }}>
    <Row gutter={[16, 12]} align="middle">
      <Col><DiseaseSelector value={disease} onChange={onDiseaseChange} /></Col>
      <Col><MapSelector value={dataType} onChange={onDataTypeChange} /></Col>
      <Col><ProvinceSelector value={province} onChange={onProvinceChange} /></Col>
      <Col>
        <Select value={language} onChange={onLanguageChange} style={{ width: 120 }}
          options={[{ value: 'zh', label: '中文' }, { value: 'en', label: 'English' }]} />
      </Col>
      <Col><Input placeholder="自定义报告标题（选填）" value={title} onChange={(e) => onTitleChange(e.target.value)} style={{ width: 260 }} /></Col>
      <Col><Button type="primary" icon={<FileTextOutlined />} onClick={onGenerate} loading={loading}>生成报告</Button></Col>
    </Row>
  </Card>
);

export default AntibodyReportForm;
