# Skills 蓝图 ID 流程

```mermaid
flowchart LR
  A["已有或手动创建 Skill"] --> B["Skills 能力库记录"]
  C["Skill Installations 导入"] --> D["校验 → 审批 → 安装"]
  D --> B
  B --> E["Skills 列表里的 Skill ID"]
  E --> F["链路节点 skill_id"]
  F --> G["校验并保存为草稿"]
  G -.-> H["T168 配置生效"]
  H -.-> I["T169 链路运行"]
```

- 链路使用 Skills 列表中的 **Skill ID**，不是 Skill Installations 的安装记录 ID。
- 当前需求分析 Skill ID：`707fa120-032b-40d7-86e5-2d37f7a2942b`。
- 导入流程完成安装后才关联/创建能力库 Skill；手动创建则保存后直接获得 Skill ID。
- 当前只校验并保存链路草稿；尚不能自动调用不同 Skill 或传递结果。导入的第三方代码也不会被执行。
