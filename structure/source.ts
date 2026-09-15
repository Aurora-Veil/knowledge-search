/** 来源类型。 */
enum SourceType {
  /** 一手访谈。 */
  PrimaryInterview = 'primary_interview',
  /** 二手公开资料。 */
  SecondaryPublic = 'secondary_public',
  /** 分析师计算。 */
  AnalystCalculation = 'analyst_calculation',
}

/** 来源材料的使用权利或限制。 */
enum SourceRights {
  /** 可公开使用。 */
  Open = 'open',
  /** 已获得使用许可。 */
  Licensed = 'licensed',
  /** 仅限合理使用范围内引用。 */
  FairUseExcerpt = 'fair_use_excerpt',
  /** 使用前需要获得许可。 */
  PermissionRequired = 'permission_required',
  /** 保密材料。 */
  Confidential = 'confidential',
  /** 权利状态未知。 */
  Unknown = 'unknown',
}

/** 来源的呈现层。 */
interface SourcePresentation {
  /** 来源类型。 */
  type: SourceType;
  /** 文件名称或二手网页标题。 */
  title: string;
  /** 文件保存路径或原始网页链接。 */
  uri: string;
  /** 资料发布方或网页来源。 */
  publisher: string | null;
  /**
   * 来源相关的补充说明，默认使用空数组。
   *
   * 对于标准、法规、目录、政策文件、交易所规则或披露规则，
   * 尽量记录现行有效、已废止、被替代、征求意见稿、状态未知等状态。
   *
   * 与使用权利或限制有关的补充情况也记录在这里。
   */
  notes: string[];
  /**
   * 使用权利或限制。
   * 二手公开来源必须填写，其他来源可以为 null。
   */
  rights: SourceRights | null;
  /** 来源材料的内容浓缩摘要。 */
  summary: string;
}

/** 来源的经验层。 */
interface SourceExperience {
  /**
   * 来源等级。
   * 二手公开来源通常填写 T1～T6；
   * 其他来源也可以填写适用的自定义等级。
   */
  level: string | null;
  /**
   * 来源标签。
   * 二手公开来源填写 source_tier.json 中 subclass 的 name；
   * 其他来源也可以填写适用的自定义标签。
   */
  label: string | null;
   /**
   * 来源等级与子分类的判断理由。
   * 说明为什么归入当前 level 和 label。
   */
  level_reason: string 
  /** 来源本身的置信度。 */
  confidence_level: ConfidenceLevel;
  /** 来源置信度的判断理由。 */
  confidence_reason: string;
}

/** 来源信息。 */
interface Source {
  /** 来源 ID */
  id: number;
  /** 项目ID **/
  project_id: number
  /** 来源在 oirf 中的ID, "source:ID" 格式 **/
  oirf_id: string
  /** 对象身份区结构 **/
  identity: Identity
  /** 呈现层：观点呈现部分的数据 **/
  presentation: SourcePresentation
  /** 推理层：Source 不承载推理，固定为 null。 */
  reasoning: null
  /** 经验层：记录来源分级、分类和可信度判断。 */
  experience: SourceExperience
  /** 生命周期层：观点的生命周期内容 **/
  lifecycle: Lifecycle[]
  /** 责任链 **/
  responsibility: Responsibility[]
}