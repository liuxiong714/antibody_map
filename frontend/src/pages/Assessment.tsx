import React, { useState, useRef } from 'react';
import { Card, Button, Row, Col, Statistic, Spin, Empty, Progress, Tag, message, InputNumber, Table, Tooltip, Collapse, Alert, Drawer, Select, Slider, Space } from 'antd';
import type { TableProps } from 'antd';
import { SafetyOutlined, InfoCircleOutlined, CheckCircleFilled, SettingOutlined } from '@ant-design/icons';
import ReactECharts from '../components/EChart';
import DiseaseSelector from '../components/DiseaseSelector';
import ProvinceSelector from '../components/ProvinceSelector';
import { getImmuneBarrier } from '../services/map';
import { ImmuneBarrierData, CatalyticModel } from '../types';

interface AssumptionState {
  life_expectancy: number;      // 期望寿命（年）
  seroreversion_mu: number;     // 0 | 0.01 | 0.02
  hit_source_override: string;  // default | who | literature | foi
}

const DEFAULT_ASSUMPTIONS: AssumptionState = {
  life_expectancy: 75,
  seroreversion_mu: 0,
  hit_source_override: 'default',
};

const SEROREVERSION_OPTIONS = [
  { value: 0, label: '无血清转阴（μ=0）' },
  { value: 0.01, label: 'μ = 0.01 /年' },
  { value: 0.02, label: 'μ = 0.02 /年' },
];

const HIT_SOURCE_OPTIONS = [
  { value: 'default', label: '自动（FOI > WHO > 文献 R0）' },
  { value: 'foi', label: 'FOI 估算' },
  { value: 'who', label: 'WHO 建议' },
  { value: 'literature', label: '文献 R0' },
];

const STATUS_CONFIG: Record<string, { color: string; label: string }> = {
  established: { color: '#52c41a', label: '免疫屏障已建立' },
  borderline: { color: '#faad14', label: '接近但未完全建立' },
  insufficient: { color: '#ff4d4f', label: '免疫屏障不足' },
  undetermined: { color: '#bfbfbf', label: '数据不足' },
  no_data: { color: '#999', label: '暂无数据' },
};

const HIT_SOURCE_LABEL: Record<string, string> = {
  foi: 'FOI 估算',
  mle_foi: 'FOI 估算',
  who: 'WHO 建议',
  ref_r0: '文献 R0',
  literature_r0: '文献 R0',
  none: '无',
};

// 催化模型参数展示辅助：把 params 字典格式化为可读的参数字符串
const formatModelParams = (m: CatalyticModel): string => {
  const p = m.params || {};
  const keys = Object.keys(p).filter((k) => !k.endsWith('_ci_lower') && !k.endsWith('_ci_upper'));
  if (!keys.length) return '-';
  return keys.map((k) => {
    const v = p[k];
    const lo = p[`${k}_ci_lower`];
    const up = p[`${k}_ci_upper`];
    if (v == null) return `${k}: -`;
    if (lo != null && up != null) return `${k}: ${v} [${lo}, ${up}]`;
    return `${k}: ${v}`;
  }).join('；');
};

interface ProvinceMatrixRow {
  province: string;
  data_point_count: number;
  total_samples: number;
  weighted_positivity_rate: number | null;
  weighted_avg_foi_per_year: number | null;
  estimated_r0_from_foi: number | null;
  hit_target_percent: number | null;
  status: string;
}

const Assessment: React.FC = () => {
  const [disease, setDisease] = useState('');
  const [province, setProvince] = useState('');
  const [yearStart, setYearStart] = useState<number | null>(null);
  const [yearEnd, setYearEnd] = useState<number | null>(null);
  const [ageMin, setAgeMin] = useState<number | null>(null);
  const [ageMax, setAgeMax] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ImmuneBarrierData | null>(null);

  // 假设与参数：三个控件即改即刷（防抖 500ms 后自动重查）
  const [assumptions, setAssumptions] = useState<AssumptionState>(DEFAULT_ASSUMPTIONS);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const assumptionsRef = useRef(assumptions);
  assumptionsRef.current = assumptions; // 每次渲染同步最新值，供防抖回调读取
  const diseaseRef = useRef(disease);
  diseaseRef.current = disease;
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleAssumptionChange = (patch: Partial<AssumptionState>) => {
    setAssumptions((prev) => ({ ...prev, ...patch }));
    // 防抖 500ms：参数连续调整时只发最后一次请求
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      if (diseaseRef.current) handleQuery();
    }, 500);
  };

  const handleQuery = async () => {
    if (!disease) { message.warning('请选择疾病'); return; }
    setLoading(true);
    setResult(null);
    try {
      const a = assumptionsRef.current;
      const params: Record<string, unknown> = { disease };
      if (province) params.province = province;
      if (yearStart) params.year_start = yearStart;
      if (yearEnd) params.year_end = yearEnd;
      if (ageMin != null) params.age_min = ageMin;
      if (ageMax != null) params.age_max = ageMax;
      if (a.life_expectancy !== DEFAULT_ASSUMPTIONS.life_expectancy) params.life_expectancy = a.life_expectancy;
      if (a.seroreversion_mu > 0) params.seroreversion_mu = a.seroreversion_mu;
      if (a.hit_source_override !== 'default') params.hit_source_override = a.hit_source_override;
      const resp = await getImmuneBarrier(params);
      setResult(resp);
    } catch {
      message.error('查询失败');
    } finally {
      setLoading(false);
    }
  };

  // 当前假设串（灰色小字展示）
  const assumptionText = [
    `期望寿命 ${assumptions.life_expectancy} 年`,
    assumptions.seroreversion_mu > 0 ? `血清转阴率 μ=${assumptions.seroreversion_mu}/年` : '无血清转阴',
    assumptions.hit_source_override !== 'default'
      ? `HIT 来源=${HIT_SOURCE_OPTIONS.find((o) => o.value === assumptions.hit_source_override)?.label ?? assumptions.hit_source_override}`
      : 'HIT 来源=自动',
  ].join('；');

  const cfg = result ? STATUS_CONFIG[result.status] || STATUS_CONFIG.no_data : null;
  const rate = result?.summary?.weighted_positivity_rate;
  const hitTarget = result?.summary?.hit_target_used_percent ?? result?.who_threshold;
  const hitSource = result?.summary?.hit_target_source ?? 'none';
  const recommendedModel = result?.summary?.recommended_model ?? null;
  const recommendedLabel = result?.summary?.models?.find((m) => m.name === recommendedModel)?.label
    ?? (recommendedModel ? recommendedModel.replace(/_/g, ' ') : '');

  const progressPercent = (hitTarget && rate != null) ? Math.min((rate / hitTarget) * 100, 100) : 0;

  // ECharts yearly trend
  const trendOption = result?.yearly_trend?.length ? {
    xAxis: { type: 'category', data: result.yearly_trend.map((t) => t.year) },
    yAxis: { type: 'value', name: '阳性率 (%)' },
    tooltip: { trigger: 'axis' },
    series: [
      {
        type: 'line', data: result.yearly_trend.map((t) => t.weighted_positivity),
        markLine: hitTarget ? {
          silent: true,
          data: [{ yAxis: hitTarget, label: { formatter: `阈值: ${hitTarget}%` }, lineStyle: { color: '#ff4d4f', type: 'dashed' } }],
        } : undefined,
      },
    ],
  } : null;

  // 年龄分层柱状图（叠加催化模型拟合曲线）
  const fittedCurve = result?.summary?.fitted_curve || [];
  // 把拟合曲线映射到每个年龄组中点的预测值（用于在分类 x 轴上叠加）
  const fittedByGroup = result?.age_groups?.length ? result.age_groups.map((g) => {
    const [lo, hi] = g.age_range || [0, 0];
    const mid = (lo + hi) / 2;
    const near = fittedCurve.reduce((acc, pt) => (Math.abs(pt.age - mid) < Math.abs(acc.age - mid) ? pt : acc), fittedCurve[0]);
    return near ? near.prevalence : null;
  }) : [];
  const ageChartOption = result?.age_groups?.length ? {
    xAxis: {
      type: 'category',
      data: result.age_groups.map((g) => g.age_group),
      axisLabel: { interval: 0 },
    },
    yAxis: { type: 'value', name: '阳性率 (%)' },
    tooltip: {
      trigger: 'axis',
      formatter: (params: Array<{ dataIndex: number; value: number }>) => {
        const idx = params[0]?.dataIndex;
        if (idx == null || !result.age_groups) return '';
        const g = result.age_groups[idx];
        return `${g.age_group}<br/>阳性率: ${g.weighted_positivity_rate ?? '-'}%<br/>FOI: ${g.weighted_avg_foi_per_year ?? '-'} /年<br/>样本: ${g.total_samples}<br/>状态: ${STATUS_CONFIG[g.status]?.label ?? g.status}`;
      },
    },
    series: [
      {
        type: 'bar',
        data: result.age_groups.map((g) => ({
          value: g.weighted_positivity_rate ?? 0,
          itemStyle: { color: STATUS_CONFIG[g.status]?.color ?? '#999' },
        })),
        barWidth: '40%',
        markLine: hitTarget ? {
          silent: true,
          data: [{ yAxis: hitTarget, label: { formatter: `阈值: ${hitTarget}%` }, lineStyle: { color: '#ff4d4f', type: 'dashed' } }],
        } : undefined,
      },
      ...(fittedByGroup.length && fittedByGroup.some((v) => v != null) ? [{
        type: 'line' as const,
        name: `拟合曲线（${recommendedLabel}）`,
        data: fittedByGroup,
        smooth: true,
        symbol: 'none',
        lineStyle: { color: '#722ed1', width: 3 },
        itemStyle: { color: '#722ed1' },
        z: 10,
      }] : []),
    ],
  } : null;

  // 催化模型比较：表格列定义
  const modelColumns: TableProps<CatalyticModel>['columns'] = [
    {
      title: '模型',
      dataIndex: 'label',
      key: 'label',
      width: 180,
      render: (label: string, m) => (
        <span>
          {label}
          {recommendedModel === m.name && (
            <Tag icon={<CheckCircleFilled />} color="gold" style={{ marginLeft: 6 }}>推荐</Tag>
          )}
        </span>
      ),
    },
    {
      title: '参数（λ 等，含 95%CI）',
      dataIndex: 'params',
      key: 'params',
      render: (_, m) => (m.converged ? formatModelParams(m) : <Tag color="default">未收敛</Tag>),
    },
    { title: 'logLik', dataIndex: 'loglik', key: 'loglik', width: 100, render: (v: number | null) => (v != null ? v.toFixed(2) : '-') },
    { title: 'AIC', dataIndex: 'aic', key: 'aic', width: 90, render: (v: number | null) => (v != null ? v.toFixed(2) : '-') },
    { title: 'BIC', dataIndex: 'bic', key: 'bic', width: 90, render: (v: number | null) => (v != null ? v.toFixed(2) : '-') },
    { title: 'ΔAIC', dataIndex: 'delta_aic', key: 'delta_aic', width: 80, render: (v: number | null) => (v != null ? v.toFixed(2) : '-') },
    {
      title: 'Akaike 权重',
      dataIndex: 'akaike_weight',
      key: 'weight',
      width: 110,
      render: (v: number | null) => (v != null ? `${(v * 100).toFixed(1)}%` : '-'),
    },
  ];

  // 催化模型比较：AIC 权重条形图
  const modelBarOption = (result?.summary?.models?.length || 0) ? {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 8, right: 30, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: 'value', name: 'Akaike 权重', max: 1 },
    yAxis: {
      type: 'category',
      data: (result?.summary?.models || []).map((m) => (m.name === recommendedModel ? `${m.label} ★` : m.label)),
    },
    series: [{
      type: 'bar',
      data: (result?.summary?.models || []).map((m) => ({
        value: m.akaike_weight ?? 0,
        itemStyle: { color: m.name === recommendedModel ? '#faad14' : '#1677ff' },
      })),
      barWidth: 16,
      label: {
        show: true,
        position: 'right',
        formatter: (p: { value: number }) => `${(Number(p.value) * 100).toFixed(1)}%`,
      },
    }],
  } : null;

  // 省份矩阵表格列定义
  const provinceColumns: TableProps<ProvinceMatrixRow>['columns'] = [
    { title: '省份', dataIndex: 'province', key: 'province', width: 100 },
    { title: '数据点数', dataIndex: 'data_point_count', key: 'dp', width: 80, sorter: (a, b) => a.data_point_count - b.data_point_count },
    {
      title: '样本量', dataIndex: 'total_samples', key: 'samples', width: 100,
      sorter: (a, b) => a.total_samples - b.total_samples,
      render: (v: number) => v.toLocaleString(),
    },
    {
      title: '加权阳性率', dataIndex: 'weighted_positivity_rate', key: 'wpr', width: 110,
      sorter: (a, b) => (a.weighted_positivity_rate ?? -1) - (b.weighted_positivity_rate ?? -1),
      render: (v: number | null) => v != null ? `${v}%` : '-',
    },
    {
      title: 'FOI (/年)', dataIndex: 'weighted_avg_foi_per_year', key: 'foi', width: 100,
      sorter: (a, b) => (a.weighted_avg_foi_per_year ?? -1) - (b.weighted_avg_foi_per_year ?? -1),
      render: (v: number | null) => v != null ? v.toFixed(4) : '-',
    },
    {
      title: '估算 R0', dataIndex: 'estimated_r0_from_foi', key: 'r0', width: 90,
      sorter: (a, b) => (a.estimated_r0_from_foi ?? -1) - (b.estimated_r0_from_foi ?? -1),
      render: (v: number | null) => v != null ? v.toFixed(2) : '-',
    },
    {
      title: '屏障状态', dataIndex: 'status', key: 'status', width: 140,
      filters: [
        { text: '已建立', value: 'established' },
        { text: '接近', value: 'borderline' },
        { text: '不足', value: 'insufficient' },
        { text: '数据不足', value: 'undetermined' },
      ],
      onFilter: (value, record) => record.status === value,
      render: (s: string) => {
        const c = STATUS_CONFIG[s] || STATUS_CONFIG.no_data;
        return <Tag color={c.color}>{c.label}</Tag>;
      },
    },
  ];

  return (
    <>
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={[12, 12]} align="middle">
          <Col><strong style={{ color: '#ff4d4f' }}>* </strong></Col>
          <Col><DiseaseSelector value={disease} onChange={setDisease} allowClear={false} /></Col>
          <Col><ProvinceSelector value={province} onChange={setProvince} /></Col>
          <Col><InputNumber placeholder="起始年份" value={yearStart} onChange={setYearStart} style={{ width: 110 }} /></Col>
          <Col><InputNumber placeholder="结束年份" value={yearEnd} onChange={setYearEnd} style={{ width: 110 }} /></Col>
          <Col><InputNumber placeholder="最小年龄" value={ageMin} onChange={setAgeMin} min={0} max={120} style={{ width: 110 }} /></Col>
          <Col><InputNumber placeholder="最大年龄" value={ageMax} onChange={setAgeMax} min={0} max={120} style={{ width: 110 }} /></Col>
          <Col>
            <Button type="primary" icon={<SafetyOutlined />} onClick={handleQuery} loading={loading}>
              查询免疫屏障
            </Button>
          </Col>
          <Col>
            <Button icon={<SettingOutlined />} onClick={() => setDrawerOpen(true)}>
              假设与参数
            </Button>
          </Col>
        </Row>
        <div style={{ marginTop: 8, color: '#999', fontSize: 12 }}>
          当前假设：{assumptionText}（在右侧「假设与参数」面板调整，500ms 自动刷新）
        </div>
      </Card>

      <Spin spinning={loading}>
        {!result ? (
          <Empty description="请选择疾病并点击查询" />
        ) : (
          <>
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={6}>
                <Card><Statistic title="数据点数" value={result?.summary?.total_data_points ?? 0} /></Card>
              </Col>
              <Col span={6}>
                <Card><Statistic title="涉及文献数" value={result?.summary?.total_literatures ?? 0} /></Card>
              </Col>
              <Col span={6}>
                <Card><Statistic title="总样本量" value={result?.summary?.total_samples ?? 0} formatter={(v) => (v as number).toLocaleString()} /></Card>
              </Col>
              <Col span={6}>
                <Card>
                  <Statistic
                    title="加权阳性率"
                    value={rate != null ? Number(rate).toFixed(2) + '%' : '-'}
                    valueStyle={{ color: cfg?.color }}
                  />
                </Card>
              </Col>
            </Row>

            <Card title="免疫屏障阈值对比" style={{ marginBottom: 16 }}>
              <Row align="middle" gutter={16} style={{ marginBottom: 12 }}>
                <Col>
                  <Tooltip title={`阈值来源：${HIT_SOURCE_LABEL[hitSource] ?? hitSource}`}>
                    <Tag color="blue" style={{ fontSize: 16, padding: '4px 12px' }}>
                      阈值: {hitTarget ?? '-'}%（{HIT_SOURCE_LABEL[hitSource] ?? hitSource}）
                    </Tag>
                  </Tooltip>
                </Col>
                {result?.who_threshold != null && result.summary?.hit_target_source !== 'who' && (
                  <Col>
                    <Tag color="default">WHO 推荐: {result.who_threshold}%</Tag>
                  </Col>
                )}
                <Col flex="auto">
                  <Progress
                    percent={progressPercent}
                    format={() => `${rate != null ? rate : 0}% / ${hitTarget ?? '-'}%`}
                    strokeColor={cfg?.color}
                    status={result.status === 'established' ? 'success' : 'active'}
                  />
                </Col>
                <Col>
                  <Tag color={cfg?.color} style={{ fontSize: 14, padding: '4px 12px' }}>
                    {cfg?.label}
                  </Tag>
                </Col>
              </Row>
              <Row gutter={16}>
                <Col span={6}>
                  <Statistic
                    title="加权平均 FOI"
                    value={result?.summary?.weighted_avg_foi_per_year != null ? Number(result.summary.weighted_avg_foi_per_year).toFixed(4) : '-'}
                    suffix={result?.summary?.weighted_avg_foi_per_year != null ? '/年' : ''}
                  />
                </Col>
                <Col span={6}>
                  <Statistic
                    title="估算 R0 (FOI)"
                    value={result?.summary?.estimated_r0_from_foi != null ? Number(result.summary.estimated_r0_from_foi).toFixed(2) : '-'}
                  />
                </Col>
                <Col span={6}>
                  <Statistic
                    title="HIT (FOI 估算)"
                    value={result?.summary?.hit_from_foi_percent != null ? Number(result.summary.hit_from_foi_percent).toFixed(2) + '%' : '-'}
                  />
                </Col>
                <Col span={6}>
                  <Statistic
                    title="HIT (文献 R0)"
                    value={result?.summary?.hit_from_reference_r0_percent != null ? Number(result.summary.hit_from_reference_r0_percent).toFixed(2) + '%' : '-'}
                  />
                </Col>
              </Row>
              {result?.r0_reference && result.r0_reference.typical != null && (
                <div style={{ marginTop: 8, color: '#888', fontSize: 12 }}>
                  文献 R0 参考：典型 {result.r0_reference.typical}（区间 {result.r0_reference.range_low ?? '—'} ~ {result.r0_reference.range_high ?? '—'}）
                </div>
              )}
            </Card>

            <Card
              title={<><InfoCircleOutlined /> 评估结论</>}
              style={{ marginBottom: 16, background: '#fafafa' }}
            >
              <p style={{ fontSize: 15, lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>{result.assessment}</p>
            </Card>

            {trendOption && (
              <Card title="逐年趋势" style={{ marginBottom: 16 }}>
                <ReactECharts option={trendOption} style={{ height: 350 }} />
              </Card>
            )}

            {ageChartOption && (
              <Card title="年龄分层分析" style={{ marginBottom: 16 }}>
                <ReactECharts option={ageChartOption} style={{ height: 350 }} />
                {fittedCurve.length > 0 && recommendedModel && (
                  <div style={{ marginTop: 4, color: '#722ed1', fontSize: 12 }}>
                    紫色曲线：推荐模型 {recommendedLabel}（M-recommended）的 P(a) 年龄-阳性率拟合曲线
                  </div>
                )}
              </Card>
            )}

            {(result?.summary?.models?.length || 0) > 0 && (
              <Card title="催化模型比较（MLE）" style={{ marginBottom: 16 }}>
                <Collapse
                  defaultActiveKey={['modelTable']}
                  items={[
                    {
                      key: 'modelTable',
                      label: (
                        <span>
                          模型比较
                          {recommendedModel && (
                            <Tag icon={<CheckCircleFilled />} color="gold" style={{ marginLeft: 8 }}>
                              推荐模型: {recommendedLabel}
                            </Tag>
                          )}
                          {result.summary?.n_catalytic_records != null && (
                            <span style={{ color: '#888', fontSize: 12, marginLeft: 8 }}>
                              有效年龄点: {result.summary.n_catalytic_records}
                            </span>
                          )}
                        </span>
                      ),
                      children: (
                        <>
                          <Table<CatalyticModel>
                            rowKey={(m) => m.name}
                            columns={modelColumns}
                            dataSource={result.summary?.models || []}
                            pagination={false}
                            size="small"
                            style={{ marginBottom: 16 }}
                          />
                          {modelBarOption && (
                            <>
                              <div style={{ marginBottom: 4, fontWeight: 500 }}>Akaike 权重</div>
                              <ReactECharts option={modelBarOption} style={{ height: 140 }} />
                            </>
                          )}
                          {result.summary?.modeling_notes?.length ? (
                            <div style={{ marginTop: 12 }}>
                              {result.summary.modeling_notes.map((note, i) => (
                                <div key={i} style={{ color: '#888', fontSize: 12, lineHeight: 1.7 }}>
                                  • {note}
                                </div>
                              ))}
                            </div>
                          ) : null}
                          {result.summary?.r0_assumption_note && (
                            <Alert
                              style={{ marginTop: 12 }}
                              type="warning"
                              showIcon
                              message={result.summary.r0_assumption_note}
                            />
                          )}
                        </>
                      ),
                    },
                  ]}
                />
              </Card>
            )}

            {result?.province_matrix && result.province_matrix.length > 0 && (
              <Card title="省份对比矩阵" style={{ marginBottom: 16 }}>
                <Table<ProvinceMatrixRow>
                  rowKey={(r) => r.province}
                  columns={provinceColumns}
                  dataSource={result.province_matrix}
                  pagination={{ pageSize: 10, showSizeChanger: true }}
                  size="small"
                />
              </Card>
            )}
          </>
        )}
      </Spin>

      {/* 右侧「假设与参数」抽屉：三个控件即改即刷（防抖 500ms） */}
      <Drawer
        title="假设与参数"
        placement="right"
        width={360}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      >
        <div style={{ marginBottom: 24 }}>
          <div style={{ marginBottom: 6, fontWeight: 500 }}>期望寿命 L（年）</div>
          <Slider
            min={60}
            max={85}
            step={1}
            value={assumptions.life_expectancy}
            onChange={(v: number) => handleAssumptionChange({ life_expectancy: v })}
            tooltip={{ formatter: (v?: number) => `${v} 年` }}
          />
          <div style={{ color: '#888', fontSize: 12 }}>用于 R0 = λ·L 反推群体免疫阈值 HIT = 1 - 1/R0</div>
        </div>

        <div style={{ marginBottom: 24 }}>
          <div style={{ marginBottom: 6, fontWeight: 500 }}>血清转阴率 μ（/年）</div>
          <Select
            style={{ width: '100%' }}
            value={assumptions.seroreversion_mu}
            onChange={(v: number) => handleAssumptionChange({ seroreversion_mu: v })}
            options={SEROREVERSION_OPTIONS}
          />
          <div style={{ color: '#888', fontSize: 12, marginTop: 4 }}>
            指定 μ 时催化模型 M2 以固定 μ 拟合，仅估计 λ；HIT 按 λ·L 强制重算
          </div>
        </div>

        <div style={{ marginBottom: 24 }}>
          <div style={{ marginBottom: 6, fontWeight: 500 }}>HIT 阈值来源</div>
          <Select
            style={{ width: '100%' }}
            value={assumptions.hit_source_override}
            onChange={(v: string) => handleAssumptionChange({ hit_source_override: v })}
            options={HIT_SOURCE_OPTIONS}
          />
          <div style={{ color: '#888', fontSize: 12, marginTop: 4 }}>
            默认优先级：FOI 估算 &gt; WHO 建议 &gt; 文献 R0
          </div>
        </div>

        <div style={{ borderTop: '1px solid #f0f0f0', paddingTop: 12, color: '#999', fontSize: 12 }}>
          当前假设：{assumptionText}
        </div>
      </Drawer>
    </>
  );
};

export default Assessment;
