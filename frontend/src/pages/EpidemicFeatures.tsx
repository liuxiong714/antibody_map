import React, { useCallback, useEffect, useState } from 'react';
import {
  Card, Row, Col, Statistic, Table, Tabs, Select, Space, Tag,
  Empty, Spin, Divider, message, type TabsProps,
} from 'antd';
import { useTranslation } from 'react-i18next';
import { DISEASES, PROVINCES, DATA_TYPE_LABEL } from '../utils/constants';
import * as epidemicSvc from '../services/epidemic';
import type {
  EpidemicOverview, EpidemicByProvince, EpidemicDataPoint,
  PathogenMonitoringResult, DistEntry,
} from '../services/epidemic';

const EPIDEMIC_COLS: { key: string; sum: boolean }[] = [
  { key: 'incidence', sum: false },
  { key: 'case_count', sum: true },
  { key: 'mortality', sum: false },
  { key: 'death_count', sum: true },
];

const EpidemicFeatures: React.FC = () => {
  const { t } = useTranslation();
  const [disease, setDisease] = useState<string>('');
  const [province, setProvince] = useState<string>('');
  const [source, setSource] = useState<string>(''); // 病原学审核状态

  const [overview, setOverview] = useState<EpidemicOverview | null>(null);
  const [loadingOv, setLoadingOv] = useState(false);

  const [dpData, setDpData] = useState<{ items: EpidemicDataPoint[]; total: number }>({ items: [], total: 0 });
  const [dpPage, setDpPage] = useState(1);
  const [dpPageSize, setDpPageSize] = useState(15);
  const [loadingDp, setLoadingDp] = useState(false);

  const [pmData, setPmData] = useState<PathogenMonitoringResult | null>(null);
  const [pmPage, setPmPage] = useState(1);
  const [pmPageSize, setPmPageSize] = useState(15);
  const [loadingPm, setLoadingPm] = useState(false);

  const loadOverview = useCallback(async () => {
    setLoadingOv(true);
    try {
      setOverview(await epidemicSvc.getEpidemicOverview({ disease: disease || undefined, province: province || undefined }));
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '加载流行病学概览失败');
    } finally {
      setLoadingOv(false);
    }
  }, [disease, province]);

  const loadDataPoints = useCallback(async () => {
    setLoadingDp(true);
    try {
      setDpData(await epidemicSvc.getEpidemicDataPoints({
        disease: disease || undefined, province: province || undefined,
        page: dpPage, page_size: dpPageSize,
      }));
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '加载流行病学明细失败');
    } finally {
      setLoadingDp(false);
    }
  }, [disease, province, dpPage, dpPageSize]);

  const loadPathogen = useCallback(async () => {
    setLoadingPm(true);
    try {
      setPmData(await epidemicSvc.getPathogenMonitoring({
        disease: disease || undefined, province: province || undefined,
        source: source || undefined, page: pmPage, page_size: pmPageSize,
      }));
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '加载病原学监测数据失败');
    } finally {
      setLoadingPm(false);
    }
  }, [disease, province, source, pmPage, pmPageSize]);

  useEffect(() => { loadOverview(); }, [loadOverview]);
  useEffect(() => { loadDataPoints(); }, [loadDataPoints]);
  useEffect(() => { loadPathogen(); }, [loadPathogen]);

  const byType = new Map((overview?.by_type ?? []).map((x) => [x.data_type, x]));

  const provinceColumns = [
    { title: t('field.province', '省份'), dataIndex: 'province' },
    { title: t('field.literatureCount', '文献数'), dataIndex: 'literature_count', width: 90 },
    ...EPIDEMIC_COLS.map((c) => ({
      title: DATA_TYPE_LABEL[c.key] || c.key,
      dataIndex: c.key,
      width: 110,
      render: (v: number | null | undefined) =>
        v == null ? '-' : (c.sum ? v.toLocaleString() : `${v}%`),
    })),
  ];

  const dpColumns = [
    { title: t('field.disease', '疾病'), dataIndex: 'disease' },
    { title: t('field.province', '省份'), dataIndex: 'province' },
    { title: t('field.city', '城市'), dataIndex: 'city' },
    { title: t('field.indicator', '指标'), dataIndex: 'data_type', render: (v: string) => DATA_TYPE_LABEL[v] || v },
    { title: t('field.value', '数值'), dataIndex: 'value', render: (v: number | null) => v ?? '-' },
    { title: t('field.unit', '单位'), dataIndex: 'unit' },
    { title: t('field.sampleSize', '样本量'), dataIndex: 'sample_size' },
    { title: t('field.year', '年份'), dataIndex: 'collection_year' },
    { title: t('field.population', '人群'), dataIndex: 'population', ellipsis: true },
  ];

  const pmColumns = [
    { title: t('field.disease', '疾病'), dataIndex: 'disease' },
    { title: t('field.pathogen', '病原体'), dataIndex: 'pathogen_name' },
    { title: t('field.pathogenType', '类型'), dataIndex: 'pathogen_type' },
    { title: t('field.serotype', '血清型'), dataIndex: 'serotype' },
    { title: t('field.genotype', '基因型'), dataIndex: 'genotype' },
    { title: t('field.subtype', '亚型'), dataIndex: 'subtype' },
    { title: t('field.lineage', '谱系/流行株'), dataIndex: 'lineage' },
    { title: t('field.detectionRate', '检出率'), dataIndex: 'detection_rate', render: (v: number | null) => v == null ? '-' : `${v}%` },
    { title: t('field.sampleSize', '样本量'), dataIndex: 'sample_size' },
    { title: t('field.method', '检测方法'), dataIndex: 'detection_method', ellipsis: true },
    { title: t('field.province', '省份'), dataIndex: 'province' },
    { title: t('field.year', '年份'), dataIndex: 'collection_year' },
  ];

  const distTags = (label: string, dist?: DistEntry[]) => (
    <div>
      <Divider orientation="left" plain style={{ margin: '12px 0 8px' }}>{label}</Divider>
      {dist && dist.length > 0 ? (
        <Space wrap>
          {dist.map((d) => (
            <Tag key={d.value} color="blue">{d.value} <b>{d.count}</b></Tag>
          ))}
        </Space>
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('empty.noData', '暂无数据')} />
      )}
    </div>
  );

  const tabs: TabsProps['items'] = [
    {
      key: 'epi',
      label: t('nav.epidemiology', '流行病学监测'),
      children: (
        <div>
          <Row gutter={[16, 16]}>
            {EPIDEMIC_COLS.map((c) => {
              const bt = byType.get(c.key);
              return (
                <Col xs={12} sm={6} key={c.key}>
                  <Card size="small">
                    <Statistic
                      title={`${DATA_TYPE_LABEL[c.key]}（${bt?.count ?? 0} 点 / ${bt?.literature_count ?? 0} 文献）`}
                      value={bt == null ? '-' : c.sum ? (bt.sum ?? 0) : (bt.avg ?? 0)}
                      precision={c.sum ? 0 : 2}
                      suffix={bt?.unit ? (c.sum ? '' : bt.unit) : c.sum ? '' : '%'}
                    />
                  </Card>
                </Col>
              );
            })}
          </Row>
          <Divider orientation="left">{t('epidemic.provinceDist', '省级分布')}</Divider>
          <Table<EpidemicByProvince>
            rowKey="province"
            dataSource={overview?.by_province ?? []}
            columns={provinceColumns}
            pagination={{ pageSize: 15, hideOnSinglePage: true }}
            loading={loadingOv}
            size="small"
          />
          <Divider orientation="left">{t('epidemic.dataPoints', '数据点明细')}</Divider>
          <Table<EpidemicDataPoint>
            rowKey="id"
            dataSource={dpData.items}
            columns={dpColumns}
            loading={loadingDp}
            size="small"
            pagination={{
              current: dpPage,
              pageSize: dpPageSize,
              total: dpData.total,
              showSizeChanger: true,
              pageSizeOptions: [10, 15, 30, 50],
              onChange: (p, ps) => { setDpPage(p); setDpPageSize(ps); },
            }}
          />
        </div>
      ),
    },
    {
      key: 'pathogen',
      label: t('nav.pathogen', '病原学监测'),
      children: (
        <div>
          {distTags(t('epidemic.byPathogenType', '病原体类型分布'), pmData?.by_pathogen_type)}
          {distTags(t('epidemic.byPathogenName', '病原体名称分布'), pmData?.by_pathogen_name)}
          {distTags(t('epidemic.byGenotype', '基因型分布'), pmData?.by_genotype)}
          {distTags(t('epidemic.bySerotype', '血清型分布'), pmData?.by_serotype)}
          {distTags(t('epidemic.bySubtype', '亚型分布'), pmData?.by_subtype)}
          <Divider orientation="left">{t('epidemic.recordList', '监测记录')}</Divider>
          <Table<epidemicSvc.PathogenMonitoringItem>
            rowKey="id"
            dataSource={pmData?.list.items ?? []}
            columns={pmColumns}
            loading={loadingPm}
            size="small"
            pagination={{
              current: pmPage,
              pageSize: pmPageSize,
              total: pmData?.list.total ?? 0,
              showSizeChanger: true,
              pageSizeOptions: [10, 15, 30, 50],
              onChange: (p, ps) => { setPmPage(p); setPmPageSize(ps); },
            }}
          />
        </div>
      ),
    },
  ];

  return (
    <div>
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select
            placeholder={t('filter.allDiseases', '全部疾病')}
            allowClear
            style={{ minWidth: 140 }}
            value={disease || undefined}
            onChange={(v) => { setDisease(v || ''); setDpPage(1); setPmPage(1); }}
            options={DISEASES.map((d) => ({ value: d.key, label: d.name_cn }))}
          />
          <Select
            placeholder={t('filter.allProvinces', '全部省份')}
            allowClear
            style={{ minWidth: 120 }}
            value={province || undefined}
            onChange={(v) => { setProvince(v || ''); setDpPage(1); setPmPage(1); }}
            options={PROVINCES.map((p) => ({ value: p, label: p }))}
            showSearch
          />
          <Select
            placeholder={t('filter.allStatus', '全部审核状态')}
            allowClear
            style={{ minWidth: 120 }}
            value={source || undefined}
            onChange={(v) => setSource(v || '')}
            options={[
              { value: 'approved', label: '已通过' },
              { value: 'pending', label: '待审核' },
              { value: 'rejected', label: '已驳回' },
            ]}
          />
          <Spin spinning={loadingOv || loadingDp || loadingPm} />
        </Space>
      </Card>
      <Card size="small">
        <Tabs items={tabs} />
      </Card>
    </div>
  );
};

export default EpidemicFeatures;