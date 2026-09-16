# 部分报告与交付故障

正常使用角色的 assemble/check/deliver。仅在缺 dispatch、采集器异常或需要诊断报告结构时读取本文件；底层自检不能代替来源链、现场与收尾验收。

preflight collect 异常或只留下半成品时，保留原目录，按原 schema 写部分 BLOCKED 并自检：

```bash
python3 <skill-dir>/scripts/verify-phase.py --check-report preflight <report.json> --expected <dispatch.json> --emit-receipt
```

executor 缺可用 dispatch 时，可对按 schema 填写的部分报告做结构自检：

```bash
python3 <skill-dir>/scripts/verify-ticket.py --check-report <report.json> --emit-receipt
```

这不构成 ticket DONE 或 controller 完整验收。恢复有效 root/stage 后仍须 ticket-deliver/controller accept。不能伪造 implementer/reviewer 来源补齐结构。

历史阶段或 worker 报告诊断使用：

```bash
python3 <skill-dir>/scripts/verify-phase.py --check-report <preflight|finalizer> <report.json> --expected <dispatch.json> --emit-receipt
python3 <skill-dir>/scripts/verify-worker.py --check-report <implementer|fixer|reviewer> <report.json> --expected <dispatch.json> --emit-receipt
```

需核对 schema 时，对应 verifier 使用 `--schema` / `--receipt-schema`，phase/worker 后带角色，ticket 不带角色。仅按已知角色与身份生成，不猜测不可读取的 schema 或更改 dispatch 绕过失败。无法形成合法报告时向派发者返回具体错误、已有文件与未知事项，恢复材料后再正式交付。

自检非零退出不产生有效回执；修正使用新文件，保留旧报告和错误。派发者仍使用正常 accept/collect；历史报告只读兼容不自动授予当前契约的成功状态。
