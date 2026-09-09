interface Lifecycle {
    /** 知识的发布时间 **/
    publish_time: string
    /** 知识的生效时间 **/
    effective_time: string
    /** 知识的失效时间 **/
    expiration_time: string
    /** 关联的责任链ID **/
    responsibility_id: string
    /** 当前生命周期版本 X.X.X **/
    version: string
    /** 依赖 / 继承自哪些数据 **/
    dependences: Array<{
        /** 依赖的对象类型 **/
        object_type: "source" | "evidence" | "viewpoint"
        /** 依赖的对象ID **/
        object_id: string
        /** object_version **/
        object_version: string
    }>
}