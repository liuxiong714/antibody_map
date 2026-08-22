import React from 'react';
import { Badge, Tooltip, Typography } from 'antd';
import { QUALITY_GRADE_META, ESTIMATE_GRADE_LABEL } from '../utils/constants';

const { Text } = Typography;

interface BreakdownItem {
  score: number;
  label: string;
  max?: number;
}

interface Props {
  qualityScore?: number | null;
  qualityGrade?: string | null;
  estimateGrade?: string | null;
  breakdown?: Record<string, BreakdownItem> | null;
}

/** 六项得分明细的中文标题 */
const BREAKDOWN_TITLES: Record<string, string> = {
  sample_size: '样本量',
  sampling: '抽样方式',
  detection_method: '检测方法',
  population: '人群代表性',
  estimate_grade: '调查级别',
  confidence: '溯源置信度',
};

const QualityBadge: React.FC<Props> = ({
  qualityScore,
  qualityGrade,
  estimateGrade,
  breakdown,
}) => {
  if (!qualityGrade || qualityScore == null) {
    return (
      <Tooltip title="审核通过后自动打分（未评分）" placement="topLeft">
        <span>
          <Badge status="default" text="-" />
        </span>
      </Tooltip>
    );
  }

  const meta = QUALITY_GRADE_META[qualityGrade] || { color: 'default', label: qualityGrade };

  const lines: string[] = [`质量评分：${qualityScore} 分`, `等级：${meta.label}`];
  if (estimateGrade) {
    lines.push(`调查级别：${ESTIMATE_GRADE_LABEL[estimateGrade] || estimateGrade}`);
  }
  if (breakdown) {
    lines.push('── 六项得分明细 ──');
    for (const [key, item] of Object.entries(breakdown)) {
      const title = BREAKDOWN_TITLES[key] || key;
      const max = item.max != null ? `/${item.max}` : '';
      lines.push(`${title}：${item.score}${max}（${item.label}）`);
    }
  }

  return (
    <Tooltip title={lines.join('\n')} placement="topLeft">
      <span>
        <Badge
          color={meta.color}
          text={
            <Text style={{ fontSize: 12 }}>
              {qualityScore} · {qualityGrade}
            </Text>
          }
        />
      </span>
    </Tooltip>
  );
};

export default QualityBadge;
