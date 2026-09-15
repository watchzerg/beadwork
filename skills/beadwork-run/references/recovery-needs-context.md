# executor 缺少上下文

- `NEEDS_CONTEXT`：controller 先从 repo、Beads 或工具获取缺失事实，再重新派发一个全新 executor 以 `continuation: resume` 恢复同一 ticket 的当前阶段，沿用原 dispatch 和 review 历史；只有真正的产品决策才交给用户。
