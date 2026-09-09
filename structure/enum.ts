/** 置信度等级。 */
enum ConfidenceLevel {
  /** 高置信度。 */
  High = 'high',
  /** 中置信度。 */
  Medium = 'medium',
  /** 低置信度。 */
  Low = 'low',
}

/** 审核状态。 */
enum ReviewStatus {
  /** 审核通过并正式入库。 */
  Formal = 'FORMAL',
  /** 待进一步确认。 */
  Pending = 'PENDING',
  /** 存在争议，暂时隔离。 */
  Disputed = 'DISPUTED',
  /** 审核未通过，不入库。 */
  Rejected = 'REJECTED',
}