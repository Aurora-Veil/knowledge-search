/** 证据类型。 */
enum EvidenceType {
  /** 已经发生或被记录的历史事实。 */
  Historical = '历史值',
 /** 对未来或未知结果的预估。 */
  Estimated = '预估值',
  /** 通过分析或计算得到的结果。 */
  Calculated = '计算值',
  /** 由标准、法规、政策或其他规则规定的规则 */
  Rule = '规则值',
}

/** 证据的呈现层。 */
interface EvidencePresentation {
  /**
   * 证据描述的企业、品牌、市场或其他主体。
   * 例如“南山婆”。
   */
  subject: string;
  /** 证据类型 */
  type: EvidenceType;
  /** 证据对应的来源类型。 */
  source_type: SourceType;
  /** 证据所属行业。 */
  industry: string;
  /**
   * 证据指标名称。
   * 例如“酸汤销量”。
   */
  indicator: string;
  /** 证据的标准化取值或结构化事实内容。 */
  value: string;
  /** 证据的数值单位或事实单位；没有单位时为 null。 */
  unit: string | null;
  /** 证据对应的期间。 */
  period: string;
  /** 证据对应的地域范围，暂不限制取值。 */
  region: string;
  /**
   * 从来源中逐字提取的原文。
   * 必须保留来源原文，不得改写、概括或补充。
   */
  raw_texts: string[];
  /** 无法通过其他结构化字段表达的补充说明。 */
  notes: string[];
}

/** 证据的推理层。 */
interface EvidenceReasoning {
  /**
   * 支撑该证据的来源 的 oirf_id。
   * 每个 ID 必须能解析到对应的 Source。
   */
  source_ids: string[];
}

/** 证据的经验层。 */
interface EvidenceExperience {
  /** 证据置信度。 */
  confidence_level: ConfidenceLevel;
  /** 证据置信度的判断理由。 */
  confidence_reason: string;
  /**
   * 对最原始发布者或最原始出处的判断。
   *
   * 必须根据来源材料判断，不得臆测。
   * 无法从材料中判断时，固定填写：
   * “原文未注明最原始发布者”
   */
  original_publish: string;
}

/** 证据。 */
interface Evidence {
  /** 证据 ID。*/
  id: number;
  /** 项目ID **/
  project_id: number
  /** 证据在 oirf 中的ID, "evidence:ID" 格式 **/
  oirf_id: string
  /** 对象身份区结构 **/
  identity: Identity
  /** 呈现层：描述证据本身及其原文表达。 */
  presentation: EvidencePresentation;
  /** 推理层：记录证据与来源之间的关联。 */
  reasoning: EvidenceReasoning;
  /** 经验层：记录置信度和原始出处判断。 */
  experience: EvidenceExperience;
  /** 生命周期层：观点的生命周期内容 **/
  lifecycle: Lifecycle[]
  /** 责任链 **/
  responsibility: Responsibility[]
}