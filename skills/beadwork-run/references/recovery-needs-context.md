# executor 缺少上下文

controller 先从 repo、Beads 或工具获取 requested_context 指定的事实，再恢复原 executor root；可继续原 executor 时继续，需接替时交接 root 检查点。executor 接续当前 stage 和已有 review，不重新分配实现或修复额度。只有真正的产品决策才交给用户。

补齐的事实写入新的证据文件，通过 report-delivery.md 的 context-add 追加来源绑定；恢复时将返回的 context_sources 交给当前实现者。只补事实，不以改 dispatch 或新建 root 改变 BASE、需求、seam 或额度。
