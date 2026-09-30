# EDA 无关调用接口 v1

核心 skill 负责电路解释、约束生成和证据审查；调用方负责工程导出、软件操作和仿真/测量工具调用。这里提供接口契约与可插入流程，**尚未实现或安装任何 EDA 适配器**。不依赖嘉立创、KiCad、Altium或某个自动布线器；不同客户端的skill发现与调用机制仍由客户端决定。约束包和审查结果的机器可校验形状分别见 [`constraints.schema.json`](constraints.schema.json) 和 [`review.schema.json`](review.schema.json)。

## 1. 调用方提供工程上下文

可用 JSON 或等价结构化信息，但必须明确单位和来源：

| 信息 | 必需内容与缺失处理 |
|---|---|
| 快照 | board_id、board_revision、schematic_revision（不可变导出标识），原理图/PCB对应关系；正式约束包另有 constraints_revision |
| 电路 | 器件精确型号/版本、网表、拓扑、关键功能与数据手册。网络名只辅助识别 |
| 工艺 | **完整层叠**（从Top到Bottom的顺序、层类型、成品铜厚μm、介质厚度/材料/Dk/Df、阻焊、盲/埋/通孔能力）、每段走线的相邻参考层、制造下限及公差。只给“4层/6层”不能确认阻抗、回流或热判据 |
| 工作条件 | 连续/峰值/RMS电流及波形、供电、压降/温升预算、环境与散热。压降须记录测量起点/终点、是否含返回路径、静态/瞬态预算；材料电阻率须记录温度和出处。未知值用null，不能静默默认 |
| 时序 | 接口、速率与上升/下降时间、接收端预算。低时钟不等于慢边沿 |
| 几何 | 器件/焊盘/过孔坐标、走线与宽度、铜区与开槽、每层参考平面与跨域边界、连接器/天线/结构限制 |
| 约束 | 产品适用规范、器件/接口要求、已批准的设计规则、规则来源与优先级 |
| 能力 | 能否导出上述数据、设置规则、移动器件、重算铺铜、DRC、阻抗/场求解/热/EMC验证 |

默认目标是低风险、低速 MCU 简单板，例如单电源、普通两层或四层、LED/按键/UART/I2C/SPI/低速 ADC。正式约束包必须记录复杂度级别、判定理由和可追溯证据；高级/不支持级别只能给出待确认约束与人工审查项，不能把自动化结果标为完成。先建立本次电路适用的检查集，并把未纳入项和原因写入 `scope` 或随附审查说明。补齐信息期间可以完成不依赖未知参数的工作；不能对未知项给出确定线宽、安规距离或“通过”。复杂度分类的具体边界见 [`complexity-levels.md`](complexity-levels.md)。

## 2. 核心 skill 返回约束包

输入不足或尚无不可变原理图/PCB 快照时，先输出独立的 `analysis-draft.json` 或等价报告，标记 `package_status: draft`、`schematic_revision: null`、`board_revision: null`，列出 `missing_inputs`、带假设的 `candidate_constraints` 和 `conditional_calculations`。草案不交给 `audit`，不能生成已验证的数值。取得快照与必要条件后，才转换为下列正式约束包；不得用“unknown-revision”之类虚构版本绕过绑定。

`constraints.json` 必须包含（也可用 [`constraints.schema.json`](constraints.schema.json) 校验）：

```json
{
  "schema_version": 1,
  "board_revision": "immutable-export-id",
  "schematic_revision": "immutable-schematic-export-id",
  "constraints_revision": "immutable-constraints-package-id",
  "design_complexity": {
    "level": "beginner_simple",
    "rationale": "低速单电源 MCU，普通工艺；未发现需升级分级的功能",
    "evidence": [
      {"kind": "schematic", "id": "design-intent", "locator": "approved design-intent.json, nets and interfaces"},
      {"kind": "manufacturing_input", "id": "board-fab-capability", "locator": "approved stackup and capability record"}
    ]
  },
  "scope": "声明电路范围、纳入检查和排除内容；必须先由工程分析确定覆盖范围",
  "checks": [
    {
      "id": "unique-instance-id",
      "rule_id": "PWR-001",
      "target": "明确到网络、器件、引脚或几何区域",
      "acceptance_criterion": "带单位、假设和来源的具体判据；未知条件要显式标注",
      "method": "geometry / drc / calculation / simulation / measurement / engineering_review",
      "basis": [
        {
          "kind": "project_requirement",
          "id": "REQ-POWER-01",
          "locator": "工程要求文档的章节或不可变记录"
        }
      ]
    }
  ]
}
```

`schematic_revision` 必须对应已批准的原理图设计意图及其 EDA 网表；原理图变化后重新生成约束。`constraints_revision` 标识这份完整约束包，包内任一约束、复杂度或证据变化都必须产生新 revision。下游 EasyEDA 契约中的 `pcb_constraints_revision` 与本字段取同一值。`design_complexity.level` 使用 [`complexity-levels.md`](complexity-levels.md) 定义的枚举，`evidence` 至少给出一条设计输入、原理图、项目要求、来源或制造能力证据；理由和证据要解释为何适用当前自动化边界。Schema 检查字段形状，不认证 revision 或证据真实性。

`basis.kind` 为 `source` 时，`id` 对应 `references/sources/*.json`，`locator` 为确实读到的页/节，该来源的 `supports` 必须包含所用 `rule_id`。仅核验书目、只取得摘要或未核验资料不得作为已确认判据。新规则先完成研究登记，不能借用不相关的“已读”来源。`project_requirement` 用于确实存在的项目要求，不是绕开未读来源检查的标签。

每个 `checks` 条目都必须被审查。建议/待研究项放随附说明，不通过删除失败条目或把它降为建议来过审。需要数值约束时，调用方可在条目中附 `parameters`（显式单位）、严重级别、预计操作、依赖项和规则类别；本版 `audit` 不解释扩展字段或计算几何。

## 3. 执行方操作并回传结果

软件映射成功后，应回读设置值，再布线并导出当前几何和DRC。不能将“成功设置线宽”作为“全板线宽满足要求”的证据。铜区重算可能改变连通性或回流，需要重导出。

工程一旦改变就生成新 `board_revision`。约束可沿用其语义，但必须由审查方确认仍适用后绑定到新快照；旧测量/截图不能仅改写版本字段冒充新证据。

```json
{
  "schema_version": 1,
  "board_revision": "immutable-export-id",
  "checks": [
    {
      "id": "unique-instance-id",
      "status": "unknown",
      "rationale": "工具没有导出参考平面几何，无法检查返回路径",
      "evidence": []
    }
  ]
}
```

状态为 `pass | fail | unknown | not_applicable`。`pass` 与 `not_applicable` 必须有证据；不适用也要解释条件为什么不成立。证据项格式：

```json
{"artifact":"本地结果文件或受控数据链接","locator":"页/坐标/网络/记录号","board_revision":"immutable-export-id"}
```

审查者要实际读取证据；可以额外附文件SHA-256、测试方法、仪器条件、测量值、单位和误差。本版脚本只检查引用和版本，不打开这些文件、不验证它们是否真实，也不判断自然语言判据是否充分。

## 4. 证据闭环

```sh
python scripts/pcb_knowledge.py audit --constraints examples/constraints.json --review examples/review.incomplete.json
```

- 退出码 `0`：声明检查集的证据字段完整，输出 `evidence_complete_for_declared_checks`。
- 退出码 `1`：有fail、unknown或遗漏检查，需修改/补证据。
- 退出码 `2`：接口错误、重复ID、版本不匹配、无证据却声称通过或引用未读来源。

`audit` 会在证据检查前加载上述两个 Schema；格式错误会以退出码 `2` 返回，
而不是把格式错误的输入当成 `fail` 或 `unknown` 继续处理。Schema 允许调用方
扩展字段，但脚本只解释契约中定义的字段和证据引用。

`0` 不代表规则集没有遗漏、更不代表电气性能/EMC/安规通过。完整验证仍要靠EDA几何、工程审查、仿真和实际测量。

## 接入现有嘉立创或其他 skill 的调用点

在其“准备布线”步骤加入：读取本skill → 导出工程上下文 → 生成约束包 → 执行方回读规则并布线 → 导出证据 → 用本skill审查 → 修复后复查。若发现布局问题，回到布局步骤。这里给的是集成协议；仓库创建不会自动修改现有技能，也不声称已完成实际客户端接线。

## 原理图 → PCB → EasyEDA 的语义交接

原理图 skill 的 `design-intent.json` 是 PCB 分析的上游事实源。调用方应将它和当前 EDA 导出绑定到同一个不可变 `schematic_revision`，再生成 PCB context。至少保留下面的映射：

| 原理图设计意图 | PCB context | 用途 |
|---|---|---|
| `nets[].id` | `net_id` | 稳定标识物理网络，网络名变化不能丢失语义 |
| `nets[].role`、端点角色 | `electrical_role`、`pin_roles` | 区分电源、返回、模拟、数字、时钟等候选类别 |
| `interface_groups[].id` / `type` | `interface_group` | 将 SDA/SCL、TX/RX、SPI 等逻辑通道成组审查 |
| `pin_assignments[]` | `component_ref`、`pad`、`pin_role` | 把器件焊盘、复用功能和方向绑定到具体端点 |
| 串联电阻、保护器件、隔离器件 | `physical_segment_id`、`logical_path_id` | 允许一条逻辑接口包含多个物理网段 |
| `power_domains[]` | `power_domain`、`return_net_id` | 检查电源域、返回路径和跨域边界 |
| `evidence[]` | `source_refs` | 追溯精确芯片、封装、手册和设计约束 |

网络名（例如 `POWER`、`VCC`、`TX`、`SDA`）只能作为弱提示。PCB skill 必须综合原理图端点、器件资料、拓扑和用户确认，输出 `confirmed`、`inferred`、`ambiguous` 或 `unknown`；没有足够证据时不能仅按名称生成确定线宽、阻抗、温升或安全距离。

EasyEDA 执行 skill 接收经用户批准的设计意图和 PCB 约束，执行后回读实际文档。每次原理图修改都要生成新的 `schematic_revision`；每次 PCB 修改都要生成新的 `board_revision`。执行计划、回读结果、ERC/DRC 结果和约束审查必须引用对应版本，不能把 API 成功或 DRC 通过当作语义正确或生产合格。

最小调用顺序：

1. 原理图 skill 核对精确器件/封装，规划外设和电源/复位/时钟/调试，生成设计意图与待确认项。
2. 用户批准设计意图后，PCB skill 读取语义、层叠、制造和工作条件，判定复杂度并输出约束草案或正式约束包。
3. EasyEDA skill 只执行已批准的操作计划，回读工程、几何、铺铜连通性及 ERC/DRC。
4. PCB skill 用新的 `board_revision` 审查结果；任何未知项保留为 `unknown`，高风险复杂度回到人工审查。
