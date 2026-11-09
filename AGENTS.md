# 本仓库协作规则

本仓库维护 AI 项目文档系统本身。修改模板前先读 [框架设计](docs/framework.md) 和 [术语表](CONTEXT.md)。

- `templates/project/` 是接入项目的基础文件原稿；`templates/documents/` 是各类文档的原稿。
- 模板字段发生变化时，同步更新框架设计中的字段说明，并检查初始化脚本生成的结构。
- 不要把示例占位内容写成已发生的需求、缺陷、验证或项目状态。
- 修改初始化脚本后，在临时 Git 项目中检查实际生成的文件；不要覆盖已有项目文件。
- 模板和检查规则共用 `VERSION` 中的版本号。需要改变既有项目的写法时，更新版本并说明迁移影响。
- 文档类型的唯一出处是 `scripts/doc_types.py`；新增或改类型要同步模板文件与 `docs/framework.md` 的类型表，`tests/test_contract.py` 会锁死三处对应关系。
- 改脚本或模板后跑 `python3 -m unittest discover -s tests`。

<!-- proma:memory:start -->
## 记忆维护

- **个人层（常驻）**：[user_profile.md](<~/.proma/memory/user_profile.md>)，跨项目共享，仅记录换个项目也成立的个人背景与稳定偏好。
- **项目护栏层（常驻）**：本文件（AGENTS.md，预算 ≤4000 非空白字符），仅保留不看就会在本项目犯错的子项目结构、常用命令与全局红线；具体模块细节、排障经过和某日状态快照一律下沉到项目 memory/。
- **专题手册层（按需）**：[MEMORY.md](<~/.proma/agent-workspaces/user-coding-agentsmd/memory/MEMORY.md>) 仅维护一行一条的场景路由索引（预算 ≤3500 字符，不写长篇结论摘要），详细主题按索引按需读取；过期或已合并的存量文件（含历史 project-preferences.md）通过可恢复归档移出有效入口。读取不等于核验，不编造用户事实。
<!-- proma:memory:end -->
