/**
 * EquityRadar：省 × 15 病公平性雷达图。
 *
 * 逐个疾病调用 /analysis/equity 获取各省加权阳性率，
 * 以 15 种疾病为雷达轴、所选省份为多边形序列，直观对比各省跨病种抗体水平。
 * 借鉴 Kenya 省际公平雷达的可视化思路：指标轴 = 疾病，系列 = 省份。
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Card, Empty, Select, Space, Spin, Tag } from 'antd';
import EChart from './EChart';
import { getEquityAnalysis } from '../services/map';
import { DISEASES, type DiseaseOption } from '../utils/constants';
import type { EquityAnalysisResponse } from '../types';

interface Props {
  selectedDisease: string;
  selectedProvince?: string | null;
  height?: number;
}

interface ProvinceDiseaseValues {
  [province: string]: Record<string, number | null>;
}

const EquityRadar: React.FC<Props> = ({ selectedDisease, selectedProvince, height = 440 }) => {
  const [loading, setLoading] = useState(false);
  const [provinceValues, setProvinceValues] = useState<ProvinceDiseaseValues>({});
  const [selectedProvinces, setSelectedProvinces] = useState<string[]>([]);

  // 汇总各疾病 equity 数据 → 省 × 病 数值矩阵
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all(
      DISEASES.map((d) =>
        getEquityAnalysis({ disease: d.key }).catch(() => null)
      )
    )
      .then((results: Array<EquityAnalysisResponse | null>) => {
        if (cancelled) return;
        const matrix: ProvinceDiseaseValues = {};
        results.forEach((res, idx) => {
          const diseaseKey = DISEASES[idx].key;
          if (!res) return;
          (res.province_rows || []).forEach((row) => {
            if (!matrix[row.province]) matrix[row.province] = {};
            matrix[row.province][diseaseKey] = row.weighted_positivity;
          });
        });
        setProvinceValues(matrix);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // 默认选中：钻取省优先，否则取当前疾病加权阳性率 Top3
  useEffect(() => {
    if (selectedProvince) {
      setSelectedProvinces((prev) =>
        prev.includes(selectedProvince) ? prev : [...prev, selectedProvince]
      );
      return;
    }
    if (Object.keys(provinceValues).length === 0) return;
    const curDiseaseRows = Object.entries(provinceValues).map(([prov, vals]) => ({
      prov,
      v: vals[selectedDisease] ?? null,
    }));
    const top = curDiseaseRows
      .filter((x) => x.v != null)
      .sort((a, b) => (b.v as number) - (a.v as number))
      .slice(0, 3)
      .map((x) => x.prov);
    setSelectedProvinces(top);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDisease, selectedProvince]);

  const provinceOptions = useMemo(
    () =>
      Object.keys(provinceValues).map((p) => ({
        value: p,
        label: p,
      })),
    [provinceValues]
  );

  const option = useMemo(() => {
    const provinces = selectedProvinces.filter((p) => provinceValues[p]);
    if (provinces.length === 0) return null;
    const maxVal = 100;
    return {
      title: { text: '省份 × 疾病 公平性雷达图', left: 'center', textStyle: { fontSize: 14 } },
      tooltip: {
        trigger: 'item',
        formatter: (p: { name: string; value: (number | null)[]; marker: string }) => {
          const lines = DISEASES.map((d, i) => {
            const v = p.value[i];
            return `${d.name_cn}: ${v != null ? v.toFixed(1) + '%' : '无数据'}`;
          });
          return `<b>${p.name}</b><br/>${lines.join('<br/>')}`;
        },
      },
      legend: {
        top: 30,
        type: 'scroll',
        data: provinces,
      },
      radar: {
        indicator: DISEASES.map((d: DiseaseOption) => ({ name: d.name_cn, max: maxVal })),
        center: ['50%', '58%'],
        radius: '62%',
        splitArea: { areaStyle: { color: ['rgba(24,144,255,0.02)', 'rgba(24,144,255,0.05)'] } },
      },
      series: [
        {
          type: 'radar',
          data: provinces.map((p) => ({
            name: p,
            value: DISEASES.map((d) => provinceValues[p]?.[d.key] ?? 0),
            lineStyle: { width: 2 },
            areaStyle: { opacity: 0.12 },
          })),
        },
      ],
    };
  }, [selectedProvinces, provinceValues]);

  return (
    <Card
      size="small"
      title={
        <Space>
          <span>省 × 15 病公平性雷达</span>
          <Tag color="blue">跨病种对比</Tag>
        </Space>
      }
      extra={
        <Space>
          <span style={{ fontSize: 12, color: '#888' }}>省份（可多选）：</span>
          <Select
            mode="multiple"
            size="small"
            style={{ minWidth: 220 }}
            placeholder="选择省份"
            value={selectedProvinces}
            onChange={(v: string[]) => setSelectedProvinces(v)}
            options={provinceOptions}
            maxTagCount={3}
            allowClear
          />
        </Space>
      }
    >
      <Spin spinning={loading}>
        {option ? (
          <EChart option={option} style={{ height }} />
        ) : (
          <Empty description="暂无跨病种公平性数据" style={{ padding: '40px 0' }} />
        )}
        <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>
          雷达轴为 15 种疾病，数值为各省在各病种上的样本量加权阳性率（%）。未加载疾病选项见疾病筛选栏；默认展示当前疾病 Top3 省份。
        </div>
      </Spin>
    </Card>
  );
};

export default EquityRadar;
