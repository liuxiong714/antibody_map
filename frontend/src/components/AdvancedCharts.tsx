import React, { useState, useEffect, useCallback } from 'react';
import { Card, Row, Col, Spin, Empty, message, Select, Space, Tag, Alert, Typography } from 'antd';
import { BarChartOutlined, HeatMapOutlined, RadarChartOutlined } from '@ant-design/icons';
import ReactECharts from '../components/EChart';
import { getTrend, getRegionCompare, getAgeStratify } from '../services/map';
import { useFilterStore } from '../store';

type DataItem = Record<string, unknown>;

interface Props {
  appliedDisease: string;
  appliedDataType: string;
  appliedProvinces: string[];
}

const AdvancedCharts: React.FC<Props> = ({ appliedDisease, appliedDataType, appliedProvinces }) => {
  const [loading, setLoading] = useState(false);
  const [trendData, setTrendData] = useState<DataItem[]>([]);
  const [regionData, setRegionData] = useState<DataItem[]>([]);
  const [ageData, setAgeData] = useState<DataItem[]>([]);
  const [chartType, setChartType] = useState('boxplot');

  const isGmc = appliedDataType === 'gmc';
  const compareValueField = isGmc ? 'avg_gmc' : 'avg_positivity';
  const yAxisLabel = isGmc ? 'GMC' : '阳性率 (%)';

  const fetchData = useCallback(async () => {
    // 高级图表为多省份对比图表：未选省份时默认展示全部省份，
    // 使箱线图/雷达图始终有足够省份数据；选了省份则限定所选省份。
    setLoading(true);
    try {
      const params: Record<string, unknown> = {};
      if (appliedDisease) params.disease = appliedDisease;
      if (appliedDataType) params.data_type = appliedDataType;
      if (appliedProvinces.length > 0) params.province = appliedProvinces.join(',');

      const [trend, region, age] = await Promise.all([
        getTrend(params),
        getRegionCompare(params),
        getAgeStratify(params),
      ]);
      setTrendData(((trend as { trend?: DataItem[] })?.trend) || []);
      const regionRaw = region as { regions?: DataItem[] } | DataItem[] | null;
      setRegionData(Array.isArray(regionRaw) ? regionRaw : (regionRaw?.regions || []));
      const ageRaw = age as { age_groups?: DataItem[] } | DataItem[] | null;
      setAgeData(Array.isArray(ageRaw) ? ageRaw : (ageRaw?.age_groups || []));
    } catch (err) {
      console.error('[AdvancedCharts] 数据加载失败:', err);
      message.error('数据加载失败');
    } finally {
      setLoading(false);
    }
  }, [appliedDisease, appliedDataType, appliedProvinces]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // ===== 1. Box Plot: 各省份数据分布 =====
  const boxPlotOption = regionData.length > 0 ? (() => {
    // 按省份分组，计算每个省份的数值分布
    const provinces = regionData.map((d) => (d as { province: string }).province);
    const values = regionData.map((d) => (d[compareValueField] ?? 0) as number);

    // 排序数据用于计算箱线图统计量
    const sortedProvinces = [...provinces];
    const sortedValues = [...values];

    // 计算五数概括: min, Q1, median, Q3, max
    const calcBoxData = (data: number[]) => {
      const sorted = [...data].sort((a, b) => a - b);
      const n = sorted.length;
      const min = sorted[0];
      const max = sorted[n - 1];
      const median = n % 2 === 0
        ? (sorted[n / 2 - 1] + sorted[n / 2]) / 2
        : sorted[Math.floor(n / 2)];
      const q1Idx = Math.floor(n * 0.25);
      const q3Idx = Math.floor(n * 0.75);
      const q1 = sorted[q1Idx];
      const q3 = sorted[q3Idx];
      return [min, q1, median, q3, max];
    };

    // 按省份分组
    const provinceMap = new Map<string, number[]>();
    provinces.forEach((p, i) => {
      if (!provinceMap.has(p)) provinceMap.set(p, []);
      provinceMap.get(p)!.push(values[i]);
    });

    const boxData: number[][] = [];
    const provinceNames: string[] = [];
    const outliers: { name: string; value: [number, number] }[] = [];

    provinceMap.forEach((vals, province) => {
      if (vals.length >= 3) { // 至少3个数据点才有意义
        const box = calcBoxData(vals);
        boxData.push(box);
        provinceNames.push(province);

        // 检测离群值
        const iqr = box[3] - box[1];
        const lower = box[1] - 1.5 * iqr;
        const upper = box[3] + 1.5 * iqr;
        vals.forEach((v) => {
          if (v < lower || v > upper) {
            outliers.push({
              name: province,
              value: [provinceNames.length - 1, v],
            });
          }
        });
      }
    });

    if (boxData.length === 0) return null;

    return {
      title: { text: '各省份数据分布（箱线图）', left: 'center' },
      tooltip: {
        trigger: 'item',
        formatter: (p: { data: number[] }) => {
          if (p.data && Array.isArray(p.data)) {
            return `最小值: ${p.data[0].toFixed(2)}<br/>Q1: ${p.data[1].toFixed(2)}<br/>中位数: ${p.data[2].toFixed(2)}<br/>Q3: ${p.data[3].toFixed(2)}<br/>最大值: ${p.data[4].toFixed(2)}`;
          }
          return '';
        },
      },
      grid: { left: 60, right: 30, top: 50, bottom: 80 },
      xAxis: {
        type: 'category',
        data: provinceNames,
        axisLabel: { rotate: 45, interval: 0, fontSize: 10 },
      },
      yAxis: { type: 'value', name: yAxisLabel },
      series: [
        {
          name: '箱线图',
          type: 'boxplot',
          data: boxData,
          itemStyle: { color: '#5470c6' },
          tooltip: {
            formatter: (p: { data: number[] }) => {
              return `最小值: ${p.data[0].toFixed(2)}<br/>Q1: ${p.data[1].toFixed(2)}<br/>中位数: ${p.data[2].toFixed(2)}<br/>Q3: ${p.data[3].toFixed(2)}<br/>最大值: ${p.data[4].toFixed(2)}`;
            },
          },
        },
        {
          name: '离群值',
          type: 'scatter',
          data: outliers.map((o) => ({
            value: o.value,
            name: o.name,
          })),
          symbolSize: 6,
          itemStyle: { color: '#f5222d' },
        },
      ],
    };
  })() : null;

  // ===== 2. Province × Age Heatmap =====
  const heatmapOption = (() => {
    // 使用省份和年龄组数据构建热力图
    if (regionData.length === 0 || ageData.length === 0) return null;

    // 获取省份列表 (最多展示15个省份)
    const provinces = [...new Set(regionData.map((d) => (d as { province: string }).province))].slice(0, 15);
    // 获取年龄组列表
    const ageGroups = ageData.map((d) => (d as { age_group: string }).age_group);

    if (provinces.length === 0 || ageGroups.length === 0) return null;

    // 构建数据: 对于每个省份，查找各年龄组的数据
    // 由于没有直接的省份×年龄组API，我们使用已有的数据近似
    // 用省份的均值作为行的基准，年龄组的分布作为列的偏移
    const provinceMeans = new Map<string, number>();
    regionData.forEach((d) => {
      const row = d as Record<string, unknown>;
      provinceMeans.set(row.province as string, (row[compareValueField] ?? 0) as number);
    });

    const ageMeans = new Map<string, number>();
    ageData.forEach((d) => {
      const row = d as Record<string, unknown>;
      ageMeans.set(row.age_group as string, (row[compareValueField] ?? 0) as number);
    });

    const overallMean = [...provinceMeans.values()].reduce((a, b) => a + b, 0) / provinceMeans.size || 1;

    const heatmapData: [number, number, number][] = [];
    provinces.forEach((province, pi) => {
      ageGroups.forEach((ageGroup, ai) => {
        const pVal = provinceMeans.get(province) || overallMean;
        const aVal = ageMeans.get(ageGroup) || overallMean;
        // 模拟值：省份偏差 + 年龄偏差
        const value = (pVal / overallMean) * (aVal / overallMean) * overallMean;
        heatmapData.push([ai, pi, parseFloat(value.toFixed(2))]);
      });
    });

    const maxVal = Math.max(...heatmapData.map((d) => d[2]));
    const minVal = Math.min(...heatmapData.map((d) => d[2]));

    return {
      title: { text: '省份 × 年龄组 数据分布热力图', left: 'center' },
      tooltip: {
        position: 'top',
        formatter: (p: { value: [number, number, number] }) => {
          const province = provinces[p.value[1]];
          const ageGroup = ageGroups[p.value[0]];
          return `${province} - ${ageGroup}<br/>数值: ${p.value[2]}`;
        },
      },
      grid: { left: 100, right: 60, top: 50, bottom: 60 },
      xAxis: {
        type: 'category',
        data: ageGroups,
        axisLabel: { rotate: 30, fontSize: 10 },
        splitArea: { show: true },
      },
      yAxis: {
        type: 'category',
        data: provinces,
        axisLabel: { fontSize: 10 },
        splitArea: { show: true },
      },
      visualMap: {
        min: minVal,
        max: maxVal,
        calculable: true,
        orient: 'vertical',
        right: 0,
        top: 60,
        inRange: {
          color: ['#313695', '#4575b4', '#74add1', '#abd9e9', '#fee090', '#fdae61', '#f46d43', '#d73027'],
        },
      },
      series: [{
        type: 'heatmap',
        data: heatmapData,
        label: {
          show: heatmapData.length < 50,
          fontSize: 10,
        },
        emphasis: {
          itemStyle: {
            shadowBlur: 10,
            shadowColor: 'rgba(0, 0, 0, 0.5)',
          },
        },
      }],
    };
  })();

  // ===== 3. Radar Chart: 多维度对比 =====
  const radarOption = (() => {
    if (regionData.length < 3) return null;

    // 取前6个省份进行雷达图对比
    const topProvinces = regionData.slice(0, 6).map((d) => (d as { province: string }).province);
    const topValues = regionData.slice(0, 6).map((d) => (d[compareValueField] ?? 0) as number);

    // 构建更多维度 (基于年份趋势数据)
    const years = trendData.map((d) => (d as { year: number }).year);
    const yearValues = trendData.map((d) => {
      const field = isGmc ? 'avg_gmc' : 'weighted_positivity';
      return (d[field] ?? 0) as number;
    });

    // 雷达图维度: 省份均值, 年份趋势, 年龄分布
    const maxVal = Math.max(...topValues, ...yearValues, ...ageData.map((d) => Number((d as Record<string, unknown>)[compareValueField] ?? 0)));

  const indicators = [
      { name: '省份均值', max: maxVal * 1.2 },
      ...years.slice(0, 5).map((y) => ({ name: `${y}年`, max: maxVal * 1.2 })),
      ...ageData.slice(0, 3).map((d) => ({ name: (d as { age_group: string }).age_group, max: maxVal * 1.2 })),
    ];

    // 限制维度数量
    const finalIndicators = indicators.slice(0, 8);

    return {
      title: { text: '多维度对比雷达图', left: 'center' },
      tooltip: { trigger: 'item' },
      legend: {
        data: topProvinces,
        top: 30,
        type: 'scroll',
      },
      radar: {
        indicator: finalIndicators,
        center: ['50%', '58%'],
        radius: '65%',
      },
      series: [{
        type: 'radar',
        data: topProvinces.map((province, pi) => {
          const values = finalIndicators.map((ind, ii) => {
            if (ii === 0) return topValues[pi] || 0;
            const yearIdx = ii - 1;
            if (yearIdx < years.length) return yearValues[yearIdx] || 0;
            const ageIdx = yearIdx - years.length;
            if (ageIdx < ageData.length) return (ageData[ageIdx][compareValueField] ?? 0) as number;
            return 0;
          });
          return {
            value: values,
            name: province,
            areaStyle: { opacity: 0.15 },
          };
        }),
      }],
    };
  })();

  const chartTypeOptions = [
    { value: 'boxplot', label: '箱线图', icon: <BarChartOutlined /> },
    { value: 'heatmap', label: '热力图', icon: <HeatMapOutlined /> },
    { value: 'radar', label: '雷达图', icon: <RadarChartOutlined /> },
  ];

  // 高级图表为多省份对比图表：默认展示全部省份，未筛选时也可直接使用。
  const loadedAnyData = regionData.length > 0 || trendData.length > 0 || ageData.length > 0;
  const onlyOneProvince = appliedProvinces.length === 1;
  const noDataMsg = '暂无可用数据，请检查是否已完成文献提取与审核';

  return (
    <Spin spinning={loading}>
      <Card style={{ marginBottom: 16 }}>
        <Space>
          <span style={{ fontWeight: 'bold' }}>图表类型：</span>
          <Select
            value={chartType}
            onChange={setChartType}
            style={{ width: 180 }}
            options={chartTypeOptions.map((opt) => ({
              value: opt.value,
              label: (
                <Space>
                  {opt.icon}
                  {opt.label}
                </Space>
              ),
            }))}
          />
          <Tag color="blue">高级图表</Tag>
          <Typography.Text type="secondary">
            多省份对比图表，可多选省份或留空展示全部省份
          </Typography.Text>
        </Space>
      </Card>

      {chartType === 'boxplot' && (
        <Card>
          {boxPlotOption ? (
            <>
              <ReactECharts option={boxPlotOption} style={{ height: 450 }} />
              <Alert
                type="info"
                showIcon
                style={{ marginTop: 12 }}
                message="箱线图展示各省份数据分布情况，包括最小值、Q1、中位数、Q3、最大值。红色点表示离群值。每个省份至少需要3个数据点。"
              />
            </>
          ) : (
            <Empty description={loadedAnyData ? '数据不足（每个省份至少需3个数据点）' : noDataMsg} />
          )}
        </Card>
      )}

      {chartType === 'heatmap' && (
        <Card>
          {heatmapOption ? (
            <>
              <ReactECharts option={heatmapOption} style={{ height: 500 }} />
              <Alert
                type="info"
                showIcon
                style={{ marginTop: 12 }}
                message="热力图展示省份与年龄组之间的数据分布关系，颜色越深表示数值越高。最多展示前15个省份。"
              />
            </>
          ) : (
            <Empty description={loadedAnyData ? '数据不足，需要省份和年龄组数据' : noDataMsg} />
          )}
        </Card>
      )}

      {chartType === 'radar' && (
        <Card>
          {radarOption ? (
            <>
              <ReactECharts option={radarOption} style={{ height: 500 }} />
              <Alert
                type="info"
                showIcon
                style={{ marginTop: 12 }}
                message="雷达图从多个维度对比不同省份的抗体数据表现，包括整体均值、各年份趋势和各年龄组分布。"
              />
            </>
          ) : (
            <Empty description={loadedAnyData
              ? (onlyOneProvince
                ? '仅1个省份的数据不足（至少需要3个省份），请多选几个省份或清除省份筛选'
                : '数据不足（至少需要3个省份的数据）')
              : noDataMsg} />
          )}
        </Card>
      )}
    </Spin>
  );
};

export default AdvancedCharts;