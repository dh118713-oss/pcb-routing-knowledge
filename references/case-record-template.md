# 板级经验记录

每个案例保存一个 Markdown 文件；包含私有工程或尚未授权的测量资料时放仓库忽略的 `private/`，不得自动公开。首次运行 skill 不会凭空产生“实操经验”。

```text
case_id:
origin: local_measurement | published_measurement | simulation | synthetic_example
title:
author_or_organization:
date:
source_url_or_project_revision:
permission_and_license:

板型/原理图版本/PCB版本:
器件型号及版本:
层叠/成品铜厚/板材/阻抗参数:
电压/电流/波形/开关频率/边沿:
环境温度/散热/负载/线缆/机壳:
仪器型号/探头/带宽/接地方法/校准状态:
原始测量或仿真数据位置:

原始问题与可复现步骤:
修改前布局/关键回路/测试结果:
修改内容（只改变哪些变量）:
修改后布局/测试结果:
是否有重复样本与误差范围:
可能的混杂因素:
能够支持的结论:
不能支持或尚未验证的结论:
关联来源与规则:
建议新增/修改规则及适用边界:
复核者及复核结果:
```

只有可对照的工程与测试证据才能升级成 `local_measurement`。厂商应用笔记中的波形属于 `published_measurement`；脚本生成的演示属于 `synthetic_example`。失败案例与不确定结论同样保留，不能只收集成功故事。
