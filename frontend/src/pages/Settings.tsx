import React, { useState } from 'react';
import { Card, Tabs, Button, Space, Tag } from 'antd';
import { SettingOutlined, UserOutlined, RobotOutlined, SafetyOutlined } from '@ant-design/icons';
import ModelManager from '../components/ModelManager';
import api from '../services/api';
import './Settings.css';

const Settings: React.FC = () => {
  const [modelModalVisible, setModelModalVisible] = useState(false);
  const [activeTab, setActiveTab] = useState('models');

  const handleModelSaved = () => {
    // 模型保存后不需要额外操作，表格已在内部刷新
  };

  const tabItems = [
    {
      key: 'models',
      label: (
        <span>
          <RobotOutlined /> 远程模型配置
        </span>
      ),
      children: (
        <Card>
          <div className="settings-section">
            <p className="settings-desc">
              配置远程LLM模型用于文献智能提取。支持OpenAI兼容API（包括OpenAI、DeepSeek、Ollama等）。
              创建/更新/删除操作仅限管理员访问。
            </p>
            <Button type="primary" onClick={() => setModelModalVisible(true)}>
              管理远程模型
            </Button>
          </div>
        </Card>
      ),
    },
    {
      key: 'system',
      label: (
        <span>
          <SafetyOutlined /> 系统信息
        </span>
      ),
      children: (
        <Card>
          <div className="system-info">
            <div className="system-info-item">
              <span className="label">项目名称</span>
              <span className="value">Antibody Map</span>
            </div>
            <div className="system-info-item">
              <span className="label">版本</span>
              <span className="value"><Tag color="blue">v1.7.1</Tag></span>
            </div>
            <div className="system-info-item">
              <span className="label">功能特性</span>
              <div className="value">
                <Space wrap>
                  <Tag color="green">文献智能提取</Tag>
                  <Tag color="green">交互式地图</Tag>
                  <Tag color="green">多维度分析</Tag>
                  <Tag color="green">JWT认证</Tag>
                  <Tag color="green">用户权限管理</Tag>
                  <Tag color="green">标签分类</Tag>
                  <Tag color="green">Word导出</Tag>
                </Space>
              </div>
            </div>
            <div className="system-info-item">
              <span className="label">项目地址</span>
              <span className="value">
                <a href="https://github.com/liuxiong714/antibody_map" target="_blank" rel="noopener noreferrer">
                  github.com/liuxiong714/antibody_map
                </a>
              </span>
            </div>
          </div>
        </Card>
      ),
    },
  ];

  return (
    <div className="settings-page">
      <Card
        title={<><SettingOutlined /> 系统设置</>}
        className="settings-card"
      >
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={tabItems}
        />
      </Card>

      <ModelManager
        visible={modelModalVisible}
        onClose={() => setModelModalVisible(false)}
        onSaved={handleModelSaved}
      />
    </div>
  );
};

export default Settings;
