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

现有本机工作区已刷新为依据累计r118精确哈希审计选定的固定试用快照：45篇整包卡面全PASS的候选版本、1,145张精编卡；r106—r108新增三篇因含UNPROVEN不纳入。仍是未批准试用内容，公开克隆不含这些第三方材料。工作台选择“仅精编候选”可避免混入尚未语义核验的机器候选；没有精编包不表示该篇没有知识点。目录保留348篇、4,441节和34,476来源单元用于查漏，不是全站已验收。348分片完整性核验通过，旧代际分片保留；发布不写浏览器笔记或复习进度。固定试用快照与滚动评审累计账是独立版本链，后续评审不会自动改变既有精选包。

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

CI 在 Windows 和 Linux 跑离线测试。贡献规范见 [CONTRIBUTING.md](CONTRIBUTING.md)。工具可用不代表知识覆盖完整。截至2026-11-24的本机阶段快照：四科目录共348篇、4,441节、34,476个来源单元。累计r122对64/348篇的精确候选版本有逐卡AI评审声明：1,896 PASS、153 UNPROVEN、2 FAIL，另284篇不在该累计批次中；这些是逐卡审查/来源映射判断，不是整篇通过、全站覆盖或人工批准。累计SHA、逐篇范围及缺口见[M3/M4证据日志](M3_M4_ACCEPTANCE.md)与本机忽略的详细报告。2027目标年度已依据教育部招生规定及高教社官方书目记录确认，但官方考纲正文未取得（要求数与映射覆盖保持null），官方一手历年真题证据为0，M4未通过。M4获取缺口交接单修订r2的17项AI独立复核为17 PASS，只说明交接记录内部核对通过；不表示已获得正文或官方真题。缓存、本地正文、候选和评审未获公开再分发授权，不进入公开仓库。

本机学习工作台当前有45篇整篇AI卡面全PASS的候选试用版（1,145张），只为可用性试学；含UNPROVEN/FAIL的文章不纳入精选试用。发布状态始终未获内容批准，不能作为唯一备考材料；用户切换“全部候选”仍可能查看未审机器卡。分片完整性检查不是内容验收。

`build_disposition_ledger.py` 在新的本机忽略目录中生成逐文章、逐章节、逐来源单元及逐空提取项的哈希绑定处置快照；`verify_disposition_ledger.py` 可重核项目计数、输入哈希和逐项关系。该快照仅为机器证据分诊，不是人工批准，也不关闭尚未补证的知识内容。候选映射、结构校验、独立内容评审和人工源单元确认必须分别看待。详见[覆盖处置台账与验收边界](DISPOSITION_LEDGER.md)及[四科批次／年度考试证据验收](M3_M4_ACCEPTANCE.md)。代码许可：[MIT](LICENSE)。第三方声明：[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
