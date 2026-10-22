# 真实校准交付补丁

这里保存两次已经执行的资源校准所捕获的真实模型交付，原始 patch 字节未改。`source.json` 绑定任务、源码版本、基线提交、patch SHA、原运行／本机重判事实与原始证据 SHA；它不是伪造的 Harbor TrialResult，也不包含模型思考、私有配置或用户路径。

这些任务和同修复组都排除于正式开发与最终验收。即使后续在稳定宿主获得不同结果，也另列诊断，不覆盖本机首判，不将校准加入正式分母。

## 来源与许可

| 目录 | 上游项目 | 原始基线提交 | 许可文件来源 |
| --- | --- | --- | --- |
| qutebrowser | [qutebrowser/qutebrowser](https://github.com/qutebrowser/qutebrowser) | `6d9c28ce10832aa727de1a326d9459a035ff3aba` | 固定任务镜像的项目 LICENSE |
| ansible | [ansible/ansible](https://github.com/ansible/ansible) | `a1730af91f94552e8aaff4bedfb8dcae00bd284d` | 固定任务镜像的项目 COPYING |

两个目录各自保留所取得的 GNU GPL v3 许可文本和 SHA。上游代码与这些派生补丁遵循其相应项目许可；仓库根目录用于评测实现的 MIT 声明不替换这些第三方许可。

补丁仅用于公开任务的可追溯复核。原始模型没有见到本次独立 verifier 的隐藏测试或参考解；不得把交付中自行编写测试通过当成外部验收通过。
