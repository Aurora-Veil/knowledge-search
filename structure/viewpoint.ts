interface Viewpoint {
    /** 观点ID **/
    id: number
    /** 项目ID **/
    project_id: number
    /** 观点在 oirf 中的ID **/
    oirf_id: string
    /** 对象身份区结构 **/
    identity: Identity
    /** 呈现层：观点呈现部分的数据 **/
    presentation: {
        /** 观点名 **/
        name: string
        /** 观点内容 **/
        content: string
        /** 观点类型，如政策监管、产业链层面等等 **/
        type: string
        /** 反证，替代解释及为何仍支持原观点 **/
        explanation: string
        /** 可能推翻观点的条件 **/
        change_triggers: string
    }
    /** 推理层：观点的推导过程说明 **/
    reasoning: {
        /** 推理步骤 **/
        steps: Array<{
            /** 关联的来源oirf_id **/
            source_ids: string[]
            /** 关联的证据oirf_id **/
            evidence_ids: string[]
            /** 当前推导步骤的结果 **/
            to: string
        }>
        /** 初步结论 **/
        narrative: string
    }
    /** 经验层：判断或分析的理由依据 **/
    experience: {
        /** 经验名 **/
        name: string
        /** 经验内容 **/
        content: string
        /** 经验规则适用于什么场景，industry_definition / ipo / ... **/
        applicable_scenario: string
        /** 该经验规则适用于哪类观点，事实判断 / 趋势判断 / 因果判断 / 测算判断 / 定义或行业边界判断 / 预测判断 / 建议性判断 / ... **/
        claim_type: string
        /** 验证模式，无需验证 / 不同原始信源相互印证 / 不同方法或不同数据体系交叉验证 / 由权威来源确认 / 同时要求独立信源和权威来源 / 最低独立原始信源数量 **/
        cross_validation_mode: string
        /** 对于验证模式的解释，如为何可以使用该模式，该模式需要至少哪些前提 **/
        cross_validation_mode_descipition: string
        /** 未达到经验标准时的处理办法 **/
        insufficient_evidence_action: string
    }
    /** 生命周期层：观点的生命周期内容 **/
    lifecycle: Lifecycle[]
    /** 责任链 **/
    responsibility: Responsibility[]
}