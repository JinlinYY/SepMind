---
skill_id: topology_construction
version: '1.0'
title: 从设计依据构建候选分离图
owner: process_advisor
applies_to: ideal
gates: [G0, G1, G4]
tools: [admit_topology_task, validate_topology_graph, execute_topology]
checks: [model_domain, frozen_requirements, connected_graph, conserved_ports, native_execution]
hypothesis: 合法单元端口可以构成满足原始产品要求的候选精馏流程。
---
从原料和产品要求构造图。记录塔数量、连接和数值设计假设的选择依据。
每股物流均有唯一去向，附加弃流进入全流程衡算。数值计算前检查组分顺序、
物性假设、连接和变量边界。实际物性与性能从计算工具取得。
