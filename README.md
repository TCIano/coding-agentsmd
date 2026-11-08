# AI 项目维护文档系统

这里保存项目文档模板和框架说明。设计见 [docs/framework.md](docs/framework.md)，术语见 [CONTEXT.md](CONTEXT.md)。

## 模板在哪里

- `templates/project/`：新项目根目录和 `docs/` 的基础文件。
- `templates/documents/`：需求、缺陷、接口、设计决定、任务变更记录及两种快照的系统模板。
- 接入后的项目将这些文档模板保存到自己的 `docs/_templates/`，并在 `docs/system.yml` 记录版本。

## 初始化一个 Git 项目

在目标项目的根目录已使用 Git 的前提下，运行：

```sh
python3 scripts/init_project.py /path/to/project --name "项目名称"
```

脚本不会覆盖已有文件。它会创建基础文档、各类型的起始草稿和项目模板副本。起始草稿是待填写材料，不代表真实存在的需求、缺陷或设计决定。

## 生成快照草稿

在接入项目根目录已使用 Git 后运行：

```sh
# 工作接续快照，必须带任务号
python3 scripts/make_snapshot.py /path/to/project --kind work --task TASK-001

# 项目状态快照，任务号可省略
python3 scripts/make_snapshot.py /path/to/project --kind project
```

只填代码版本、分支、未提交改动、生成时间等机器知道的信息，进度、验证结论等保持「待填写」；生成的是草稿。文件已存在不覆盖；项目未初始化或不是 Git 根目录退出 2。

## 检查文档、任务或改动影响

在接入项目根目录已使用 Git 后运行：

```sh
# 检查全部正式文档
python3 scripts/check_task.py /path/to/project

# 只检查某个任务
python3 scripts/check_task.py /path/to/project TASK-001

# 看某次改动可能影响哪些文档
python3 scripts/check_task.py /path/to/project --changed-from HEAD
```

脚本只读。不带任务号时检查全部正式文档的必填字段、空串、文档状态、本地链接、重复 id、类型和 `document-map.yml`，并提示模板版本差异；带任务号时另查该任务的任务变更记录、文档影响判断、验证表和合并检查。影响判断和验证表按模板表头列名取列。给 `--changed-from <版本>` 时，按 `document-map.yml` 的 `path` 匹配改动文件，提示可能受影响的文档和未登记文件；提示不改变退出码。带任务号并给 `--changed-from` 时，还会核对「已更新」的文档或类型是否真的在改动里，没改就报错；ref 要选任务开始点。检查还会扫描敏感信息，报错和警告都打码；报「通过」只代表未发现已知格式的泄露。有错误时退出码为 1，环境或用法不满足时为 2。

## 汇总 CHANGELOG 候选

```sh
# 打到屏幕
python3 scripts/make_changelog.py /path/to/project

# 写到别的文件
python3 scripts/make_changelog.py /path/to/project --output /tmp/changelog-candidates.md
```

只收 `docs/tasks/` 下 `type: task-change`、且「合并检查」里已填合并负责人的记录；合并负责人空着或还是「待填写」的跳过。任务号已经在 `docs/CHANGELOG.md` 里出现的也跳过。候选给任务号、标题、链接、改动原文和验证原文，原文照抄，不改写。默认打到屏幕，`--output` 才写文件；文件已存在退出 1，指向 `docs/CHANGELOG.md` 会被拒绝并退出 2。跳过几条、为什么跳过也会打到屏幕。输出是候选清单，不是发布记录，发不发由人决定。

## 查看模板升级差异

```sh
python3 scripts/upgrade_templates.py /path/to/project [--check]
```

脚本只比较项目的 `docs/_templates/` 与系统模板并展示差异，不覆盖项目内容；`--check` 在有差异或缺失时退出码为 1。人工合并差异后，自行更新 `docs/system.yml` 的 `system_version`。

当前版本（0.8.1）提供模板、初始化、快照草稿、CHANGELOG 候选、任务检查和模板升级查看。0.8.1 修正 `document_status` 非法时的提示，指向工作接续快照的 `task_status`。
