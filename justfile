set positional-arguments

# 列出当前项目开发命令。
default:
    @just --list

# 检查宿主 uv/just 和 uv 管理的开发 Python 补丁版本；不安装或升级工具。
check-toolchain:
    #!/usr/bin/env bash
    set -euo pipefail
    command -v uv >/dev/null || { echo '错误：缺少 uv，请先通过 Homebrew 安装宿主 uv。' >&2; exit 1; }
    command -v just >/dev/null || { echo '错误：缺少 just，请先安装宿主 just。' >&2; exit 1; }
    uv run --no-project --offline --no-python-downloads --no-env-file --managed-python --python "$(cat .python-version)" python -B - <<'PY'
    import pathlib
    import subprocess
    import sys

    def fail(message):
        sys.exit(f"错误：{message}。请按 README 的环境准备顺序修复后重试")

    actual_uv = subprocess.check_output(["uv", "--version"], text=True).split()[1]
    pin = pathlib.Path(".python-version").read_text().strip()
    actual_python = ".".join(map(str, sys.version_info[:3]))
    if actual_python != pin:
        fail(f"Python 版本不一致：预期 {pin}，实际 {actual_python}")
    print(f"uv={actual_uv}；Python={actual_python}；工具链检查通过")
    PY

# 使用宿主 uv 安装项目 Python 和 uv.lock 中的默认开发依赖。
install:
    uv python install "$(cat .python-version)"
    uv sync --locked --managed-python --python "$(cat .python-version)"

# 格式化指定路径；无参数时处理当前目录。
fmt *paths=".":
    uv run --locked ruff format "$@"
    uv run --locked ruff check --fix "$@"

# 检查约定范围的 lint 与格式，不修改文件。
lint:
    uv run --locked ruff check scripts skills/beadwork-run/scripts tests
    uv run --locked ruff format --check scripts skills/beadwork-run/scripts tests

# 使用 Python 3.14 目标检查仓库脚本、skill 运行源码和 tests。
typecheck:
    uv run --locked ty check

# 使用项目环境中的 PyYAML 运行用户级 skill validator；缺失时明确失败。
validate-skill:
    #!/usr/bin/env bash
    set -euo pipefail
    validator="$HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py"
    if [[ ! -f "$validator" ]]; then
        echo "错误：缺少 skill validator：$validator" >&2
        exit 1
    fi
    uv run --locked python "$validator" skills/beadwork-run

# 运行 unit、integration、workflow、distribution 或 all；额外参数原样传给 pytest。
test suite *args:
    #!/usr/bin/env bash
    set -euo pipefail
    suite="$1"
    shift
    exec uv run --locked python scripts/run_tests.py "$suite" -- "$@"

# 完整门禁：静态检查、全部 pytest 和真实 skill validator 顺序执行，首错停止。
gate-full:
    just check-toolchain
    git diff --check
    just lint
    just typecheck
    uv run --locked python scripts/run_tests.py --gate all
    just validate-skill
