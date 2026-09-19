# Beadwork 项目工程化改造计划

状态：阶段 1–3 已完成；阶段 4–6 尚未开始。

制定日期：2026-09-19。本文供后续独立 session 顺序实施、勾选和交接使用；不是本轮实施授权记录。

## 1. 已批准的设计与范围

- skill 运行源码最低支持 Python 3.14，仅依赖标准库和 skill 自带模块。运行时不依赖 uv、mise、pytest、Ruff、ty 或仓库开发环境。
- 整个 `skills/beadwork-run/` 是独立分发单元；内部允许正常 import，不要求每个模块单独复制后运行。
- 唯一公开 Python CLI 为 `python3 <skill-dir>/scripts/beadwork.py <command> …`，标准库 `argparse` 路由，内部直接调用 Python API。
- 不考虑旧 CLI、旧参数或正在进行中的 flow 兼容；删除被替代入口，不增加兼容 wrapper、别名或迁移器。不测试历史 flow 的接续能力。
- 保持工作流业务语义：角色权限、阶段规则、报告字段、append-only 证据、branch/worktree 布局等不因工程化改造改变。新命令记录使用新入口；不修改消费项目的既有证据。
- 开发侧使用 mise、uv、Ruff、ty、pytest、pytest-xdist、just。ty 按 x-media-saver 的方式管理：manifest 声明版本范围，`uv.lock` 固定实际版本；不因其 beta 状态另加审批流程。
- 用户层 `~/.codex/skills/.system/skill-creator/scripts/quick_validate.py` 是明确的开发前置依赖，由 just 封装。缺失即非零失败；不下载、复制、锁定或重写 validator。
- 不新增应用打包后端、PyPI 发布、常驻服务、插件框架、自动 commit/push 或真实消费项目执行。
- 只修改本仓库。不得升级用户级 mise、just、Python、skills 或修改隔壁项目；它们缺失时报告前置条件。

Python 3.14 是长期兼容下限，不是必须永远停留的开发版本。提高下限必须作为单独兼容性变更提出；日常依赖升级不得顺带提高它。初期开发解释器也使用 3.14，并固定补丁版本。

## 2. 执行规则与 session 交接

每个大阶段使用一个新 session，按阶段 1 → 2 → 3 → 4 → 5 → 6 顺序执行。阶段内任务按编号实施；完成一个任务并完成相应验证后，才将其改为 `[x]`。阶段内允许短暂调整，但阶段结束必须留下可运行、可验证的工作区。

每次 session 开始：

1. 阅读本文件、根目录 `AGENTS.md`、本阶段涉及的当前源码与文档；以实时文件为准。
2. 检查 Git 状态，保留已有修改。核对上一阶段完成记录，不把“打勾”当作当前文件仍正确的唯一证据。
3. 执行本阶段，不自动进入下一大阶段；发现必要遗漏时直接修订本文对应任务，并在阶段记录说明原因。
4. 使用当前阶段已经存在的验证入口。本文标注的目标入口在创建前不能作为已可执行命令。
5. 小任务失败或只完成部分时不勾选；记录具体剩余项。环境缺失不记为测试通过，也不通过跳过检查让门禁变绿。

阶段结束在本文的阶段记录中填写：完成任务、主要改动、验证命令与结果、限制或待办、下一阶段入口。若用户另行要求提交，记录 commit SHA；本计划不自动授权 commit/push。无需为每个小任务创建独立报告或强制提交。

可用于新 session 的请求：

```text
请执行 docs/project-modernization-plan.md 的阶段 N。
先读取计划和 AGENTS.md，核实前序阶段记录，按顺序实现并验证小任务，
逐项标记完成状态，最后更新阶段记录；不要自动进入下一大阶段。
```

## 3. 目标结构与边界

```text
AGENTS.md                         维护约束与验证选择
mise.toml / mise.lock              项目工具声明与解析版本
.python-version                   开发 Python 3.14 的具体补丁版本
pyproject.toml / uv.lock           开发依赖、Ruff、ty、pytest 配置
justfile                          公开开发命令和门禁顺序
scripts/maintenance_check.py       仓库专用结构、链接等检查；不编排整个门禁
skills/beadwork-run/
  SKILL.md / agents/ / references/ 随 skill 分发的指令与协议
  scripts/
    beadwork.py                    唯一公开 Python CLI
    cli.py                        argparse 注册、输出和错误边界
    …                             按职责组织的内部模块
tests/
  conftest.py                      最小 marker 完整性检查与公共 fixture
  …                             按行为领域组织，显式 markers 分层
docs/                             架构、接入及维护说明
```

采用现有平铺模块基础，避免同时增加安装式 package 或大规模嵌套目录。内部文件名统一为可 import 的 snake_case。基础模块不依赖 CLI；CLI 可以依赖操作模块。消除真实依赖回路，不能通过动态 import 或通用回调掩盖回路；确有启动需求的延迟加载须有明确原因。

mise 管理项目使用的 uv；uv 管理开发 Python、虚拟环境和 Python 开发依赖，不再让 mise 重复管理同一个 Python。just 和 mise 自身作为宿主前置工具检查，不修改用户级安装。锁文件支持范围以实际安装平台为准，不声明未经测试的平台支持。

项目所需 uv/Python 的安装属于正常环境准备，允许工具使用其常规安装目录和缓存；“不升级用户级工具”指不执行全局升级、不改变全局默认版本，不是禁止安装项目锁定的解释器。新机器的准备顺序为：确认宿主 mise/just → 安装项目声明的 uv → 准备 `.python-version` 指定的 Python → locked sync → 检查和门禁。`check-toolchain` 只检查，不要求通过它才能执行用于补齐环境的 install；具体准备命令由阶段 1 核实后写入 README。

### 3.1 CLI 命令迁移目标

| 当前入口 | 最终公开调用前缀 |
| --- | --- |
| `controller.py` | `beadwork.py controller` |
| `executor-operations.py` | `beadwork.py executor` |
| `preflight-operations.py` | `beadwork.py preflight` |
| `plan-operations.py` | `beadwork.py plan` |
| `graph.py` | `beadwork.py graph` |
| `run-verification.py` | `beadwork.py run-verification` |
| `verify-ticket.py` | `beadwork.py verify ticket` |
| `verify-phase.py` | `beadwork.py verify phase` |
| `verify-worker.py` | `beadwork.py verify worker` |

各组的业务动作和必要参数按现有能力映射；全组注册到 argparse，`--help` 能逐级发现。不要只将剩余 argv 转交给依赖全局 `sys.argv` 的旧 main。只在顶层转换退出码和 CLI 错误，内部 API 返回值或抛出明确异常，不修改全局 argv、不主动 `sys.exit()`。正常机器可读输出保持 JSON，不混入帮助性日志；诊断走 stderr，参数错误与操作失败均非零。

明确区分“检查已经完成但结果不通过”和“检查无法执行”：前者保留 stdout 的结构化失败结果（如 `ok: false`），同时返回非零退出码；后者在 stderr 输出明确诊断并非零退出。帮助正常退出，argparse 参数错误沿用其错误边界。同步更新新调用者对返回码的处理，不能仅因有 JSON 输出就认定成功。统一入口在加载运行模块前检查 Python 下限，并给出版本不足的明确提示；这个小启动段不使用会让版本检查本身无法解析的新语法。

本表是迁移清单，实施时须扫描全部实际入口补齐，不得因表中遗漏删除现有能力。生成 `self_check_argv` 等命令的地方统一使用简单的 argv 构造函数，不启动子进程、不拼 shell 字符串。

### 3.2 测试分层

| 主 marker | 判定标准 | 示例 |
| --- | --- | --- |
| `unit` | 被测行为和 fixture 准备纯内存，无真实文件、命令或服务 | JSON 字符串解析、字段规则、图判定、纯状态转换 |
| `integration` | 验证一个明确能力与真实本地边界协作 | 文件发布、绑定、symlink、Git/worktree、CLI、进程组、独立分发 |
| `workflow` | 连续多个操作的产物衔接、阶段推进或恢复 | prepare → 验证 → 验收 → 下一阶段；最终集成与清理 |

每例恰好一个主 marker；`distribution` 是 integration 的专题 marker。pytest 自身读取源码、写缓存和报告不计入 unit 边界。一次真实 Git 操作不自动算 workflow；一次纯状态转换也不自动算 workflow。

使用模块级 `pytestmark` 或类/函数级 marker；一个模块混合层次时按实际类/函数标记，必要时拆文件。分层事实来自 marker，不从目录或文件白名单推断。不按耗时自动分类。`--strict-markers` 检查未知名称，最小 collection hook 检查漏标、多主层和错误使用 distribution；不要开发通用测试分类框架。

保留有效的 unittest 测试；有收益时再改为 pytest fixture、参数化或函数式用例。纯规则直接测 API，CLI 测试只覆盖真正入口行为，workflow 集中覆盖衔接和恢复，不重复穷举所有规则矩阵。涉及文件系统语义时使用真实临时文件，不用 mock 文件系统代替验收。

### 3.3 开发命令与完整门禁

目标 just recipes：`check-toolchain`、`install`、`fmt [PATHS...]`、`lint`、`typecheck`、`check-docs`、`validate-skill`、`test <suite> [ARGS...]`、`gate-full`。

- `test` 的 suite 为 `unit`、`integration`、`workflow`、`distribution`、`all`，用 pytest marker 选择，剩余参数保持 argv 边界；默认不允许调用者用另一个 `-m` 覆盖 suite。零匹配沿用 pytest 非零结果。
- unit 默认串行；integration/workflow/distribution/all 默认 xdist 4 workers、`--dist=worksteal`，允许通过明确的 jobs 配置切换串行诊断，不把线程数写成性能承诺。
- `test all` 不加主 marker 的排除表达式，收集全部测试并执行分类检查；distribution 只执行一次。
- 完整门禁的 pytest 调用不继承会缩小测试范围的 `PYTEST_ADDOPTS`，不转发路径、`-k`、`-m` 等筛选。日常 `test` 仍可定向选择。marker 检查按有效主 marker 名称的集合判断，避免模块/类继承同名 marker 被误判为两个层次。
- `install` 使用 locked sync；日常运行使用 locked uv 命令。格式化可以修改源码，所有 gate 只检查不自动修复。
- `validate-skill` 由 just 显式检查用户 validator 路径，并用项目 uv Python 环境运行，PyYAML 放在 dev 组。用户路径用正确引用处理，不写死用户名；缺失文件打印路径后失败，不动态 `--with` 安装。
- `gate-full` 由 just 单一编排：工具链检查 → 文档/结构检查 → lint/format check → ty → `test all` → validator，首错停止，不接受筛选参数。开发脚本不再嵌套调用整套门禁。
- 阶段 1 的过渡门禁只包含已建立的检查；阶段 3 后启用完整静态检查，阶段 5 后自动覆盖分发测试。必须在阶段记录明确当时覆盖，不提前宣称最终门禁已完成。
- Beadwork 维护入口不必照搬消费项目的全部 recipe 协议，也不复制隔壁业务依赖、Docker gate 或自动 Git 交付逻辑。

suite、jobs 和额外 pytest 参数的转发若在 just 中难以清楚表达，可使用一个仓库专用的小型测试 runner；它只构造并执行一次 pytest argv，不维护第二份完整门禁顺序。不要把复杂 shell 参数解析塞入 recipe，也不要引入通用任务调度框架。

## 4. 阶段 1：固定运行边界，建立开发工具和 just 入口

目标：为后续改造提供统一环境和可工作的门禁；暂不迁移 CLI，不全仓格式化。

- [x] **1.1 盘点基线。** 检查 Git、Python/uv/mise/just、validator 可用性；记录当前测试收集数量和已有完整门禁结果及耗时。需要权限时遵循 AGENTS.md；缺失环境明确记录，不修改用户工具。现有基线命令为 `uv run python skills/beadwork-run/scripts/maintenance_check.py full --jobs 4`。
- [x] **1.2 固定开发环境。** 添加项目 mise 配置及可适用的 lock、`.python-version`；Python 下限改为 `>=3.14`，运行 dependencies 仍为空。选取实施当时稳定 uv/Python 补丁版本，明确排除预发布；不把所有依赖任意加主版本上限。
- [x] **1.3 更新开发依赖。** 纳入 Ruff、ty，升级 pytest/xdist/PyYAML，按隔壁的范围声明与 uv.lock 方式锁定，设置 prerelease 策略。ty 使用正常已发布版本，保留其 beta 工具定位。完成 locked sync，记录实际版本。
- [x] **1.4 分离仓库维护脚本。** 将 `maintenance_check.py` 移到仓库 `scripts/`，调整根路径推导、测试 import 和当前命令引用；保留有价值的链接、语法、策略/结构检查。链接检查覆盖根目录 README.md、AGENTS.md 以及 docs/、skill 文档，不能遗漏两个主要维护入口。完整门禁和 validator 编排移入 just；相应旧维护入口直接删除，不留转发器。
- [x] **1.5 建立 just 命令。** 实现工具链检查、安装、文档检查、validator、分层测试和过渡 gate-full；参数带空格能正确传递，未知 suite/无测试/子命令失败均失败。lint/typecheck 待阶段 3 正式纳入门禁，不伪造占位成功 recipe。
- [x] **1.6 更新维护约束。** AGENTS.md 和 README 写明 Python 3.14、标准库边界、开发前置依赖、锁定方式、当前可用命令和不考虑历史兼容。同步活跃 skill 文档的最低版本描述。
- [x] **1.7 验证并交接。** 从 locked 环境运行现有全量测试、文档/结构检查和真实 validator。对开发命令的参数转发与失败传播做必要的小范围验证；更新阶段记录。

完成条件：新 just 入口真实可用；仓库维护脚本不再随 skill 分发；原有回归没有因搬迁丢失；缺失 validator 的失败有清晰诊断。阶段 1 的旧 marker 分类仍待阶段 2 修正，不宣称 unit 已纯内存。

## 5. 阶段 2：重整 pytest 分层和测试准备

前置：阶段 1 完成。目标：在运行入口重构前，建立可信的回归边界。

- [x] **2.1 逐例分类。** 盘点所有测试及 fixture 的文件、Git、CLI、跨步骤依赖，登记到源码 marker；重点修正 `test_evidence.py`、`test_review_reuse.py`、`test_verification_records.py`、`test_maintenance_check.py` 的现有 unit 误分类。不因文件名包含 workflow 就整体归为 workflow。
- [x] **2.2 替换自动白名单。** 删除 `UNIT_MODULES`/`WORKFLOW_MODULES` 分类推断；注册 markers、添加最小完整性检查。在隔离的小型 pytest collection 测试中验证漏标、多主层、未知 marker、distribution 非 integration 的失败。
- [x] **2.3 整理 fixture。** 共享必要的临时仓库、worktree、命令替身和证据构造；避免可变全局现场和测试间复用同一个 Git 目录。确认环境变量恢复的必要边界，优先 scoped monkeypatch，不为统一风格强制重写全部 unittest。
- [x] **2.4 优化重复覆盖。** 把纯规则矩阵放到 unit，将入口行为留在 integration；workflow 保留阶段衔接、失败恢复和证据链关键路径。删减测试须记录被哪项等价或更强的断言覆盖，不以减少数量为目标。
- [x] **2.5 对齐命令与文档。** `just test` 真实使用 markers；在 AGENTS.md 明确各层定义、选择场景和零匹配行为。此阶段尚无 distribution 测试时，该筛选可以非零，不添加占位用例。
- [x] **2.6 验证并交接。** 分别收集三个主层，开发时定向运行受影响用例，最终用一次过渡完整门禁验证全部回归；比较调整前后覆盖及耗时。确认全部 collection 数等于三个互斥主层数量之和，并行执行无共享现场故障；更新阶段记录。不为统计分层结果先完整跑三层再原样重跑全部测试。

完成条件：所有测试显式且唯一分类；unit 的测试行为和准备不使用真实 I/O；各层回归仍覆盖原有业务语义。

## 6. 阶段 3：接入 Ruff 和 ty，收敛静态质量基线

前置：阶段 2 完成。目标：在 CLI 重构前消除基础静态问题，后续每阶段使用同一质量门禁。

- [x] **3.1 配置检查范围。** Ruff 和 ty 覆盖 skill 运行源码、仓库开发脚本和 tests，运行源码检查目标明确为 3.14。Ruff 从 E/F/I/UP/B 等高收益规则开始，结合实际决定 W/SIM；不要为追求规则数量增加无关改写。
- [x] **3.2 处理格式与基础 lint。** 执行格式化和安全修复，人工检查语义变化；格式变更与行为修正清楚区分，不顺带改 CLI 和协议。
- [x] **3.3 建立有效类型边界。** 给公开内部 API、报告/状态的核心结构和外部输入解析补足有价值的标注；用标准库 TypedDict/dataclass 等按实际结构选择。外部 JSON 仍做运行时校验，不因类型声明信任数据；不引入第三方 schema 库，不用全局 Any/ignore 掩盖问题。
- [x] **3.4 修正真实问题。** 处理未定义变量、遮蔽、错误返回类型和不清晰的数据流。必要局部豁免说明原因；不整体排除 tests 或运行模块，不开发泛化类型框架。
- [x] **3.5 启用正式静态门禁。** 完成 `fmt`、`lint`、`typecheck`，gate-full 纳入 Ruff check、format check、ty；复用锁定版本，不在 gate 中安装最新工具。
- [x] **3.6 验证并交接。** 静态检查和全部回归通过，确认运行 dependencies 为空、源码没有新增第三方 import；记录实际诊断清理范围和剩余合理豁免。

完成条件：全仓约定范围静态检查通过，已有完整回归通过；从下一阶段开始门禁不能临时关闭这些检查。

## 7. 阶段 4：集中完成统一 CLI 与单解释器内部调用

前置：阶段 3 完成。目标：一次 session 完成入口切换，结束时只保留最终 CLI，不留下半迁移状态。

- [ ] **4.1 完整列出调用者。** 搜索脚本入口、`__main__`、`sys.argv`、subprocess、`self_check_argv`、dispatch/draft、fixture、Markdown 和开发检查中的命令引用，补齐 3.1 表。区分实际执行、argv 生成、业务外部命令，避免把后两者都当作嵌套 Python。
- [ ] **4.2 建立薄入口与解析层。** 新建 `beadwork.py` 和 `cli.py`，按表注册全部命令。内部 main 改为明确参数/API，集中处理 JSON、stderr 和退出码。脚本从任意 cwd 和 symlink 路径可加载自带模块。
- [ ] **4.3 整理模块边界。** 将 preflight/plan 的连字符文件改为内部 snake_case 模块；删除旧 wrapper 和各内部模块的公开 CLI 启动段。入口只路由，Git/Beads 权限仍由对应操作层掌握；更新 import 边界测试，不允许基础层反向依赖 CLI。
- [ ] **4.4 消除无价值的自启动。** 内部 verifier/schema/状态计算直接 API 调用；preflight 的多次 schema Python 启动改为内部生成并保留所需事实产物。只为冷启动验收保留独立进程测试，不在正常工作流反复自检同一加载事实。外部 Git、bd、just、gate 的执行、超时和进程组语义保留。
- [ ] **4.5 统一生成命令。** 所有 self-check、dispatch、draft 和测试 fixture 输出新 argv；使用小型共享构造函数保证解释器与 skill 路径一致。不通过 shell 转义字符串传递用户参数。
- [ ] **4.6 更新活跃指令与测试。** 更新 SKILL.md、agents、references、README、AGENTS.md、ARCHITECTURE 和真实测试调用。当前规范不留旧入口；历史实施记录保持历史事实，若文件被删除导致旧 Markdown 链接断裂，可将旧路径改为 inline code 并注明历史，不创造兼容文件。
- [ ] **4.7 验证最终 CLI。** 检查顶层和各组帮助、未知命令/缺参数、版本不足提示、JSON stdout、错误 stderr、结构化校验失败的非零退出及关键业务参数；版本分支可在测试中模拟，不要求额外安装旧 Python。代表性内部 API 校验在禁止启动子进程的条件下通过；CLI 测试与必须的 Git/gate 进程不受该禁令影响。检查新进程中的正常工作流恢复能力，不测试旧版本 flow 兼容。
- [ ] **4.8 全量验收并交接。** 跑 gate-full，检查新命令生成→执行→读取的 workflow，扫描活跃文档和代码无旧入口引用；更新阶段记录和最终命令映射。

完成条件：唯一公开 Python CLI 为 beadwork.py；所有现有能力可经新入口使用；没有旧入口兼容层；内部纯计算不重新启动 Python；完整门禁通过。

## 8. 阶段 5：独立分发与最低版本验收

前置：阶段 4 完成。目标：自动验证开发环境不会成为 skill 的隐式运行依赖。

- [ ] **5.1 明确分发内容。** 以 `skills/beadwork-run/` 为分发根，排除 bytecode/cache 等生成文件；根目录的 tests、开发 scripts、.venv、工具配置不进入分发。先使用测试内的简单复制，不建立发布系统或打包后端。
- [ ] **5.2 建立隔离 fixture。** 将内容复制到临时独立位置，从无关 cwd 启动已准备的 Python 3.14；清除 PYTHONPATH 等开发路径注入，以 `-S` 禁用 site-packages、`-B` 禁止 bytecode。不要盲目使用会移除脚本目录搜索路径的隔离参数导致正常自带模块无法 import。测试运行时不下载解释器。
- [ ] **5.3 验证真实运行。** 顶层及所有命令组帮助、具备 schema 能力的各角色 schema、代表性报告文件操作和本地 Git 边界可运行；测试环境可提供明确的外部命令替身。标准库允许来自解释器安装目录，所有 Beadwork 自带模块及运行资源必须来自复制后的分发目录，不能回读原仓库。验证分发文档/资源的相对引用在复制后仍有效，且没有逃逸到原仓库的 symlink；源仓库内链接检查不能替代这一项。验证缺少必需工具时的清晰失败；既有 symlink 安装路径单独覆盖。
- [ ] **5.4 检查依赖边界。** 增加运行源码 import 的标准库/自带模块检查，覆盖直接 import 和实际动态加载路径；结合隔离运行验证，不能只检查 `dependencies=[]`。无需为任意动态代码建立通用静态分析器。
- [ ] **5.5 集成 marker 与门禁。** 分发测试标记 integration + distribution，`just test distribution` 可独立运行，`test all` 中只运行一次。缺少最低版本解释器时该必要验收失败，不 skip；开发工具检查说明准备方式。
- [ ] **5.6 验证并交接。** 运行分发 suite、完整门禁，记录实际 Python 版本、宿主平台和测试范围；不把当前 macOS 验收写成已通过 Linux/Windows 矩阵。未来开发 Python 高于下限时，继续独立准备 3.14 运行这些测试。

完成条件：只有分发目录与声明的外部工具即可执行被验收行为；无第三方 Python 包和仓库开发路径依赖；最低版本验证是完整门禁的必需部分。

## 9. 阶段 6：最终收敛、自审与维护交接

前置：阶段 5 完成。目标：核对改造结果形成一致、可维护的正式项目，不增加新的产品范围。

- [ ] **6.1 最终扫描。** 核对唯一入口、第三方 import、开发/运行目录、工具版本声明、marker 完整性、重复门禁执行与失效文件。清除迁移遗留代码，不删除有独立价值的业务回归。
- [ ] **6.2 整理长期维护说明。** README 保留安装与常用命令；AGENTS.md 保留约束与验证选择；ARCHITECTURE 描述最终模块职责。版本数字以配置/锁文件为准，除运行下限外避免在多处重复补丁版本。本文保留阶段记录，不替代长期文档。
- [ ] **6.3 固定验证选择表。** 将下节规则落实到维护文档，区分本地 fixture workflow、真实 Beads 服务与真实 Codex 派发的证据范围。记录用户 validator 是未锁定的宿主依赖，这是已接受的设计。
- [ ] **6.4 最终完整验证。** locked install 后运行 gate-full；确认完整测试包含分发，收集数量与主层数量一致。验证必要前置条件缺失时明确失败，避免重复运行已经在本次门禁成功的同一批检查。
- [ ] **6.5 自行 review 并修正。** 对照第 1 节逐项检查；检查 CLI 组是否遗漏能力、业务语义是否意外变化、类型豁免是否过宽、测试是否只重复实现、有没有引入未请求的兼容/发布机制。修正后仅重跑受影响检查，必要时完整门禁。
- [ ] **6.6 完成交接。** 填写最终结果、验证限制与可能后续事项，确认各阶段任务真实完成。没有真实 agent/Beads 验收时明确说明，不因缺少范围外验收将本计划无限延长。

完成条件：六阶段完成，正式维护说明和实际命令一致，完整门禁通过，交付范围可准确说明。

## 10. 修改场景与验证选择

| 场景 | 开发迭代验证 |
| --- | --- |
| 纯规则、解析、状态计算 | 相关 unit |
| 文件发布、绑定、symlink、Git、外部进程 | 相关 integration，加被修改的纯规则测试 |
| 多阶段推进、恢复、关闭、集成 | 相关 workflow，加受影响的低层测试 |
| CLI、import、目录、运行版本、分发内容 | CLI integration + distribution，涉及命令衔接时加 workflow |
| 文档文字与链接 | check-docs + diff check；执行命令变化加相关 CLI 验证 |
| 工具链升级、跨模块协议或目录迁移、大阶段交付 | 当时已建立的完整 gate-full；阶段 5 起必须包含 distribution |

完整门禁不接受筛选参数。日常开发使用最窄充分验证；不因每个小任务都修改了 Python 而每次重复完整 workflow。全部脚本测试通过仍不等于真实 Codex 嵌套派发已验证。

## 11. 阶段完成记录

各阶段实施者填写本节；计划制定时留空，避免把设计审查当作实施证据。

| 阶段 | 状态 | 改动与验证摘要 | 限制/待办/下一步 |
| --- | --- | --- | --- |
| 1 开发环境与入口 | 已完成（2026-09-19） | 基线：宿主 Python 3.14.7、uv 0.12.10、mise 2026.9.10、just 1.58.0 和 validator 可用；旧 uv 环境为 Python 3.12.14，收集 315 项，旧 full 315/315 通过（pytest 137.60 秒、整体 137.85 秒），validator 通过。新增 `mise.toml`/`mise.lock`、`.python-version`、justfile 和仓库测试 runner；开发 Python 固定 3.14.7 并由 uv 管理，uv 锁定 0.12.10，运行 dependencies 保持为空；locked 开发版本为 pytest 9.1.1、xdist 3.8.0、PyYAML 6.0.3、Ruff 0.16.8、ty 0.0.82。`maintenance_check.py` 已移到根 `scripts/`，旧 skill 内入口删除；根 README/AGENTS、docs、skill 文档链接、结构、explicit-only policy 和 Python 语法由新入口检查。`just install`、`check-toolchain`、`fmt`、`check-docs`、`validate-skill`、`test`、过渡 `gate-full` 已建立。最终 `just gate-full` 在 uv-managed Python 3.14.7 下 319/319 通过（pytest 121.19 秒、整体 122.41 秒），真实 validator 通过；`just check-docs` 与 `git diff --check` 通过。定向验证确认带空格 `-k` 保持 argv 边界，未知 suite/额外 `-m` 返回 2，零匹配返回 5。 | 当前 marker 仍有阶段 2 要修正的历史误分类；尚无 distribution 测试，Ruff/ty 尚未进入 gate。未运行真实消费项目 ticket graph，未验证真实 Codex 嵌套派发。未提交或 push。下一入口：阶段 2.1 逐例分类。 |
| 2 测试分层 | 已完成（2026-09-19） | 删除 `UNIT_MODULES`/`WORKFLOW_MODULES` 自动白名单，全部测试在源码中显式声明且唯一归入主 marker；继承的同名 marker 按集合去重，`distribution` 必须同时属于 `integration`。四个点名文件已从错误的 unit 改为 integration；纯内存规则只保留在 `graph`、`stage_policy`、`workflow_contract`，阶段推进、恢复和证据链关键路径归 workflow。新增 7 项隔离 collection 契约测试，覆盖漏标、多主层、未知 marker、错误 distribution 组合及合法继承/组合。环境变量现场由全局 autouse 快照恢复改为相关 unittest 的 scoped `patch.dict`；审计未发现可由等价或更强断言安全替代的业务用例，因此原 319 项业务回归全部保留。调整前分层为 unit 34、integration 173、workflow 112；调整后为 unit 18、integration 129、workflow 179，另增 7 项契约测试，总计 326，三个主层互斥且总和一致。定向验证为 unit 18/18、相关 integration 28/28、batch workflow 8/8；`just check-docs` 通过；`just test distribution --collect-only -q` 因零匹配按预期返回 5。最终仅运行一次 `just gate-full`：工具链和维护检查通过，4 个 xdist worker 下 326/326 通过（pytest 106.15 秒；阶段 1 的 319 项记录为 121.19 秒），真实 validator 通过。 | 尚无 distribution 测试；Ruff/ty 仍按计划在阶段 3 纳入门禁。耗时只是本机本次观测，不作为性能承诺。未运行真实消费项目 ticket graph，也未验证真实 Codex 嵌套派发；未提交或 push。下一入口：阶段 3.1 配置静态检查范围。 |
| 3 静态质量 | 已完成（2026-09-19） | `pyproject.toml` 已将 Ruff 和 ty 的检查范围固定为仓库 `scripts/`、skill 运行源码和 tests，并明确 Python 3.14 目标；Ruff 启用 E/F/I/UP/B 高收益规则，未启用 W/SIM。全仓 Python 已建立 Ruff format 基线并完成安全 lint 修复；`ExecutionPlan` 与 preflight `CommandResult` 使用标准库 `TypedDict` 固定核心边界，外部 JSON 仍由运行时逐字段校验，测试中的异构 JSON 仅在局部 fixture 标注 `dict[str, Any]`。修正了可能为空的 regex/查找结果、动态 stream 方法、异构命令结果、未使用值、错误 fixture import 和 `zip(strict=...)` 等真实静态问题。新增可独立运行的 `just lint`、`just typecheck`，`gate-full` 现按文档/结构 → Ruff lint/format → ty → 全量 pytest → validator 执行。定向回归先后通过 integration 60/60、workflow 128/128，以及最终边界补强后的 execution-plan 16/16、preflight 14/14；最终 `just gate-full` 在 Python 3.14.7 下 Ruff/ty 通过，326/326 测试通过（pytest 143.65 秒），真实 validator 通过。运行 `dependencies` 仍为空，新增 import 仅来自标准库或仓库自带模块。 | Ruff 全局忽略 `E501`，由 formatter 统一布局但不强制拆分所有长字符串；4 个公开脚本为在加载内部模块前设置 `sys.dont_write_bytecode`，保留有说明的局部 `E402` 豁免。尚无 distribution 测试；未运行真实消费项目 ticket graph，也未验证真实 Codex 嵌套派发。未 push。下一入口：阶段 4.1 完整列出调用者；本 session 不进入阶段 4。 |
| 4 CLI 与内部调用 | 未开始 | — | 依赖阶段 3 |
| 5 独立分发 | 未开始 | — | 依赖阶段 4 |
| 6 最终验收 | 未开始 | — | 依赖阶段 5 |

## 12. 计划自审记录

2026-09-19，制定者自行审查；未派发子 agent，未实施代码改造。

- 已确认六阶段顺序让测试边界和静态基线先于 CLI 改造，分发验收针对最终入口实施。
- 已避免循环依赖：阶段 1 不要求尚未清理的 Ruff/ty 通过；阶段 2 不要求尚未创建的 distribution suite 成功；各阶段明确门禁当时覆盖。
- 已明确旧入口直接删除，不引入历史兼容或在途 flow 迁移；当前正常恢复行为仍属于产品回归。
- 已将用户 validator 固定为 just 调用的宿主前置条件，缺失失败，不改为版本化依赖或自动安装。
- 已区分主 marker 与 distribution 专题，避免全量门禁重复执行分发用例；完整收集不隐藏漏标测试。
- 二次审阅修正：阶段 2 改为分层收集加一次完整运行，避免为统计重复执行全套测试；允许小型 argv runner，明确 just 仍是完整门禁顺序的唯一维护位置。
- 已把动态生成 argv、历史文档失效链接、内部 main 退出处理、模块边界和冷启动纳入 CLI 阶段，避免只替换文件名。
- 已明确最低解释器在测试前准备、测试中不下载、缺失不 skip，以及隔离参数不能破坏自带模块加载。
- 已区分计划自审与真实执行证据，所有实施任务保持未勾选；后续每个 session 都有明确停止点和交接位置。

再次全文 review 后的修正（2026-09-19）：

- 补齐新机器环境准备顺序，消除“安装项目解释器”与“不升级全局工具”可能产生的冲突，以及先通过检查才能安装缺失工具的循环依赖。
- 明确结构化校验失败仍必须非零退出；现有 verifier 存在输出失败 JSON 后正常返回的路径，新 CLI 必须同步修正结果与退出码处理。
- 补上入口的 Python 下限检查；最低版本不能只写在开发 metadata 中。
- 修正分发验收“Python 模块不能来自仓库外”的过宽表述，允许解释器标准库，并补查分发后的资源引用和 symlink，避免只验证 Python import。
- 补上根 README/AGENTS 链接检查、完整门禁的环境筛选隔离，以及继承同名 marker 的正确判定。六阶段和 39 项任务数量保持不变，无新增用户决策。
