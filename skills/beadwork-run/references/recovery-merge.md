# 合入命令恢复

checkpoint 表示已记录合入目标，不单独证明 merge 成功。命令中断后，保持相同参数重跑：若 main 仍为受审 BASE 则尝试合入；若已有相同 checkpoint 且 main 已等于受审 HEAD，则返回成功；其他移动停止。合入前输出文件写入失败不会移动 main。controller 不因失败而 reset，仍写停止记录。
