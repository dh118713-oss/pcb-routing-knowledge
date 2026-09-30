# 可运行的最小闭环

这个 walkthrough 使用仓库内的合成输入，演示一次从规则筛选到证据审查的
完整命令链。它不代表真实 PCB、EDA 几何、仿真、制板或测量结果；真实工程
必须替换为当前 BOM、网表、层叠、几何和不可变工程快照。

## 1. 筛选适用性候选

在仓库根目录运行：

```sh
python scripts/select_rules.py --profile examples/applicability/rf-2g4.json
```

这个 profile 明确声明了器件、封装、协议和频段。输出中的 `candidate` 只
表示目录条件匹配，仍需要读取对应来源并结合实际板级证据复核；它不是 RF
走线尺寸，也不是通过结论。

## 2. 审查约束与结果是否对应同一板版本

```sh
python scripts/pcb_knowledge.py audit \
  --constraints examples/constraints.json \
  --review examples/review.incomplete.json
```

这个命令预期退出码为 `1`，并返回 `needs_changes`，原因是：

- `vcc-width` 被合成观测判定为 `fail`；
- `return-path` 因没有参考平面几何而保持 `unknown`。

这里的 `synthetic-demo-r1` 是两份 JSON 共同绑定的板版本。把 review 文件
换成另一版本，即使文字结果相同，也应该被拒绝，避免旧证据被套到新板上。

## 3. 做一个有边界的压降计算

```sh
python scripts/pcb_knowledge.py dc-budget \
  --current-a 2 \
  --length-mm 100 \
  --copper-um 35 \
  --drop-mv 100 \
  --rho-ohm-m 1.724e-8 \
  --width-mm 1
```

输出是均匀矩形导体的直流压降下限。它不包含温升、过孔、焊盘、颈缩、回流
路径、瞬态、电磁场或制造公差，因此不能单独决定最终线宽。

## 4. 换成真实工程时必须补齐的内容

1. 用不可变的 `board_revision` 绑定原理图、网表、BOM、层叠和几何导出。
2. 把合成 `project_requirement` 换成真实项目要求或已核验来源。
3. 为每个 `pass` 或 `not_applicable` 提供可复查的 DRC、几何、仿真或测量证据。
4. 将工具无法导出的内容保留为 `unknown`，不要通过改写判据来取得 `pass`。
5. 设计审查完成后，仍按项目需要执行 EDA、SI/PI、热、EMC、安规、制板和
   实测验证。

这个 walkthrough 的价值是验证调用链和证据边界；它不会把合成示例包装成
真实板级成功案例。
