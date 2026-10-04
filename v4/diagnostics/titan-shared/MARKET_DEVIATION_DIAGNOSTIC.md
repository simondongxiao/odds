# Market Deviation Diagnostic

市场盘口只在 FFL/CMFL 之后读取。每场同时输出四个可审计分数：

- H1 `FUNDAMENTAL_UPDATE`：市场变化是否与跨市场基本面更新一致。
- H2 `PRICE_DISCOVERY`：亚盘是否向独立 CMFL 收敛。
- H3 `PUBLIC_BIAS_SHADING`：盘口是否偏离足球基本面且跨市场不支持。
- H4 `LIQUIDITY_NOISE`：单公司、低覆盖、不同步或陈旧快照噪声。

跨市场、跨公司广度和时间先后不足时允许 `UNKNOWN` 或 `MIXED`。单一展示公司绝不能直接判为诱盘；当前单源聚合数据将 H4 提高并把 Market Quality 限制在 LOW。

这些解释字段不直接命令 V3/V4 方向，也不存在盘口档位到方向的硬规则。
