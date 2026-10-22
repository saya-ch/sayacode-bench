# 生产基线的精确重建

`product-baseline-source.zip` 保存本次生产运行包的源码与构建元数据原始字节，不含用户状态、API 密钥、公开基准答案或原始模型轨迹。

基线来自 SAYACODE 的基础提交 `8cf966e508e94e1e501a4eb15939b29a39d16d12` 及当时未提交的团队工具开关与错误审计改动。只检出该提交不足以重建当前候选，因此归档完整保存运行时源码和元数据；`identity.json` 同时记录源码归档、原始 wheel 与依赖锁导出的身份。

已在独立目录解压、重新构建 wheel，并验证它与模型试验使用的原始 wheel **逐字节相同**：

```text
sayacode-3.2.4-py3-none-any.whl
SHA256 7892afcd50bd0ee786ed3ea5ba73015af32da11cd3eeff5474ce7e64d039dffe
```

重建步骤：

1. 校验归档 SHA256 与 `identity.json` 一致。
2. 解压到新目录，不覆盖现有项目。
3. 在该目录执行 `uv build --wheel`。
4. 对 wheel 求 SHA256，与上列身份核对。
5. 使用该归档中的 `uv.lock` 执行 `uv export --frozen --no-dev --no-editable --no-emit-project --output-file requirements.txt`，保留所有依赖 hash，再传给本仓库适配器。

导出 requirements 的自动注释可能包含本地命令路径，因此不同路径导出的文本 SHA 未必相同；实际实验使用的原始 requirements SHA 在 identity 中单独记录。正式研究绑定实际文件身份，不以包版本号代替内容身份。
