export enum ResponsibilityOperation {
  Create = "create",
  Review = "review",
  Maintain = "maintain",
  Correct = "correct",
}

export enum OperatorType {
  Human = "human",
  Ai = "ai",
}

export interface ResponsibilityChange {
  /** 字段路径，用 . 连接 */
  path: string;
  /** 修改前的值 */
  from: string;
  /** 修改后的值 */
  to: string;
}

interface ResponsibilityOperator {
  /** 人员 ID 或 Agent（Codex、Workbuddy、Cursor等） */
  id: string;
  type: OperatorType;
  /**  人员角色 或 Agent 角色，如 analyst、developer、review-agent */
  role: string;
  /** 人员名称 或 模型名称 */
  name: string;
}

interface Responsibility {
  /** 责任ID，"responsibility:ID" 格式*/
  id: string;
  operation: ResponsibilityOperation;
  operator: ResponsibilityOperator;
  /** create 时为 null，其他操作为字段变化数组 */
  changes: ResponsibilityChange[] | null;
  note: string;
  time: string;
}