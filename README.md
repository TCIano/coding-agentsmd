# AI 项目维护文档系统

这里保存项目文档模板和框架说明。设计见 [docs/framework.md](docs/framework.md)，术语见 [CONTEXT.md](CONTEXT.md)。

## 模板在哪里

- `templates/project/`：新项目根目录和 `docs/` 的基础文件。
- `templates/documents/`：需求、缺陷、接口、设计决定、任务变更记录及两种快照的原始模板。
- 接入后的项目将这些文档模板保存到自己的 `docs/_templates/`，并在 `docs/system.yml` 记录版本。

## 初始化一个 Git 项目

在目标项目的根目录已使用 Git 的前提下，运行：

```sh
python3 scripts/init_project.py /path/to/project --name "项目名称"
```

脚本不会覆盖已有文件。它会创建基础文档、各类型的起始草稿和项目自己的模板副本。起始草稿是待填写材料，不代表真实存在的需求、缺陷或设计决定。

## 检查当前任务

在接入项目根目录已使用 Git 后运行：

```sh
python3 scripts/check_task.py /path/to/project TASK-001
```

脚本只读。它检查任务变更记录、任务相关文档的必填字段与文档状态、本地链接、文档影响判断和验证表，并提示模板版本差异。有错误时退出码为 1，环境或用法不满足时为 2。

## 查看模板升级差异

```sh
python3 scripts/upgrade_templates.py /path/to/project [--check]
```

脚本只比较项目的 `docs/_templates/` 与系统模板并展示差异，不覆盖项目内容；`--check` 在有差异或缺失时退出码为 1。人工合并差异后，自行更新 `docs/system.yml` 的 `system_version`。

当前版本（0.1.0）提供模板、初始化脚本、任务检查和模板升级查看。快照生成和现有文档检查仍按 [框架设计](docs/framework.md)逐步制作。
