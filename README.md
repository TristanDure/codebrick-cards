# CodeBrick Cards

面向操作系统（OS）、计算机组成原理（CO）、计算机网络（CN）和数据结构（DS）的本地学习工作台。支持文章分片加载、章节检索、翻卡、自评、笔记、进度备份，以及来源追踪和独立评审工具。

**当前尚未通过全站 408 内容验收，批准卡数量为 0。** 请结合教材、官方大纲和真题核对答案；记忆自评、程序测试和来源覆盖率都不等于内容批准。

## 快速开始

需要 Python 3.12+，只依赖标准库；开发测试另需 Node.js 22+。公开仓库不带 CodeBrick 正文或本机数据。隔离演示会放到仓库之外，HTTP 服务只提供这个隔离目录：

```sh
git clone https://github.com/TristanDure/codebrick-cards.git
cd codebrick-cards
python scripts/build_public_demo.py --site ../codebrick-demo-site
cd ../codebrick-demo-site
python -m http.server 8765 --bind 127.0.0.1
```

打开 <http://127.0.0.1:8765/>。演示包含四科各一张自编机器候选卡，可测试检索、翻面、评分和本机进度导出；数据仅为界面/流程示例，不代表完整教材或审核通过的学习内容。候选仍显式标记待审，批准数为 0。需要在现有克隆生成本地工作台时，运行 `python scripts/prepare_workspace.py --demo`；此操作拒绝覆盖已有索引。用 `--sync` 可显式请求同步来源，访问前请核对网站条款和授权。

Windows 本地完整工作台可在准备后双击 `start-study.cmd`，或用 `start-study.ps1 -Check` 检查、`start-study.ps1 -Port 8765` 启动。该启动器服务整个本地项目目录，仅应在可信的个人环境使用；不要在含敏感本地文件的环境中运行，也不要转发/暴露监听端口。端口被占用时请换端口，不要关闭其他学习服务。

### 本机阶段性试用包

现有本机工作区已刷新为基于累计r75输入生成的r75试用快照：41 篇整包卡面全 PASS 的候选版本、960 张精编卡；仍是未批准试用内容，公开克隆不含这些第三方材料。打开工作台后选择“仅精编候选”，可避免混入尚未语义核验的机器候选；无精编的文章会显示空卡组，不表示该篇没有知识点。页面使用“未获内容批准”中性标签，不把AI卡面评审当正式批准；精确版本结论以本地哈希台账为准。目录保留348篇、4,441节和34,476来源单元用于查漏，不是全站内容已验收。旧快照已保留，348分片完整性校验通过；发布不写浏览器笔记或复习进度。后续评审结论不会自动改变固定r75精选包，试用快照编号与累计评审编号是两条独立版本链。

## 来源与授权

来源为 [CodeBrick](https://www.codebrick.tech/)，本项目与其无隶属关系。仓库未确认第三方内容的开放再分发许可，因此不包含正文、图片、既有候选包、评审档案或历史缓存。MIT 仅覆盖项目原创代码，不扩展到第三方内容。细节见 [第三方声明](THIRD_PARTY_NOTICES.md) 和 [数据边界](data/README.md)。

准备及重建命令：

```sh
python scripts/prepare_workspace.py --demo  # 四科原创演示；新克隆使用
python scripts/prepare_workspace.py --sync  # 显式联网同步四科来源并构建
python scripts/prepare_workspace.py          # 从本地完整缓存离线构建
python scripts/verify_study_workspace.py    # 分片路径与SHA完整性检查
python scripts/build_disposition_ledger.py --output-dir data/_reviews/mass-20261122/m2-accounting-next
python scripts/verify_disposition_ledger.py --ledger data/_reviews/mass-20261122/m2-accounting-next/ledger.json
```

同步耗时取决于来源与网络，失败会非零退出。缓存及生成分片存于本地 `data/` 和 `.cache/`，默认不纳入版本控制。来源更新或富内容提取缺失时，需要人工核对待查项。浏览器评分仅保存在当前浏览器的站点存储；换端口/设备前请通过界面备份。不要提交笔记、学习进度或备份。

## 开发与验收

```sh
python -m unittest discover -s tests -p "test_*.py"
node --test tests/test_workbench_progress.cjs
```

CI 在 Windows 和 Linux 跑离线测试。贡献规范见 [CONTRIBUTING.md](CONTRIBUTING.md)。工具可用不代表知识覆盖完整。截至本轮 r80 的本地台账记录：348 篇目录、94 篇有作者候选（171 个历史及当前候选版本，共 5,177 张卡面，含同篇旧版，不能视为去重知识量）；累计账选定的 46 篇候选版本有哈希绑定的逐卡 AI 评审（1,162 PASS、10 UNPROVEN、0 FAIL），另有 302 篇在批外。评审版本不等于最新作者版本，旧版结论不自动转移到修订版。这些数字是证据库存，不是文章通过率，更不是全站 408 覆盖率。所有本地正文、候选、评审与缓存均未获公开再分发授权，不随仓库发布；机器结构检查和 AI 评审均不等于人工批准。交付检查通过也不代表全站 408/真题能力通过，不应作为唯一备考材料。评审规则保留在 `data/reports/acceptance-rubric-408.md` 的本地工作区资料中；公开版本的评审原则在贡献指南中说明。

`build_disposition_ledger.py` 在新的本机忽略目录中生成逐文章、逐章节、逐来源单元及逐空提取项的哈希绑定处置快照；`verify_disposition_ledger.py` 可重核项目计数、输入哈希和逐项关系。该快照仅为机器证据分诊，不是人工批准，也不关闭尚未补证的知识内容。候选映射、结构校验、独立内容评审和人工源单元确认必须分别看待。详见[覆盖处置台账与验收边界](DISPOSITION_LEDGER.md)及[四科批次／年度考试证据验收](M3_M4_ACCEPTANCE.md)。代码许可：[MIT](LICENSE)。第三方声明：[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
