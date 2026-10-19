-- query 向量缓存。


CREATE TABLE IF NOT EXISTS query_vec (
    model            TEXT        NOT NULL,
    dim              INTEGER     NOT NULL,
    instruction_hash BYTEA       NOT NULL,   -- sha256(instruction)[:16]，换前缀即换键
    text_hash        BYTEA       NOT NULL,   -- sha256(q.strip())
    vec              BYTEA       NOT NULL,   -- float16 小端，dim * 2 字节
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT query_vec_pk PRIMARY KEY (model, dim, instruction_hash, text_hash),
    CONSTRAINT query_vec_len CHECK (octet_length(vec) = dim * 2)
);
