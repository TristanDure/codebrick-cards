# 四科内容批次与年度考纲／真题证据验收

## 不混合四种结论

1. 结构校验：候选与来源能否正确解析、映射。
2. 卡面独立评审：非作者逐张核对题面、答案、前提、反例与来源；FAIL 修复后绑定新哈希复审。
3. 全文覆盖：未用卡覆盖的单元、不制卡的合理处置、未读图示／互动和其他缺证另列；卡面 PASS 不等于文章 PASS。
4. 年度考试适用性：官方目标年度逐条要求、可复核原题与答案、独立求解和能力覆盖；旧版、目录及机构转载不能替代。

AI 评委须写 `kind=ai`、`independentOfAuthor=true`、`humanApproval=false`。这些是显式声明，不是身份认证；不得导入要求人类身份的来源审核字段。普通外链、参考书目不应无差别扩散为每卡错误，但承载实质题干、图示或争议依据的缺口必须定点保留。

## M3 批次输入与审计

本机批次清单使用 `codebrick-content-review-batch` v1，明确 `batchId`、`targetYear` 与 `entries`。每个 entry 固定候选文件路径、SHA-256，以及可选的独立评审路径与 SHA-256。未指定评审仍是 `UNREVIEWED`。

```sh
python scripts/audit_content_batch.py --batch data/_reviews/<batch>.json --output data/_reviews/<new-audit>.json
```

工具重新结构校验候选，核对评审绑定的来源缓存与候选；逐卡校验 ID 顺序、题答文本哈希、source unit IDs、四项检查（accuracy/atomicity/assumptions/sourceMapping）、具体独立理由与边界／反例。候选与缓存按解析后的规范路径去重，相同文章+候选字节不得作为不同版本重复计数；批处理前后重算缓存内容哈希并复核清单绑定，发现漂移即拒绝。缺一张卡、沿用旧哈希、声称人类批准或卡级结论与四维检查矛盾均不被接受。四维聚合遵循 FAIL 优先，其次 UNPROVEN，再次 PASS。缺口单元所在章节必须出现在缺口章节清单中，章节号按原缓存重解析核对。

独立评审使用 `codebrick-batch-card-review` v1。除上述逐卡项，还需 `missingCoverage`（单元 ID、章节范围、未证问题）、`fullArticleApproved=false` 和 `overall408Acceptance=false`。工具输出每批卡面结论、映射与未映射来源单元、不制卡处置统计，以及清单中所有批外文章。批外不代表未被任何历史批次审阅，只代表本批未覆盖。

每次修订新建候选／清单／评审，不覆盖 FAIL 历史。计数只表示哈希绑定的评审声明，不是自动语义认证；全科、全站验收需汇总非重叠有效范围并单独处理未覆盖项。

## M4 证据层级和缺口

目标年度以能核验的最新官方出版物／招生年度为依据，记录核验日期；未指定不猜未来年度。以下证据不能互换：

| 载体 | 能证明 | 不能证明 |
|---|---|---|
| 教育部招生管理规定 | 年度、统考科目、规定中的考试安排 | 408 详细逐条考点、每科分值或真题题干 |
| 官方出版社书目 | 题名、作者署名、ISBN、版本等 | 未展示的考纲正文、年度无变化 |
| 官方目录／封面图片 | 对应版本和目录实际列出的内容／页码 | 每一条官方要求或具体试题的全部内容 |
| 官方全文载体 | 该年度相应可读条款、题目、参考答案 | 卡片自动覆盖、答案已独立求解或必然有同样考频 |
| 机构转载／网站题库 | 其作者对题目的复现或分析 | 仅凭域名、题号或“真题”标签取得官方身份 |

```sh
python scripts/audit_exam_evidence.py --evidence data/exam/<annual-evidence>.json --output data/_reviews/<new-exam-audit>.json
```

本机 `codebrick-exam-evidence-chain` v1 为每个来源固定 URL、出版者、年份、证据等级、实际快照路径／SHA-256、能证与不能证的范围。官方要求需要目标年度、完整考纲载体、逐条定位和可在快照核对的原文；映射需要真实候选哈希及卡 ID。独立映射报告还必须绑定 `requirementSha256`：调用 `requirement_sha(requirement, source)`，对条目及来源完整对象按 `ensure_ascii=False, sort_keys=True, separators=(",", ":")` 的规范 JSON 字节取 SHA-256；同一条目 ID 的引文或来源变更后，旧报告不可复用。原卷和答案各有完整载体与定位，单独检查年份和来源等级。每题另须将年度、科目、题号、题型、完整题干（含全部选择项）及答案正文逐项绑定；题干与答案分别标同一题号、同年、同科，另由固定哈希的非作者证据配对评审通过。全文定位须逐字覆盖声明的完整题目/答案，不接受目录标题或单字符片段。该机器门槛仍不能判定真实官方身份或语义完整性。

未取得官方详细要求时，`officialRequirements=null`，条目数及覆盖率均为 null；不得用空数组计算“100%”。候选映射目标须通过与M3同源的文章/单位/正式卡结构校验，真实卡须含问答与来源映射；仅有任意schema和卡ID不能让年度链条记账齐备。参考主题树与旧年条目可暂作组织框架，但不可冒充目标年度要求。目录证明出版物收录真题，而没有题干／答案正文时，只记 `catalog-only`；不得伪造官方题目覆盖数。

`candidateMappingCoverage` 计候选映射声明，`officialMappingCoverage` 只计绑定有效的独立 AI 映射声明；二者均仅在完整清单被声明时计算，不是人工验收或语义认证。`targetAnnualEvidenceAccounted` 也只是声明清单的链条齐备，不证明清单确实穷尽官方考纲。

校验器只查本机一致性及声明的证据层级。SHA-256 不是数字签名，来源真实性、完整性与映射语义仍需独立复核；评审档案仍须检查非PASS卡对应源单元/章节以及候选open issues，不能用空缺口清单掩盖失败；本工具不授予 408 或人工批准。

## 数据与版本控制

官方／第三方原文、图片、试卷、私人评审和浏览器学习数据留在被忽略的本机目录。公开提交只包含工具、测试、原创演示和文档；不得强制加入来源快照。两个工具均拒绝覆盖既有输出，不修改正式卡、源台账或学习进度。


## 当前年度与分批推进方式

截至 2026-11-23，本项目采用 **2027 招生年度**作为未指定年份时的目标。本轮已重新核验的高教出版社书目为《2027年全国硕士研究生招生考试计算机学科专业基础考试大纲》，教育部教育考试院署名，ISBN 978-7-04-068451-3。已取得的教育部管理规定及研招网转载能支持年度/统考背景，不能替代详细考纲；本轮已取得出版社公开书目 DOM，页面显示“暂无简介”，样章入口声明“该书暂无样章”；详细正文仍未取得，不能宣称正文未发布。

- [教育部 2027 管理规定](http://www.moe.gov.cn/srcsite/A15/moe_778/s3261/202609/t20260923_1451734.html)
- [中国研招网转载](https://yz.chsi.com.cn/kyzx/jybzc/202609/20260924/2293971511.html)
- [2027 高教出版社书目入口](https://xuanshu.hep.com.cn/front/h5Mobile/bookDetails?bookId=6aa97a0be119ac9729dd09ea)（本轮已保存公开书目 DOM；不是详细考纲正文）
- [考试院 2022 版介绍页](https://yankao.neea.edu.cn/html1/report/21115/4961-1.htm)（只提供封面/版权/目录，不可当2027正文）

M3 每批选四科的实际候选，先冻结完整文件哈希，再由非作者逐卡审阅。返修创建新候选和新评审，旧失败记录保留。每批报告同时列出：候选数量、逐卡 PASS/FAIL/UNPROVEN/UNREVIEWED、每篇映射及缺口来源单元、源问题以及批外全部文章。不同版本同一篇不累加为不同已覆盖文章；旧卡 PASS 不自动继承到变更后的候选。先完成已有候选的独立卡面闭环，再补缺卡文章、富内容和全文覆盖证据。

M4 在合法获得目标年度官方正文后，逐科逐条提取带页码和逐字引用的要求，建立候选映射并独立复核；目录可用于安排获取任务，但不得扩写为官方条目。历年原卷与参考答案分别建立绑定和逐题定位，网站“真题”只做二手线索。题源核实、答案独立求解、能力覆盖分别验收，不因单题来源核实就宣布备考通过。

## 本轮验证快照（2026-11-23）

原创工具经非作者独立 AI 复审 r4，通过38项定向用例，并复演拒绝此前8种输入攻击与4种脚本漂移注入；结论限于已审工具及测试哈希，不是卡片或考试内容批准。全项目 Python 实跑362项（350通过、12跳过），Node 17项通过，348个分片完整性通过。

本机首批4篇修订候选共98卡，在固定哈希下获得逐卡独立AI PASS；全文缺口、空节和富内容未证项继续保留。第二批4篇与后续批次分别验收，不叠加同文章旧版本。2027官方逐条正文未取得，要求数和映射率仍为null，完整官方原题证据数仍为0。详细第三方来源、候选及评审快照仅在本机保留；这些数字是本次运行快照，后续以新批次审计为准。

## M3/M4 增量快照（2026-11-23，r17/r8）

本轮将累计清单提升至 `data/_reviews/mass-20261123/m3-four-subjects-cumulative-r17.json`，对应机器台账 `m3-four-subjects-cumulative-audit-r17.json`。机器重验显示 16/348 篇，卡面汇总347 PASS、10 FAIL，批外332篇；这不是语义认证。新增纳入的 CO「C语言类型转换」r2 为30 PASS/6 FAIL，CN「电子邮件」r4 为14 PASS/1 FAIL，DS「顺序表」旧候选为24 PASS/3 FAIL。三篇已有更新候选（CO r3、CN r6、DS r3）仍须针对完整新哈希逐卡独立复审，不得继承上述旧版本结论。OS「启动」旧报告未纳入累计通过数：模板理由重复且多卡仅绑定导语、在线图尚缺可靠审查绑定。CO「流水线冒险」schema修复v3曾出现卡号024理由与卡面主题错配，已要求独立评委新建报告复审；v3不视为该篇闭环。

目标年维持2027。`evidence-2027-r8.json` 及 `m4-evidence-audit-r15.json` 将零售目录所列2025/2026年度题目作为**二手获取线索**登记，同时保留高教社96页与零售页91页矛盾，不推定原因。当前官方详细考纲仍未取得，`officialRequirements=null`、映射率 null；已核官方完整原题及答案数为0，2025/2026目录线索不计官方题目。相关HTML快照仅在被忽略的本机 `.cache` 中，审计绑定其哈希但不提交原文。AI报告与机器校验都不是人工批准；本文件的增量记录也不代表四科或408整体通过。

### 增量更新：最新候选逐卡复审（2026-11-23）

CO「C语言类型转换」r3（36/36）、CN「电子邮件」r6（15/15）、DS「顺序表」r3（27/27）已分别由声明独立于作者的AI评委重审完整候选，并各自通过 `audit_content_batch.py` 哈希/结构审计。新的累计快照 `m3-four-subjects-cumulative-r18.json` 与 `m3-four-subjects-cumulative-audit-r18.json` 仍只合计16/348篇、357张卡面PASS、332篇批外。**不代表全文通过**：三篇各自分别有56、21、32个来源单元不在卡片映射内（含处置为重复/背景/未证或无卡映射的单元）；审查报告对整篇覆盖仍明确未批准，图示/教材/互动及章节缺口未因卡面PASS自动关闭。以上数量是来源映射账，不可直译为“遗漏考点数”。

CO「流水线冒险」r4全22卡独立报告经机器审计为18 PASS、4 UNPROVEN；这份报告已修复旧v3将024调度卡理由串成分支预测的错误，但本轮尚待另一独立评委对r4自身做质量复核。009正文线性计数器与022图示状态机分开建模；004还需核实其sourceNotes引用单元与`unitIds`的一致性。此篇不计入累计已验卡数。
## M3/M4 增量快照（2026-11-23，r19）

CO「流水线冒险」r4已由非作者评委完成逐卡理由质量复核：004因`sourceNotes`引用单元缺失于`unitIds`，UNPROVEN适当；009/022/023各自题面限定线性/图示模型，质量评委认为按指定模型即可求解，原r4把文章级源冲突下沉为卡级UNPROVEN不恰当；建议候选修订为卡级PASS，同时继续保留文章级`CO-SOURCE-CONFLICT`。024题卡为指令调度，r4理由目前围绕调度但带有可删除的“与分支预测无关”噪声。原候选未经改动，也未伪称质量评委另做了r5。r4独立报告暂按其原声明纳入r19台账；17篇/348篇、375 PASS、4 UNPROVEN、331篇批外。该数字仍是对评审声明的机器记账，三项分类修正未落到新哈希重评前不得称此篇完全闭环。报告及SHA细节见`m3-co-pipeline-hazards-r4-quality-review.json`；原r4逐卡结果见`m3-co-pipeline-hazards-r4.json`，机器绑定审计见相邻`*-validation-audit.json`。

下一步先复制候选新版本，补齐004来源映射并修正009/022/023卡级分类，保留源冲突全文问题；新版本交另一位评委全22卡重审。OS启动新候选还在修订队列，旧版图示卡未据导语认作有证。
### 增量更新：OS boot候选及后续队列状态（2026-11-23）

OS「操作系统引导」r2新候选 `data/curated/os-boot-r2.json` 已通过只读结构校验：SHA-256 `415508a1f6f8a6b9fcdee7b3687cb194a72613c09a844f2f6d8ddd9da19dcb5e`，31卡、97来源单元、11个开放问题。005改用缓存中已提取的传统引导交接表；缺图/缺可复核富内容依据的旧006/007已删除。结构校验不等于卡面评审，该版本尚未进入r19累计清单，等待非作者逐卡审核。DS「循环队列」候选31卡/91单元已进入独立评审队列；CN TCP拥塞控制75卡/110单元亦已派发独立评审，均未收到完整评审交付。CO pipeline依据r4质量复核提出的r2候选修订尚未落盘。当前有效累计仍以r19为准，不把候选存在或代理在途当作验收结果。
### 增量更新：M4 二手旧年度考纲线索（2026-11-23）

通过新建后台页面取得并保存新东方网《2026年计算机学科综合专业基础综合考试（408）大纲》转载 DOM：`.cache/evidence/m4-20261123/xdf-2026-syllabus-secondary-r1.html`，SHA-256 `44268d32989e047fa66ee4f38109c466829f0c297a1ddfbef1b7095eb2bcf648`。已登记到 `data/exam/evidence-2027-r9.json`，对应审计 `m4-evidence-audit-r16.json`。来源被明确标为 `authority=secondary`、`evidenceLevel=secondary-reference`、文档年度2026；只用于旧年度的组织框架和来源发现，不用于2027逐条requirements、映射率或官方真题计数。审计结果保持：2027 `officialRequirements=null`、官方完整题目证据数0、`full408Acceptance=false`。原始转载快照仍留在被忽略的本机 `.cache`，不提交公开仓库。
### 增量更新：M3 batch-006 冻结（2026-11-23）

已创建 `data/_reviews/mass-20261123/m3-batch-006-pending-r1.json`，冻结三个待审候选的当前SHA：OS boot r2 `415508a1…9dcb5e`（31卡）、DS circular queue `32ce6278…6dbc32`（31卡）、CN TCP congestion `9899cded…d865cb39`（75卡）。只读审计 `m3-batch-006-pending-audit-r1.json` 记录3篇、137张 `UNREVIEWED`；该结果明确不是内容通过，待非作者逐卡报告替换。候选文件未被修改。
### 增量更新：全站结构审计基线（2026-11-23）

重新运行本地全站工具：`audit_408_readiness.py` 报告 9,700 张卡、4,441/4,441 章节关联，结论仍为 `not_demonstrated` 且需要人工核验；`audit_coverage.py` 报告 348/348 篇、4,441/4,441 章节、34,476/34,476 来源单元已有机器映射，待人工核对 1,142、解析失败0。该“全映射”仅证明结构台账没有遗漏，不证明语义正确、全文覆盖或408适配，不能替代M3逐卡独立评审。
### 增量更新：M3 scope snapshot r20（2026-11-23）

新增 `data/_reviews/mass-20261123/m3-scope-snapshot-r20.json`，按四科重新汇总当前范围：CN 62篇/6,579单元，CO 72篇/7,051单元，DS 133篇/11,619单元，OS 81篇/9,227单元；r19哈希台账覆盖17篇，批外331篇。batch-006待审候选为CN TCP 75卡、DS循环队列31卡、OS boot r2 31卡，共137张UNREVIEWED。该快照仅为范围和台账统计，不等于文章或知识点语义通过。

### 增量更新：M3 DS 循环队列独立评审（2026-11-23）

新增非作者独立 AI 评审 `data/_reviews/mass-20261123/m3-ds-circular-queue-r1.json`，绑定候选 `data/curated/ds-circular-queue.json` SHA-256 `32ce62785df072bd59826b630a3a631e1572491c7243a87765f7b447b36dbc32`。31/31 卡的 accuracy、atomicity、assumptions、sourceMapping 均 PASS；FAIL=0、UNPROVEN=0。评审列出34个未映射来源单元（章节1,2,3,4,5,6,7,8,9,10,12），故 `fullArticleApproved=false`、`overall408Acceptance=false`，且 `kind=ai`、`independentOfAuthor=true`、`humanApproval=false`。validation batch 与 audit 已重跑，批次审计为1篇/31卡PASS。累计台账更新为 `m3-four-subjects-cumulative-r20.json` / `m3-four-subjects-cumulative-audit-r20.json`：18篇、406 PASS、4 UNPROVEN、330篇批外；这些是哈希绑定的机器记账，不是人工批准或408通过。

### 增量更新：CO pipeline r2/r5 重审与台账修正（2026-11-23）

`data/curated/co-pipeline-hazards-r2.json` 已由非作者评委重新逐卡复核，报告为 `m3-co-pipeline-hazards-r5.json`：22/22 PASS、0 UNPROVEN、0 FAIL；评委重新读取并绑定123个来源单元，将全部123个单元列入文章级未闭环范围（其中75个有卡映射、48个未映射），保留 `CO-SOURCE-CONFLICT`、互动、渲染、教材身份、考纲和链接真题等文章级缺口。该报告的四维卡级结论仍不等于全文或408批准。

初次生成的r21误把同一 `articleUrl` 的新CO版本追加，造成“版本数”而非“当前文章数”的累计视图；保留原文件并记录 `m3-bookkeeping-corrections-r2.json`，修正快照为 `m3-four-subjects-cumulative-r22.json` / `m3-four-subjects-cumulative-audit-r22.json`，按articleUrl替换旧版本后为18篇、410 PASS、330篇批外。后续累计更新必须替换同一文章版本，不能重复计数。


### 评审质量隔离与当前有效基线（2026-11-23）

OS boot r2报告出现重复通用理由和Markdown/JSON计数不一致，已要求另一轮全卡具体语义复审。包含该报告的r23快照仅是结构审计产物，隔离记录见 `m3-bookkeeping-corrections-r3.json`，不得计为通过。当前有效累计仍为 **r22：18篇、410张卡面AI PASS、330篇批外**。CO流水线的123个`missingCoverage`单元表示文章级未闭环范围，不是123个未映射单元；实际卡映射75、未映射48。

### 增量更新：CN TCP 拥塞控制独立评审（2026-11-23）

`data/curated/cn-tcp-congestion.json`（SHA-256 `9899cded2849bb6983b5370d88eda8d05cd4f83bfc4ceb6346a08659d865cb39`）已完成75卡非作者逐卡独立AI评审：75/75 PASS，0 UNPROVEN，0 FAIL；每卡含四维检查、具体理由、边界/反例和来源哈希。报告列出110个来源单元和章节4、7、16的抽取边界；图表/互动、站内真题官方身份、协议版本和2027官方大纲仍是文章级缺口，`fullArticleApproved=false`、`overall408Acceptance=false`、`humanApproval=false`。批次审计通过。使用 `merge_content_batches.py` 按articleUrl替换/加入当前候选后，最新有效累计快照为 `m3-four-subjects-cumulative-r24.json` / `m3-four-subjects-cumulative-audit-r24.json`：19篇、485张卡面AI PASS、329篇批外；OS boot仍因r3发现的2张sourceMapping UNPROVEN待修订，故未计入有效累计。范围快照更新为 `m3-scope-snapshot-r21.json`。

### 增量更新：M4 2027二手PDF线索（2026-11-23）

从公开第三方资料页取得并保存 14 页PDF快照 `hqwx-claimed-2027-syllabus-secondary-r1.pdf`（SHA-256 `dc9c3773a507c75a7a7347157ef120cbfc35e5646cdb9bdd451f913e829276e9`），并保存资料页公开DOM摘录。PDF正文包含四科考查目标、结构和章节条目，足以作为2027考纲线索和组织框架；但页面为第三方机构，PDF作者元数据为“Tsinghua”不能证明教育部/教育考试院/高教出版社官方发布，且未建立官方发布链。来源明确登记为 `authority=secondary`、`evidenceLevel=secondary-reference`，独立来源评审仍在进行。`m4-evidence-audit-r17.json`仍正确保持 `officialRequirements=null`、`officialQuestionEvidenceCount=0`、`full408Acceptance=false`，不把PDF当官方条目或真题证据。


### M3 current-version baseline（r25）

追加CN TCP评审时的累计快照短暂使用CO流水线历史r4；随后已按当前候选r2及独立评审r5替换为 `m3-four-subjects-cumulative-r25.json` / `m3-four-subjects-cumulative-audit-r25.json`，故该历史截点为19篇、485 PASS、329篇批外；此前快照留存，当前以r32为准。

### 增量更新：OS boot r4 独立复审未通过全卡门槛（2026-11-23）

r2→r3→r4 候选迭代后，Peirce 对 r4 的全31卡新评审报告 `m3-os-boot-r4.json`：29 PASS、2 UNPROVEN、0 FAIL。021的技术结论合理但绑定来源未充分支持UEFI接口定义及字段宽度推论；029补入U23后仍缺“C/D为操作系统卷访问名、非分区表字段”的直接绑定证据。两项均非事实FAIL，卡面未通过逐卡PASS门槛，已回作者再修。全篇还留51个未映射来源单元、70个未闭环/缺证单元、图表/空节/练习与官方大纲真题缺口。机器审计审查绑定成功，但不改变两张UNPROVEN。

为完整记录每次批次结论，r4进入累计快照 `m3-four-subjects-cumulative-r26.json` / `m3-four-subjects-cumulative-audit-r26.json`：20篇、514 PASS、2 UNPROVEN、328篇批外。它不是“全通过”台账；OS 文章仍处于待返修状态，不批准全文或408。

### 增量更新：M4 二手来源独立评审完成

Peirce对环球青藤2027 PDF二手来源完成独立来源核验，见 `m4-hqwx-2027-secondary-review-r1.json/.md`。PDF首页确有2027题名，14页中含1页宣传材料，正文可读，但未见官方编者、版权页、ISBN或可追溯官方发布链；“Tsinghua”PDF Author字段不是身份认证。评审记录8处错字/赘字风险，结论为 `SECONDARY_REFERENCE_ONLY`，允许作为四科非官方章节/关键词导航，禁止计官方考纲条目、官方真题/答案或正式分值时长证据。新evidence快照 `evidence-2027-r11.json` 绑定这份评审；重审 `m4-evidence-audit-r18.json` 仍显示官方requirements未知、官方完整题目证据0、408未通过。

### 批次合并器独立代码审查及测试缺口修复

`merge_content_batches.py` 与对应测试的独立AI代码审查记录 `m3-merge-tool-independent-review-r1.json/.md` 未发现可复现实现回归；审查指出缺少UNPROVEN决策经合并保真的直接回归用例。已新增该测试。针对性测试现为11项通过；全套执行373项，其中361项通过、12项跳过（0失败）；新增测试不构成对评审语义的批准。

### 增量更新：CO DMA独立评审（2026-11-23）

CO「DMA」13/13卡由非作者独立AI逐卡评审PASS，四维检查、具体推理和反例见 `m3-co-dma-r1.json/.md`；绑定候选SHA `0be3efe41f43aa083d442c63b67be9a25ed6e8bfd8f69fc4f8b57cf19e9a795d`。评审围绕DMA请求/完成中断区别、单总线仲裁和事务粒度、周期挪用/停止CPU访存、DMAC寄存器功能、传输次数与单位计算逐张核查。118个来源单元全部留在文章级未闭环列表（41个有卡映射、77个未映射），空节、SVG/交互未渲染、站内题目官方身份、教材/考纲范围仍开放；非全文/人工/408批准。validation audit记录13 PASS、0人类批准。

该时点有效累计r27为21篇、527 PASS、2 UNPROVEN、327篇批外；之后已经由r28至r32更新，最新以文末r32为准。


### M3/M4 持续验收增量（2026-11-23，r12）

**OS boot r5 评审质量与返修。**非原评委对 `os-boot-r5.json` 的11张UNPROVEN做了定点质量复核（`m3-os-boot-r5-review-quality-r1.json/.md`，绑定候选、r5报告/Markdown及source ledger哈希），不是第二次31卡完整验收。结论是有些四维被不当一律降级，且存在实质映射问题：003漏U16/U17，005被质量复核误报漏U17（后续主线程实核r5已存在该ID），016评审误称漏U29（候选实际已绑定U29）；020/023仅规范/架构普遍性仍缺证；028现实“通常出厂”需移除或一手来源；030“建立”需表达初始结构及延迟初始化边界。r5方法和Markdown将修订人误记为用户指定Hypatia；质量复核核对候选revision是 `Codex-main`，任务没有用户指定修订者。旧报告不修改、不继承其结论。

据此新建 `data/curated/os-boot-r6.json`，SHA-256 `75e810bf4b815e5c1e96a5758555ff68a75b1dc94fa409718acdb725e9e5ceca`。003补入U16/U17并双向同步unitDisposition；005原已有U17，仅补说明，收窄002/004/020/022/023/027/028/030适用范围，修正016证据说明。机器结构审计：97/97 source units dispositions、31卡，无结构错误；仍有11项open issues，`contentApproved=false`、`contentBlocked=true`。原作者说明曾错误归为Codex主线程；真实子代理归属更正记录于 `os-boot-r6-author-attribution-correction-r1.json/.md`，实际执行者为Zeno子代理（运行线程ID见更正记录），不覆盖原作者说明。r6尚未通过逐卡内容评审，独立重审进行中；不得计入M3当前累计。

**M4官方来源有限范围再核。**新增 `m4-official-acquisition-r12.json/.md`，明确记录读取考试院官方考纲目录三页、2022官方详情目录页，以及高教出版社2027与2023书目页面和抓取SHA；目录/书目页面只作catalog证据。出版社2027 DOM显示书名、教育部教育考试院署名、ISBN `978-7-04-068451-3`、2026年9月和96页，但目录暂无；未取得详细正文。考试院2022目录所列2020/2021试卷与答案附录本轮没有取得原文，官方完整题目证据仍为0。此为有限检索结果，不推断未发布、不可获取或不存在其他合法渠道。

据r12已取得的6份官方目录/书目快照和capture记录新增 `data/exam/evidence-2027-r12.json` 与 `m4-evidence-audit-r19.json`。audit绑定一致；仍是 `officialRequirementCount=null`、年度要求未完整、官方完整题目计数0、`full408Acceptance=false`、人工批准0。新增来源均`catalog-only`，未填充要求映射或试题。

**技术外证哈希审计器。**新增 `scripts/audit_card_technical_evidence.py`，专为候选metadata中的 `externalCardEvidence` 检查本地快照SHA、引文与位置、card ID关联以及可选评审绑定；不认证发布者真实性，不判断语义支持，也不授予全文/408/人工批准。17项针对性测试通过。对OS boot r5/r6三个Microsoft技术来源的本地绑定核验均成功（r6尚无评审报告，故只验证候选和源快照绑定）。工具独立代码评审待补。

本轮没有提交第三方正文或原卷、没有提交Git，也未更改历史累计r27。此前有效累计仍是21篇、527 PASS、2 UNPROVEN、327篇批外；r27含OS boot r4旧版本。新OS r6须待完整独立评审后用按articleUrl替换的合并器生成新累计快照。


### 本轮新增CO独立复核与外证绑定复查

- CO「主存与CPU之间的连接」候选 `co-memory-expansion.json`（SHA `ce39d4afc8b091022c5d573d1ba9e17676e5c14da099b23fe9fcf02c0b84872e`）已由非作者Zeno逐卡审查32/32，accuracy/atomicity/assumptions/sourceMapping均PASS；含容量/地址位数、位/字扩展接线、片选译码、地址映射与容量题复算。全文仍未批准：89源单元、53个列入缺口、9节、图像/表格/公式实际渲染未核；真题官方身份和2027映射也未闭环。报告/validation batch为 `m3-co-memory-expansion-r1.*`，机器重验输出另有audit-recheck。
- 新增 `scripts/audit_card_technical_evidence.py` 与17项测试，对登记的Microsoft技术旁证快照SHA、逐字引文、定位、cardIds和可选评审引用绑定做本机一致性校验。OS boot r5/r6各3项声明来源本地绑定一致；它不认证域名发布者、来源真实身份、语义支持或408通过。该工具尚未独立代码复审。
- 计数更正：修复前390项全套为377通过、12跳过、1项夹具ERROR（`browser.json` 尚在写入就被 `exists()` 检测触发读取，出现PermissionError）；修改mock marker原子发布后，最终390项执行、378通过、12跳过、0失败。


### OS boot r6 独立复审与当前累计 r28

Peirce（非作者）对`os-boot-r6.json`作全31卡新评审，重新读取文章97个来源单元及外部证据哈希；不继承r5卡面结论。逐卡结果30 PASS、1 UNPROVEN、0 FAIL；023因地址转换环境精确依赖仍缺目标架构/内核证据而保留UNPROVEN。评审者Peirce；报告沿用候选的错误修订作者标签Codex-main-thread，实际为Zeno子代理，归属更正见独立更正单。Peirce未参与修订。r6作者说明文件当前被修改为附加更正注记，但其候选SHA绑定的原修订事实文本应保持原样；归属更正仅以独立更正记录为准。JSON/Markdown中卡片与missingCoverage计数一致，四文件逐项validation audit通过。报告：`m3-os-boot-r6.json/.md`，候选SHA `75e810bf4b815e5c1e96a5758555ff68a75b1dc94fa409718acdb725e9e5ceca`。文章仍有97单元中的51未映射、67缺口单元/15节和9个未解决/冲突单元；11项文章issues、视觉/互动、考纲/真题缺口仍存在。全文、408和人工批准均为false。

使用`merge_content_batches.py`按URL替换r27中的OS boot旧版本，得到`m3-four-subjects-cumulative-r28.json`及audit-r28：仍21/348篇，当前卡面AI计数528 PASS、1 UNPROVEN、327篇批外。未将卡面PASS说成整篇或408通过。单篇CO memory expansion之后已按URL加入累计r29；避免同一文章多版本重复计数。


### 当前累计r29（r28之后加入CO存储器扩展）

按URL将独立评审的 `co-memory-expansion.json` 32卡加入r28，生成累计r29并运行多份audit/recheck；以`m3-four-subjects-cumulative-audit-r29-final.json`的22篇、560 PASS、1 UNPROVEN为准。现22/348篇、560卡面AI PASS、1 UNPROVEN、326篇批外。CO卡面PASS不等于来源图像/公式/表格渲染或全文通过；CO篇仍有53单元/9节缺口。其时M3下一候选进入CN CSMA/CA独立复审；现已由文末记录的r2复审完成。M4之后新增r14，结论以最新记录为准。



### CN CSMA/CA r1 独立复核与累计r30

Zeno非作者逐卡评审候选 `cn-csma-ca.json`（14卡、143来源单元、17章节索引），复算DCF退避冻结/恢复、DIFS/SIFS、窗口增长、重传与ACK时序。结果12 PASS、2 UNPROVEN、0 FAIL；两张UNPROVEN是新增的标准边界措辞缺本地直接映射（802.11帧确认例外、以太网全双工/传统共享半双工限制），不是物理机制判错；应收窄卡面或加绑定标准来源后新版本复审。全文未通过：143单元仍纳入缺口范围、17节/6条评审缺口说明（候选自身1个open issue），富内容、练习来源身份、教材及年度考纲未闭环。通过合并器按URL加入批次后，r30为23/348篇、572 PASS、3 UNPROVEN、325篇批外。M4 r13有限获取仍无官方完整原题及答案，计数保持0，报告不推断未发布或无法通过其他合法渠道取得。


### 测试夹具并发竞争修复

`test_start_study.py::test_browser_mock_runs_only_after_live_verified_http` 偶发在 `Path.exists()` 已观察到 browser.json 后立即读取，遇PowerShell `Set-Content` 尚未关闭的短暂文件锁。本测试是对 launcher mock marker 的测试夹具；已改用同目录 `.pending` 完整写入并关闭后原子移动，避免把部分发布当完成。13项 launcher 测试通过；全套390项重跑为378通过、12跳过、0失败。未修改 launcher 产品逻辑。


### CN CSMA/CA r2 修复与独立重验

基于r1的两项UNPROVEN，新候选 `cn-csma-ca-r2.json` SHA `463ec320b67359d23364a7929e8a2362949fd1ca8f19ab061baff7db2aa4eb25` 收窄两卡：MAC确认卡只讨论基本DCF单播DATA成功后SIFS/ACK及缺ACK不能确定碰撞；概念对照卡改为“本文课程对照”且不声称所有实现，双向来源映射同步。其作者修订说明尚未单独绑定。

Peirce作为非作者对r2全14卡重新读取143来源单元，不继承r1；14 PASS、0 UNPROVEN、0 FAIL。两张修订卡的accuracy/atomicity/assumptions/sourceMapping均单独PASS，纯离线来源映射支持限定后的教材概念主张，不代表标准/官方真题认证。评审：`m3-cn-csma-ca-r2-peirce.json/.md`；validation batch为 `m3-cn-csma-ca-r2-peirce-validation-batch.json`，主线程重新运行audit通过14 PASS，结果`m3-cn-csma-ca-r2-peirce-audit-r2.json`。文章级143单元/18节、6条评审缺口和来源练习/渲染/年度证据问题仍阻断全文与408批准。后续累计应以r2替换r1。注意 `m3-cn-csma-ca-r2-validation-batch.json` 是作者修订后、待审的批次，不包含reviewPath，不可拿来累计；可用的完成批次是Peirce写出的 `m3-cn-csma-ca-r2-peirce-validation-batch.json`，本线程重新审计后记录14 PASS。


### M3累计r31与四科范围快照r24

将CN CSMA/CA r2 Peirce已验收批次按URL替换r1后，r31为23篇当前版本、574 PASS、1 UNPROVEN、0 FAIL、325篇批外。r24范围快照由该audit及source ledger重新计算：OS 5/81篇（120卡，119P/1U）、CO 7/72篇（167卡全P）、CN 6/62篇（160卡，r1版本）、DS 5/133篇（128卡全P）；r32再以CN r2替换r1，因此当前CN为6/62篇、160卡全P。均为批次卡面AI记录；未评文章与同一篇未映射内容仍大量存在，不等于全站/408覆盖。


### r32纠正CN卡批次评审归属

主线程复核并要求Peirce确认r2独立报告，当前采用 `m3-cn-csma-ca-r2.json`（report SHA `1c6863ca6e5551112a287d9d80a456c987fb92c2dcb1c2aa399a90ac8aa13f07`）和 `m3-cn-csma-ca-r2-independent-validation-batch.json`；报告身份Peirce、全14 PASS。Zeno随后误将自己的独立任务线程用于生成同候选的另一份同名 `-peirce`报告，身份字段与实际执行线程混淆；该重复报告不计入有效累计且保留作审计历史。重新按URL合并Peirce确认的批次生成r32，统计与r31一致：23篇、574 PASS、1 UNPROVEN。无重复卡计数。


### M4官方来源边界 r14 与实现/身份纠正摘要

Peirce完成r14有限范围核查并保存 `m4-official-acquisition-r14.json/.md`。重核6份公开目录/书目HTML及HTTP记录哈希，并目视1张公开预览图片（其父书目对应2021旧版的试卷结构页，不是试题/答案，且不能外推2027）。NEEA/HEP目录确有2020/2021附录名称或书目信息，但正文未取得；本轮官方完整原题、答案、题证据依然均0，`officialRequirements=null`。有个带`failure`旧名的缓存最后HTTP为200、实际是2021书目，报告按实纠正旧capture对502的误述，未篡改历史。只完成既存公开页面核对；不声称搜索全网、不声称材料未发布。尚未在合法可读取官方正文中建立一条逐题原卷/答案链。r14没有给2027清单或提高官方计数。

**作者/评委归属更正。**r6 r1修订记录字段“Codex-main-thread”不实；实际执行子代理Zeno，父线程是主线程，但用户只授权最多2并发、没有点名修订者。此前更正r1/r2中的“用户指定Zeno”也不实；最新 `os-boot-r6-author-attribution-correction-r3.json` 明确更正：Zeno为实际子代理执行者，非用户点名，r6候选字节不变。原作者说明已按绑定SHA恢复字节不变，其中仍留旧错误；以纠正r3为准。修订基线细节也有误：U17在r5 card005中本已存在，r6只改变其sourceNotes；真正增补U16/U17的是card003。r5质量复核声称005漏U17；后续实核确认U17在r5原卡和双向处置中已存在，因此此项质量复核建议是误报。r6只改了005的sourceNotes；旧报告和修订过程档案均保留并显式更正，不能覆盖。

CN CSMA/CA：有效r2逐卡独立评审作者为Peirce的`m3-cn-csma-ca-r2.json`，不是Zeno另行产生的同名“Peirce”复核线程报告；后一份不纳入当前账。r32由Peirce报告路径的`m3-cn-csma-ca-r2-independent-validation-batch.json`合并并审计，结果仍23篇、574 PASS、1 UNPROVEN。重复报告留历史且不双计。

Launcher mock并发修复的独立评委Zeno给出PASS_WITH_LIMITS：仅`tests/test_start_study.py`夹具，生产launcher未改；PowerShell标记先写同目录pending并关闭，再File.Move原子发布；13个launcher测试PASS，限制为单写者，不覆盖广义并发/安全审计。主线程实际全套390项最终378通过、12跳过、0失败；独立报告路径`m3-launcher-fixture-independent-review-r1.json/.md`。

**M3阶段性现状以r32为准：**23/348篇、574张卡面AI PASS、1张UNPROVEN、325篇批外。四科当前批次：OS 5/81（119P/1U，r6文章仍未闭环）、CO 7/72（167P）、CN 6/62（160P；只含Peirce的CSMA/CA r2）、DS 5/133（128P）。未审文章、已审文章未映射知识单元、原文空节/富内容、交互和官方题证据仍未闭环。范围快照r24现有CO/CN/OS/DS逐科计数；整体人工批准为0，全文408接受为false。


### 历史档案绑定提示

`M3_M4_ACCEPTANCE.md` 中2026-11-23较早增量保留当时已知状态与后续纠正链接；若旧段落统计、候选版本或角色署名与后文冲突，按最后的 r32 / acquisition-r14 / attribution-correction-r3 勘误为准，不把历史快照当最新。所有“PASS”均指AI卡级结论，不含人工批准。


**r6评审归属补充：**Peirce的评审JSON与Markdown目前把候选reviser写为Codex-main-thread；这同样不实，运行线程归属以Zeno子代理correction-r3为准。修订归属错误不改变候选卡哈希，但已记录为报告元数据瑕疵，不能把评审身份声明当作密码学认证。

## M3/M4 验收增量（2026-11-23，r13 / M3 r33）

### M3 四篇独立评审已落盘，不通过项保留

批量绑定文件 `data/_reviews/mass-20261123/m3-mixed-four-r1-validation-batch.json`（SHA-256 `947963563983bec9514e9ffe5ccb277cfdcc8e47e512333a0a25868987fc480c`），审计文件 `m3-mixed-four-r1-validation-audit.json`。四篇都是全新逐卡非作者 AI 评审，均未声称人工批准或全文通过：

- OS「SPOOLing」`os-spooling-r2`：4 PASS、6 UNPROVEN、0 FAIL。报告 `m3-os-spooling-r2-independent-r1.json`。主要问题是多组件/步骤复合原子性，以及指针生命周期、锁/条件同步、现代实现前提缺少直接来源绑定。
- CO「CISC/RISC」`co-cisc-risc-r3`：10 PASS、2 UNPROVEN、1 FAIL。报告 `m3-co-cisc-risc-r3-independent-r1.json`。FAIL 卡把七项 RISC 特征集中一题；另有 CISC 动因/80-20 复合检索和 RISC-V 位字段缺少原始字段材料。
- CN「FTP/DHCP」`cn-ftp-dhcp`：3 PASS、9 UNPROVEN、0 FAIL。报告 `m3-cn-ftp-dhcp-independent-r1.json`。事实层面未发现错误，UNPROVEN 主要是 PASV/DHCP 分支、端口/交互细节未由绑定单元直接支持。
- DS「图判树」`ds-ext-graph-is-tree`：5 PASS、3 UNPROVEN、0 FAIL。报告 `m3-ds-ext-graph-is-tree-independent-r1.json`。主要问题是三角形反例、矩阵 BFS 复杂度纠正和路径压缩复杂度没有直接绑定来源。

Peirce 两份报告的 `reviewer.threadId` 最初误写为父线程；已由实际 Peirce 子代理生成不可覆盖的归属更正 `m3-cn-ftp-dhcp-and-ds-graph-tree-attribution-correction-r1.json`，原报告哈希与卡片结论保持不变。上述身份是显式声明，不是密码学认证。

合并后累计快照为 `m3-four-subjects-cumulative-r33.json` / `m3-four-subjects-cumulative-audit-r33.json`，范围快照为 `m3-scope-snapshot-r25.json`（SHA-256 `6239860d78116bb07bff796e6b143c0deb20a74bebc003808672ce2c752838ee`）：

- 27/348 篇已有当前候选的逐卡 AI 评审；321 篇仍在批外。
- 596 PASS、21 UNPROVEN、1 FAIL；这些数字只是当前台账，不是通过率。
- OS 6 篇：123 PASS、7 UNPROVEN；CO 8 篇：177 PASS、2 UNPROVEN、1 FAIL；CN 7 篇：163 PASS、9 UNPROVEN；DS 6 篇：133 PASS、3 UNPROVEN。
- 4,441 章节和 34,476 来源单元的全站处置台账不等于语义覆盖；每篇仍保留未映射来源、空节、富内容、题源和年度考纲缺口。

验收未通过后已启动定点返修：CO 拆卡、SPOOLing 收窄/补证、CN/DS 分支绑定与删改。修复后必须生成新候选哈希并由非作者从新字节重新评审，不能继承本轮 PASS。

### M4 官方书目/封面线索增量，详细考纲仍缺失

`m4-official-acquisition-r15.json/.md` 记录一次受限增量：重新打开高教社 2027 大纲书目页，确认署名、ISBN、出版时间、页数与“图书目录：暂无”；从官方书目页引用资源加载封面并目视核对 2027 年题名及“教育部教育考试院”署名。封面视口截图 SHA-256 为 `39e41be27f82d038fec87a9517cd4573582e9195cf4286d7223be6a25f5f2333`，只证明封面文字，不是原始图片字节或正文。

新证据快照 `data/exam/evidence-2027-r13.json`（SHA-256 `77e15108291219295167c11a3cd258760d713a4a542eb523fc8583d8ad33b491`）绑定该官方封面线索；`m4-evidence-audit-r20-final.json` 复核后仍为：

- `officialRequirementCount=null`、`mappedRequirementCount=null`、`officialMappingCoverage=null`。
- 官方完整题目证据 `0`，官方完整答案证据 `0`，`pastPaperInventoryComplete=false`。
- `full408Acceptance=false`、`humanApprovalsGenerated=0`。

本轮还明确记录：官方页面所列购买链接跳登录（未登录/未购买），Google Books API 返回 HTTP 429，百度结果仅用于发现二手线索且未进入官方证据。它不是穷尽检索；仍优先通过合法授权渠道取得 2027 详细正文及可复核历年原题/答案。

### M3/M4 验收增量（2026-11-23，r14 / M3 r34）

**OS 启动篇 r7 全31卡复评与返修。**Peirce 对 `os-boot-r7.json` 从新哈希全卡复核，31卡为29 PASS、2 UNPROVEN、0 FAIL；card023由r6/r7遗留的不确定转为PASS，明确按文章教学模型排序，不推广所有体系结构。card030 对“惰性初始化”和文件系统具体表结构泛化缺直接来源；card033 对文件更新/重分区/休眠恢复扩展缺来源。评委还发现 card023 sourceNotes 把U64误写U44，实际候选unitIds已绑定U64。报告 `m3-os-boot-r7-independent-r1.json` 绑定候选SHA `20ae8ab96e05370514c223c04efe299be0e44e0b9bae47bd3a105f78f620a2b5`；逐单元97/97正文哈希核验。随后主线程作者创建新候选 `os-boot-r8.json` SHA `ef8e4fc187080eb555dafba4ddb16254af3e2ac2b44226c8d69d93a94592871f`：收窄030/033到来源支持的教学模型，并纠正U64笔误。机器结构检查通过；新候选等待Peirce全31卡重新评审，r7任何PASS均不自动转移。

**累计快照按最新OS版本替换。**r34以URL替换r33中的OS启动篇r6评审绑定：累计仍27/348篇，321篇批外，595 PASS、22 UNPROVEN、1 FAIL。四科：OS 6篇、122 PASS/8 UNPROVEN；CO 8篇、177 PASS/2 UNPROVEN/1 FAIL；CN 7篇、163 PASS/9 UNPROVEN；DS 6篇、133 PASS/3 UNPROVEN。范围快照 `m3-scope-snapshot-r26.json` SHA-256 `9a0f84d794866b2ca8e3738af118e293917c5f8fd011c1e3f451589b585944a4`。这只是当前逐卡AI评审库存；未产生人工批准或全文/408通过。

**四篇候选作者返修完成，等待新哈希独立复审。**Zeno 在不覆盖旧版的情况下写入 `co-cisc-risc-r4.json`（18卡，SHA `519f7e44d12028743e28784f932fde344eaf6bdeda38205401afa63aea518732`）、`os-spooling-r3.json`（17卡，SHA `17ddf7ecac90682e78ba704f99a14ebad4331d0c98d3521c1cd61b79be74b1e2`）、`cn-ftp-dhcp-r2.json`（12卡，SHA `7fccdd2de1d7b5fd4d3742167f6d9de38e2375226e31588c184e7845c927c6da`）、`ds-ext-graph-is-tree-r2.json`（8卡，SHA `3cd4c34c0a06e4772195f41496135ff2af083cab19fe95b6050df582a26cfc8e`）。四篇结构/双向映射机器检查均通过，但所有卡都等待非作者独立评审；不得继承r1报告中的PASS。

**M4 acquisition 更新。**高教社2027封面和书目页只加强年度/署名/ISBN书目证据；`evidence-2027-r13.json` 的审计仍为官方详细条目数、映射数与覆盖率 `null`，官方完整题文0、官方答案0、历年真题库存不完整、`full408Acceptance=false`。官方原卷入口仍未解决；不以考试培训摘要、书目或CodeBrick自称真题替代。
