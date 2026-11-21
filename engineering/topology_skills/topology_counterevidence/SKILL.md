---
skill_id: topology_counterevidence
version: '1.0'
title: 计算反证驱动的拓扑与参数修订
owner: process_advisor
applies_to: failure
gates: [G1, G4]
tools: [validate_topology_graph, execute_topology]
checks: [failure_evidence, frozen_requirements, connected_graph, conserved_ports, native_execution]
hypothesis: 保持硬约束的拓扑或参数修订可通过重新计算恢复产品指标。
---
先读取原始失败记录。判断问题来自连接、输入、求解器或产品要求。
允许改变塔数量、连接、出口分配与范围内的参数。修订重新通过连接校验和实际计算。
复用严格匹配输入且证据未变的单元，依赖输入变化的单元重新计算。
