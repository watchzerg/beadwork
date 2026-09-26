set positional-arguments

# 列出当前项目开发命令。
default:
    @just --list

# 检查宿主工具、mise/uv lock 绑定和开发 Python 补丁版本；不安装或升级工具。
check-toolchain:
    #!/usr/bin/env bash
    set -euo pipefail
    command -v mise >/dev/null || { echo '错误：缺少 mise，请先安装宿主 mise。' >&2; exit 1; }
    command -v just >/dev/null || { echo '错误：缺少 just，请先安装宿主 just。' >&2; exit 1; }
    mise exec -- uv run --no-project --offline --no-python-downloads --no-env-file --managed-python --python "$(cat .python-version)" python -B - <<'PY'
    import pathlib
    import subprocess
    import sys
    import tomllib

    def fail(message):
        sys.exit(f"错误：{message}。请按 README 的环境准备顺序修复后重试")

    config = tomllib.loads(pathlib.Path("mise.toml").read_text())
    lock = tomllib.loads(pathlib.Path("mise.lock").read_text())
    entries = lock["tools"]["uv"]
    if len(entries) != 1 or config["tools"]["uv"] not in entries[0]["specifiers"]:
        fail("mise.toml 与 mise.lock 的 uv 声明不一致")
    actual_uv = subprocess.check_output(["uv", "--version"], text=True).split()[1]
    if actual_uv != entries[0]["version"]:
        fail(f"uv 版本不一致：预期 {entries[0]['version']}，实际 {actual_uv}")
    pin = pathlib.Path(".python-version").read_text().strip()
    actual_python = ".".join(map(str, sys.version_info[:3]))
    if actual_python != pin:
        fail(f"Python 版本不一致：预期 {pin}，实际 {actual_python}")
    print(f"uv={actual_uv}；Python={actual_python}；工具链检查通过")
    PY

# 安装 mise 锁定的 uv、项目 Python 和 uv.lock 中的默认开发依赖。
install:
    mise install --locked uv
    mise exec -- uv python install "$(cat .python-version)"
    mise exec -- uv sync --locked --managed-python --python "$(cat .python-version)"

# 格式化指定路径；无参数时处理当前目录。
fmt *paths=".":
    mise exec -- uv run --locked ruff format "$@"
    mise exec -- uv run --locked ruff check --fix "$@"

# 检查约定范围的 lint 与格式，不修改文件。
lint:
    mise exec -- uv run --locked ruff check scripts skills/beadwork-run/scripts tests
    mise exec -- uv run --locked ruff format --check scripts skills/beadwork-run/scripts tests

# 使用 Python 3.14 目标检查仓库脚本、skill 运行源码和 tests。
typecheck:
    mise exec -- uv run --locked ty check

# 使用项目环境中的 PyYAML 运行用户级 skill validator；缺失时明确失败。
validate-skill:
    #!/usr/bin/env bash
    set -euo pipefail
    validator="$HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py"
    if [[ ! -f "$validator" ]]; then
        echo "错误：缺少 skill validator：$validator" >&2
        exit 1
    fi
    mise exec -- uv run --locked python "$validator" skills/beadwork-run

# 运行 unit、integration、workflow、distribution 或 all；额外参数原样传给 pytest。
test suite *args:
    #!/usr/bin/env bash
    set -euo pipefail
    suite="$1"
    shift
    exec mise exec -- uv run --locked python scripts/run_tests.py "$suite" -- "$@"

# 完整门禁：静态检查、全部 pytest 和真实 skill validator 顺序执行，首错停止。
gate-full:
    just check-toolchain
    git diff --check
    just lint
    just typecheck
    mise exec -- uv run --locked python scripts/run_tests.py --gate all
    just validate-skill
