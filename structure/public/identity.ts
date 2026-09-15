interface Identity {
    /** 身份对象名 **/
    name: string
    /** 对象的类型 **/
    object_type: "source" | "evidence" | "viewpoint"
    /** 当前的审核状态 **/
    status: ReviewStatus
}