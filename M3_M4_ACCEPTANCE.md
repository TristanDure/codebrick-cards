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

### 持续执行增量：2026-11-24（r37 / M4时间出处更正）

本轮使用项目当前锁定的目标年度 **2027招生年度**。该年度由已核验的高教出版社官方书目与封面元信息支持；详细官方大纲条文没有取得，因此`officialRequirements=null`、映射率`null`。审计仍计官方完整原题0、官方答案0；这不是对“未发布”的判断。2027是本项目目前可核验的最新官方年度，并非穷尽搜索保证。

**新增内容评审与范围账。** 在r36（29/348篇、652 PASS/28 UNPROVEN）上，本轮按URL以新哈希版本替换：OS「SPOOLing」r4（17 PASS/0U/0F）；CN「FTP/DHCP」r2（10 PASS/1U/1F）；DS「树与图」r2（7 PASS/1U/0F）。新候选均由非作者子代理完成逐卡AI评审，候选/评审字节绑定后再经机器audit；归属为评审记录声明，不是密码学身份认证或人工批准。r37为 **29/348篇评审候选版本、664 PASS、15 UNPROVEN、1 FAIL、319篇批外**。对应范围快照 `m3-scope-snapshot-r30.json`：OS 6/81（137P）、CO 9/72（197P/6U）、CN 7/62（170P/1U/1F）、DS 7/133（160P/8U）；活跃来源单元总计34,476。只列候选评审版本映射账，不代表最新作者版本必已评，也不代表全文覆盖；大量未映射/非卡处置单元、空节、练习与富内容仍有缺口。

CN FTP/DHCP r2的FAIL卡`curated-ccacdcac4a45c3cb`将FTP会话状态、传输模式和安全性揉成多目标；UNPROVEN卡`curated-af7af8f3f5ff45c7`把站内自称2026大纲目录归属写成未经官方正文证实的事实。DS图树r2另有1张sourceMapping UNPROVEN。已派原作者侧代理逐项修订；旧候选和失败报告保留，修订后必须由非作者针对全新哈希复评，之前PASS不继承。CO ALU r2（19卡）与DS C函数控制流r2（32卡）作者返修已落盘、结构检查通过，但尚未进入r37，因为尚无新独立复评；等待评委。CO CISC/RISC r5的独立复评进行中。

**评审工具与回归。** 新增只读`build_content_scope_snapshot.py`，从新鲜批次audit生成逐文章覆盖/批外范围，校验哈希漂移且拒绝覆盖；9项定向单测通过。全量Python测试实际运行399项（387通过、12跳过、0失败），Node 17/17通过，`git diff --check`通过。这些是工具测试，不是内容审批；该新增范围生成器仍未做独立代码评审。

**M4时间元数据更正。** 历史`evidence-2027-r13.json`与`m4-official-acquisition-r15.json`中的`verifiedAt/reviewedAt`和r15封面`captureAt`曾被写为估计时间；现有机器审计生成时间早于所写capture/review时间，故不应将这些时间当成capture telemetry。原始字节和旧审计均保留，新增`m4-timestamp-provenance-correction-r1.json`显式撤回三个精确时间、哈希绑定原文件，并生成`evidence-2027-r14.json`及`m4-evidence-audit-r21.json`。新manifest的`verifiedAt`仅指当前本地字节复核，不替代原始采集时间。该更正未增加官方条文或题证据，年度条款数仍null、官方题文/答案仍0，全文408仍未接受。


**r38：CISC/RISC r5复评已完成。** Peirce对18卡重新做四维独立AI复评，18 PASS/0U/0F；验证批次和来源哈希机器重核后按URL替换r4，得到`m3-four-subjects-cumulative-r38.json`及audit、`m3-scope-snapshot-r31.json`。累计 **29/348篇、667 PASS、12 UNPROVEN、1 FAIL、319篇批外**；四科OS 137P、CO 200P/3U、CN 170P/1U/1F、DS 160P/8U。CISC/RISC文章105来源单元中63个无卡映射，2个空节及富内容、官方考纲/真题证据仍未闭环；creatorAuthoredExercises仍不在正式卡片复评/可导入范围。r37的“r5进行中”由此新记录替代；旧记录不覆盖。ALU/C函数控制流已正式派给非作者评委重审，尚未计入r38。公开README的作者候选库存也重新实数：93篇、144历史/当前版本、4,443卡面（包含同篇旧版，不是去重知识量）。

**r40：持续验收更新。** Peirce对DS C函数控制流作者候选r2的32卡重审（26P/6U/0F），完整71来源单元/10节，20个未映射、40单元/9节列入review missing coverage；6张UNPROVEN均涉及本文未陈述的C语言规则，编译实验不能替代来源证据。ALU r2仍18P/1U/0F，完整复核140单元/15节，44个未映射、105单元/13节缺口；唯一UNPROVEN超出本文数据通路模型。作者已产出ALU r3并经结构检查，尚无新独立评审，故r40仍记r2。C函数r2已替换r1（r1 25P/7U→r2 26P/6U），绝不从PASS推广到全篇。r40仍29/348篇、671 PASS/9 UNPROVEN/1 FAIL、319篇批外；OS 137P、CO 203P/1U、CN 170P/1U/1F、DS 161P/7U。

Zeno按精确代码哈希独立审查scope快照生成器和9项定向测试，未发现可复现缺陷；明确多篇跨科端到端、并发和Windows特定边界仍未覆盖，不是人工审批。

**M4非官方题卷线索。** 厦门工学院备考栏目公开列有2009—2025题目及解析PDF。公开下载2009 PDF共7页，仅目视第1页标题/页脚和第6页45—47题/页脚；未完成整卷逐题核对，MarkItDown转换失败。因此r16只按`secondary`/`partial-text`入账，PDF SHA及目录DOM快照均绑定；高校托管不是命题机关身份，官方完整题文/答案计数仍0。`evidence-2027-r16.json`及`m4-evidence-audit-r23.json`结构审计通过；大纲正文未取得、条款映射null、库存不完整、full408Acceptance=false。中间r15因目录年份字段为null被审计拒绝，原件保留，r16加上“目录最新列示年份”的明确语义后通过；拒绝记录不是证据版本。
**r41—r42 增量。** CN FTP/DHCP r3 全14卡独立AI评审14P，按新SHA替换r2，r41=29/348篇、675P/8U/0F、319篇批外。此文章仍93来源单元全列入missing coverage、50单元未映射、4空节、9项练习入口未证。DS图树r3全8卡独立AI评审8P，替换r2后r42=29/348篇、676P/7U/0F、319篇批外。逐篇复评报告与validation audit均为哈希绑定机器核验；评委身份只是声明，非人工批准。图树r3仍有31来源单元中16个无卡映射、24 missing units/9节、6个open article issues；因此同样仅卡面通过。DS C函数r3（32卡）作者返修已完成，正在寻找非作者评委复审；CO ALU r3、图树/FTP之外的文章也继续排队。README数字同步为r42，当前候选库存93篇/148历史版本/4516卡（旧版重复计入）。

**r42后 M4状态不变：**2027仍为书目核验的目标年；官方详细条文及映射仍null，高校托管2009扫描仅secondary/partial，官方题文/答案计数0。不能据此宣称真题链或408通过。
**r43—r44扩展批次。** Peirce对ALU r3（19卡）全卡复评19 PASS；对DS C函数控制流r3（32卡）全卡复评32 PASS，均为新哈希逐卡独立AI判断且机器validation通过。此前ALU r2的UNPROVEN点和C函数r2的6项UNPROVEN经作者收窄后，本版未再留卡级UNPROVEN；这不消除作者说明中创作的待证扩展、原文空节/交互/官方题源缺口。r43 29/348篇，683 PASS、0U、0F、319批外；OS 137P、CO 204P、CN174P、DS168P。

随后扩展至两篇此前不在累计的现有作者候选：OS VFS（Zeno非作者评审）12卡=5P/6U/1F；CN WWW r2（Peirce）11卡=4P/7U/0F。逐篇完整读来源、单元哈希绑定；分别发现VFS错误/过宽的read路径复合卡及多项技术细节无直接来源，WWW存在内网部署、链接检查、大小写路由、HTTPS IP证书、URL/资源映射、缓存规则等无来源扩展。不得因技术听来合理就升级通过。r44扩大到31/348篇，累计 **692P/13U/1F**、317篇批外；OS 7篇142P/6U/1F，CN 8篇178P/7U，CO 9篇204P，DS 7篇168P。已在累计增加两篇评审版本，但没有“最新作者版本自动转移”规则。Zeno现负责两篇修订；待新哈希作者返修并由非作者复评。高质量评审揭出事实/证据缺陷，所以本轮并非总体验收通过。

M4有限范围独立AI复核已检查高校目录/2009 PDF登记中70个绑定、目录34链接和PDF元数据一致，维持secondary分类；没有检查2009卷其余五页或校对题文，不改变官方计数0与完整库存false。该报告不是官方身份认证或人工批准。

全量Python回归在此增量测试代码修改前实跑400项（388通过、12跳过、0失败）；新加的四科端到端scope测试定向运行10/10通过。Node工作台测试17/17通过。测试与AI评审都不等于人工批准。
**r44账后重新检查边界：** 最新累计只包含31个文章的绑定候选版本，其中新增的OS VFS和CN WWW评分出现1 FAIL、13 UNPROVEN，明确暴露返修需求；31/348并非全站审查。OS VFS的问题不能被五张PASS遮盖，返修/全卡复审应保留该FAIL直到新哈希通过。当前本地遗留的可用评审版本与当前作者版本有时不同，只有绑定清单可确定已审版本，绝不据文件日期推断“最新已审”。

### 2026-11-24 五并发试运行与保守累计 r45—r47

用户允许最多5并发后，使用五个互不重叠子任务执行独立内容复评、作者返修、代码复审及M4有限来源核对；无自审升级，也不以模型容量错误当完成。评审分歧保留而不挑选有利PASS：DS C函数r3的第二非作者意见为28P/4U，替代首评32P纳入r45，原报告字节保留，新增`m3-c-functions-r3-review-disagreement-r1.json`。4卡涉及最大值循环来源、条件运算符选中求值、BST边界和size_t替代代码缺证；作者r4已完成，待全卡新哈希复评。ALU r3的第二意见仍19P，独立复算仅支持绑定模型的卡面，不使全文覆盖通过；同篇只计一次。

r46新增CO I/O概述12卡=4P/7U/1F（全文57单元/10节，18单元未映射、全文missing覆盖57单元）；作者r2现已完成，不继承旧PASS，等待非作者复评。CN WWW r3经Newton全卡重审=10P/1U/0F，剩余`curated-www-load`在hosts/缓存/跨主机流程有无源扩写，作者继续r4。r47累计 **32/348篇候选版本、698 PASS、18 UNPROVEN、2 FAIL、316篇批外**。四科：OS 7/81（142P/6U/1F）、CO10/72（208P/7U/1F）、CN8/62（184P/1U）、DS7/133（164P/4U）。这比r44覆盖篇目增加，不是全站或最新版已审；未映射单元和文章级issues/官方证据依然开放。当前候选库存93篇、152个历史及当前版本、4582卡面，包含旧版重复，不是去重知识量。

**作者分工说明更正：** r44记录“Zeno现负责两篇修订”不准确，实际VFS r2由Peirce返修、WWW r3由Laplace线程作者返修，Zeno做VFS/I/O r1独立评审并作DS C函数修订；原记录保留以本增量更正为准。所有人工批准与整体408验收仍为false。

**范围工具测试返修闭环。** 独立代码评委r2要求补逐科decision断言（实测生产计数正确，但旧测试未捕获CO/CN被改PASS的内存故障）。主线程已修测试：逐科四种decision、卡数/篇数/已审数/活跃单元、articleScope决策/reviewPath全断言，并把只读检查改为完整路径集合和字节。独立r3复演故障注入成功捕获两处错误及额外文件创建，正常10/10通过；结论限该测试哈希。全量Python重跑400项（388通过/12跳过/0失败，33.448s），Node17/17；机器回归不是语义或人类批准。

**M4题42有限视觉线索。** 主线程新增目视2009高校托管PDF第4/5页，规范化转录第5页第42题到本机忽略目录，题号/15分及链表合同供独立校对；尚无独立题面校对、官方身份或答案证明。原MarkItDown wrapper失败；经审批调用已安装环境后退出0但输出0字节，明确没有取得可用Markdown。`evidence-2027-r17.json`/`m4-evidence-audit-r24.json`保存这条secondary-unverified线索而官方题文/答案仍0，2027条款和映射仍null。只有高校托管二手扫描与CodeBrick二手转述相互吻合不构成官方认证。
**r48—r49：修订后复评。** CO「I/O系统概述」r2由Zeno逐卡全审12P/0U/0F，替换r1的4P/7U/1F后累计r48=32/348篇、706P/11U/1F、316篇批外。该篇57单元中28个未映射、全57列入missings、10节含1空节、5项open issues、8条作者待证实现主张排除在卡片之外。因此只有新版卡面暂全过，不代表文章完整。DS「C函数控制流」r4全32卡独立复评29P/3U/0F，替换保守纳入r45/r47中的r3第二意见，r49=32/348篇、707P/10U/1F、316篇批外。r4改掉先前4项分歧中的多项，但Peirce再指出016空检查/BST性质、017自足完整函数仅绑定片段、029最佳值轨迹缺U26；作者r5返修进行中。全四科范围比卡面计数重要的限制持续：已评文章仍有来源未映射、正文缺口与富内容待核。

M4官方大纲需求仍null，官方原题证据0、答案证据0。2009题42仅有高校托管PDF的视觉转录，与CodeBrick转述在狭义题面语义上吻合；独立AI校对非来源认证、非答案/解法/评分校验。


## r50：万维网新版复评与题42代码运行补证

CN「万维网」r4由非作者Newton重新逐卡审11卡，11 PASS/0 UNPROVEN/0 FAIL；本轮没有沿用r3结论。合并清单 r50 仅按文章URL替换旧绑定，累计仍为32/348篇、708P/9U/1F，316篇批外。分科为OS7/81（142P/6U/1F）、CO10/72（216P）、CN8/62（185P）、DS7/133（165P/3U）。`m3-scope-snapshot-r43.json`重新检查34,476个活跃来源单元及各科范围。WWW的51单元/12节中仍有21个无卡映射，全51个单元列入全文缺口，5项open issues、6项source conflicts、8条作者待证主张、1个空节和5个练习仍未关闭；新版卡面全P不是整篇验收。

本地哈希绑定（文件不公开）：
- 累计清单 `m3-four-subjects-cumulative-r50.json`：`4ef899d09af1952bac7159aa04ad4fb23be286824f547d014bcafdd78133c370`。
- 累计fresh audit `m3-four-subjects-cumulative-audit-r50.json`：`8af35e92c4915c4fdb9ada2e9727b8eab09e2134d92ca059926655fbad6e96b1`。
- 逐科范围 `m3-scope-snapshot-r43.json`：`1f25b4030bd472c0e50093d6fdd5fe21d93d7e96c992c5cd371998190a78027c`。
- WWW r4评审 `m3-cn-www-r4-independent-r1.json`：`d0c9516da7f02f882545beeaac13849f79c06dcc10e639dad1f7df9adf4394a8`。

M4另外对已有DS「倒数第k个结点」候选的两块原样C11代码进行了本地MinGW GCC 8.1.0运行补证：`-std=c11 -Wall -Wextra -Werror -pedantic -O0`编译成功；两遍扫描、双指针各3,840例，共7,680例。用例包括空表、空指针、非正k、INT_MIN/INT_MAX、k越界，以及长度0至64、127、128、1024的有效有限无环链表，检查状态返回、恰当输出和结点字节未变。AI编写的具体值oracle与既有二手题面契约一致，但不是官方答案或独立求解；没有覆盖任意长度、无效内存、环或并发，也没有运行sanitizer或跨平台验证。报告 `m4-q42-candidate-code-execution-r1.json`（SHA-256 `e94b6646013d96d9dc4d564f61062bca428af428038af5b1e4e6849ee11c5ec5`）仅为待独立核查的运行证据，不改变M3卡面结论，不增加官方题/答案数量，不声称普遍正确性或复杂度证明。

并发上限按用户最新要求为5个代理；容量错误时降并发。当前独立评审、作者返修与主线程累计整合分开，作者不得自审、旧版P不自动继承。官方2027逐条大纲仍null，官方完整题和答案仍0；M3/M4目标尚未完成。


## r51—r52：OS链接复评与DS完全二叉树批次

OS「硬链接与软链接」r2由非作者Laplace审16卡，9P/6U/1F（`.cache`类本地全量来源审查边界见报告）。主要问题包括文件映射引用缺源、软链接路径重绑定未绑定路径解析单元、引用计数不能简单等同进程数、读取既有路径成本与创建目录项开销混在一卡，以及目录硬链接/软链接相关范围的源映射缺口。AI评委所称“逐卡”仅指当前16卡；93来源单元、11节仍有49单元未卡映射，整篇93单元全列缺口，1个空节、1项开放文章问题、3项评委开放发现，故不得称整篇审通过。累计r51新增该篇r2绑定：33/348篇，717P/15U/2F，315篇批外。

DS「完全二叉树判定」候选13卡由非作者Dalton独立逐卡评审全P。该篇27单元/9节仅14单元映射到卡，18个单元和全部9节列入缺口，另8个单元处置未决、6项文章问题保持开放；动态演示/外部练习等非静态内容不由文字卡PASS涵盖。因此仅为13张卡面全P。累计r52新增该文章，34/348篇、730P/15U/2F、314篇批外；34,476活跃单元的范围快照重建，未把该项局部结果外推到整科。

文件SHA-256（均为本地评审材料，不公开）：
- r52累计审计 `m3-four-subjects-cumulative-audit-r52.json`：`042ca5fdb9fe3644935b3bed1b8164bfc12ba4e7d48e79f554f395a5d0e63c48`。
- 范围快照 `m3-scope-snapshot-r45.json`：`c8fcc4d62e2cdbe162b914a01ce9317a0b2c2b23b4840393fa9109f3e0e492f7`。
- 完全二叉树独立报告 `m3-ds-ext-complete-tree-independent-r1.json`：`411eb3564ee3abae9d52c3fb79b8678f4c32b1ad464671ae0acb6d8b0c638aaf`。
- 硬/软链接r2独立报告 `m3-os-hard-soft-link-r2-independent-r1.json`：`4db91660a879515cd543aa2b2e2e2e3a7d27c56f76503a1ca1a84d5da7dfa94f`。

OS硬/软链接r3作者修复中；UNPROVEN/FAIL只在新候选哈希被非作者复评后才可替换r2结论。另有DS C函数r5返修待非作者复评，CO/CN新文章评审与2009题42候选代码执行独立复核在进行。当前未满足M3/M4目标。


## r53：CN CRC独立全卡评审

CN「CRC」由非作者评委Newton对47卡逐卡检查，39 PASS、7 UNPROVEN、1 FAIL；静态110来源单元/20节字段和哈希比对110/110，CRC算例另做有限复算。但交互可视化、外链可视化、两个动态练习均未审；8组原文正确性冲突仍open，5项候选问题、2个空节及广泛全文缺口均保留。FAIL为第16卡`curated-9b74ff1f28932669`：把FCS位宽/多项式与CRC实现参数完整性两个目标混合，后半无绑定来源；UNPROVEN另见第1/3/4/7/30/42/47卡，包括检错限制、计时、CRC判据、突发错误、具体CRC参数、条件概率及硬件时序扩写。数学数值复算和有限程序校验不能弥补来源不足。累计r53新增该文章，35/348篇、769P/22U/3F、313篇批外。按科：OS8/81（151P/12U/2F）、CO10/72（216P）、CN9/62（224P/7U/1F）、DS8/133（178P/3U）；再生成34,476活跃单元快照。

- r53 fresh audit `m3-four-subjects-cumulative-audit-r53.json`：`041b794fecc9682a728dc06e22b074cd289220483995bba76ddb00b7c5ac71a2`。
- 范围快照 `m3-scope-snapshot-r46.json`：`a28eea3b516f29fa483289e871bfa4faa022b5e3ec805e71ade61deda6937570`。
- CRC全卡独立报告 `m3-cn-crc-independent-r1.json`：`c71ddb093c659816c60d9bee8dfbd3e0aab9ff5a61e7d847fe2284d4661dbeec`。

该篇作者返修已分配给Zeno（在OS链接当前任务之后串行进行）；新版本必须非作者重评才可替换本次绑定。M4题42方面，Laplace独立复核本地候选代码执行结论为`PASS_WITH_LIMITATION_FINAL_STATE_ONLY`：核对原样代码并在独立目录重跑7,680例与oracle相符；`memcmp`只比较前后状态，不能排除中途改后恢复，静态本轮未见写操作也不是普遍证明。代码报告继续是二手题面条件下的局部运行证据，官方题/答案计数仍0。


新增待审作者候选：DS「用两个栈实现队列」12卡，37单元/8节，候选SHA-256 `d5b6160273395ef5c2fa9c132b7bbb4f5a7103f321b436edfa447ecfa45a908c`，全部单元有明确处置（15卡映射、3上下文、3导航、16未决），只通过结构检查，尚不计入累计已评数字。覆盖两栈分工、完整搬运、out非空搬运的反例、操作序列推演、双栈联合判空、单次最坏与序列摊还、原C空队下溢与第101次入队越界。未复制或认可原代码无检查的安全性，官方/未考断言、单栈不可能的全称断言、JS/OJ/图示和实际渲染仍未证。作者为主线程，已交给非作者Newton全卡评审；新稿结论待评，不自审批准。


## r54—r55：OS VFS复评与CO存储器概述新增独立批次

OS「虚拟文件系统」r2由非作者Dalton逐卡审11卡，10P/1U；60来源单元/11节中仅38单元映射、全60单元列为全文缺口、9单元处置未决、1空节、5篇文章问题和7项deferred topic仍开。`curated-vfs-performance`保留UNPROVEN：缓存命中可避免简化模型中的重复目录查找I/O，不等于真实工作负载总性能保证；文章自身说“VFS不加快”亦是未经量化的过强结论。累计r54替入r2后35/348篇、774P/17U/2F、313篇批外。

CO「存储器概述」`co-memory-overview.json`由非作者Peirce逐卡48卡审，32P/16U/0F。46个静态单元/11节仅34单元映射、46全列全文缺口、1空节、2项文章问题、16条评委发现；未证项包含访问时间/周期、DRAM性质、内存/外存等扩写和证据范围；卡面PASS不是整篇存储机制或年度验收。累计r55新增该文章后36/348篇、806P/33U/2F、312篇批外。DS与CN细分同r53：DS8篇178P/3U，CN9篇224P/7U/1F；OS含VFS为8/81篇156P/7U/1F；CO11/72篇248P/16U。已重新生成34,476活跃单元逐科快照。

- r55累计审计 `m3-four-subjects-cumulative-audit-r55.json`：`d17e9634d486ec08c4eeb998b83f598a743699c958ca55074eece0106d9d2e13`。
- 范围快照 `m3-scope-snapshot-r47.json`：`9bfe8556bbb14d92c9df864f463d49710589b5a2c5d53c1215c002859ca9b9e0`。
- VFS r2独立评审 `m3-os-vfs-r2-independent-r1.json`：`dace1a627d0843bbb6c8359faeb0577906cb2e8110669b08584e543b4ef12483`。
- CO存储器概述独立评审 `m3-co-memory-overview-independent-r1.json`：`74ba4c0ed8b07263e480144fbc5f7ac2f492cebc88185b13f910c78be12bdafc`。

修订队列：Zeno在OS硬/软链接r3之后修CN CRC r2；Dalton返修CO存储器概述r2；Peirce完成DS C函数r5评审后作者修OS VFS r3；Newton评DS双栈队列r1；Laplace评OS链接r3（并已完成本地C代码运行独立复核）。所有新候选只在非作者按新SHA评审后更新累计。


## r56—r57：DS局部错误复评闭环与双栈队列新篇

DS「C函数与控制流」r5由非作者Peirce重新全32卡审，32P/0U/0F，作者Zeno未自审，未继承旧r4的29P。32卡已缩窄到来源可支持的合同/语句/推演目标，原未证代码/语言规范/平台机制另列deferred，不能据删除扩写而称这些能力也通过。71来源单元/10节仍全部列入全文缺口、20个无卡映射、2项文章问题和1项评委发现；局部旧U仅在本次新卡哈希范围闭环。累计r56为36/348篇、809P/30U/2F。

DS「双栈实现队列」作者候选r1又经非作者Newton逐卡审12卡全P；37单元中15单元映射，22未卡映射，27单元/7节列全文缺口，4项候选问题和4项来源问题，12个练习入口仍未审。摊还证明与代码边界的静态推演获限定卡面P，并非原C安全实现或动态演示/OJ通过。累计r57为37/348篇、821P/30U/2F、311篇批外。四科范围为OS8/81（156P/7U/1F）、CO11/72（248P/16U）、CN9/62（224P/7U/1F）、DS9/133（193P/0U/0F）。全34,476活跃单元范围快照重建；局部四科数字不可当文章/全站/年度通过率。

- r57 fresh audit `m3-four-subjects-cumulative-audit-r57.json`：`c65686a0c5ea267c6a07bb625f809b69ecc6b58f890538f333a1a40da0dca7de`。
- 范围快照 `m3-scope-snapshot-r48.json`：`9a34d7a7f24dc9de06113b8534c30340c1cf072a06d0c389ade064695e19a937`。
- C函数r5独立报告 `m3-ds-c-functions-r5-independent-r1.json`：`c2086f2901e14240e4ddfdf0d6d7661fbf0627ff8fabef723553064aad7ee7de`。
- 双栈队列独立报告 `m3-ds-queue-stacks-independent-r1.json`：`c34b3361cfa799820f7c0b3aa237b68e464aa2f2eb0c41d5a2ba922f0c614bee`。

M4证据清单r19仅追加候选代码有限执行及独立复现指针（不是新增官方来源）；新增字段由主线程显式重新hash绑定，通用exam audit只核其既有schema识别字段，不验证新增指针的语义。`evidence-2027-r19.json` SHA `a6a10b5136eaaa69f7dab826af49415ba605bca273f1b7f6c0718c59028df313`；`m4-evidence-audit-r26.json`重审官方需求null、官方题/答案仍0、整体false。

本轮完整工具回归实测：Python 400项，388通过/12跳过/0失败（54.286s，`.cache/test-suite-20261124-r55.log`）；Node 17/17通过。负向测试日志中预期拒绝覆写等输出不是测试失败，以最终exit=0和unittest摘要为准。此后仅新增忽略目录候选/报告与公开原创摘要，无生产代码变化；`git diff --check`通过。


M4新增指针的本地独立核查报告 `m4-q42-code-execution-independent-r1.json` SHA `a290478d3bf6aa74852aa12657aaaae1b0f45645b425d6dbdee5380ada89fce0`；r26年度结构审计SHA `edda67c994991741ca24568e180245319893ce3e2791995f10e1203ae4bc3ebd`。指针的主线程哈希重核不等于schema自动语义审核或来源身份认证。


## r58—r59：OS硬/软链接及VFS局部修复复评

OS「硬/软链接」r3由Laplace按新SHA对17卡全量复评，17P/0U/0F，替r2的9P/6U/1F。原复合卡拆出读取成本与创建逻辑元数据变化；mmap、open-description/dup/fork/内核引用对象、stat/lstat计量和创建物理I/O四项能力仍deferred。93单元/11节均列入全文缺口，47单元无卡映射、1空节、2项文章open issue；近邻卡去重建议保留，不计新增能力。累计r58=37/348篇、829P/24U/1F。

OS「VFS」r3由非作者Newton重新审12卡，12P/0U/0F，替r2的10P/1U。有效命中复用机制、明示教学模型的6次/2次I/O计算、真实端到端总性能未证三者明确区分。60单元/11节，空节和deferred/源冲突仍开；真实速度方向/幅度并未因卡面通过而成立。累计r59=37/348篇、831P/23U/1F、311篇批外；四科为OS8/81（166P）、CO11/72（248P/16U）、CN9/62（224P/7U/1F）、DS9/133（193P）。非最新作者版政策仍明确：CRC r2与存储器概述r2仅作者修订待评，不继承旧P。

- r59累计审计SHA：`4288794d1a9f444152c030cce118a08d6550e4a2068aea19aa05bf1320a8413c`。
- r50范围快照SHA：`802b2e96e19ef6147ebb7f8066dc0fb6d6305aaa247e37bb8fa259d95cd5f4bd`。
- OS硬/软链接r3独立评审SHA：`601afac1b03975e8f560666d89a848d96eae201a100844fce960183e30d67d18`。
- VFS r3独立评审SHA：`1d280fa7df74b696cf3b1033a2e96a7f115285fcb81768cb02d63561a0eedffb`。

这些仍是AI卡面范围声明、不是文章/人工/408批准。M4详细官方大纲需求仍null、官方原题和答案证据仍0，不用二手题或代码运行替代。


## r60—r61：CRC返修通过、存储器概述仍一项未证；本地试用快照

CN CRC r2由非作者Newton全47卡复评47P/0U/0F，替r1的39P/7U/1F；FCS生成器拆分，欠缺的一般CRC实现参数、概率与纠错能力仍deferred，原文8组冲突和13项作者issue未关。110单元/20节，80单元映射、30未映射，35单元/17节列全文缺口、2空节与练习目标保持未证。累计r60=37篇、839P/16U/0F。

CO存储器概述r2由Peirce对40卡从零审39P/1U；原48卡中8张完整卡及5项部分能力deferred，不计覆盖。唯一`curated-co-memory-overview-035`的磁带顺序访问对照缺绑定直接来源；已交Dalton修r3，不因主体机械硬盘分类正确而抹去缺源。46来源单元/11节全部保留全文缺口，12单元未卡映射、1空节、5项文章问题、19项missing issues。累计r61=37/348篇、846P/1U/0F、311篇批外；批内无FAIL不等于全站或全能力通过，旧版未证/退役内容继续在历史和deferred中。

另外，学习工作台已从2026-11-22旧索引刷新为r59的保守试用精选：只把当时35个整包全卡P的候选版本（760张卡）导出，不对子集过滤或改写已审候选，旧F/U整篇候选不在精选包内。全站仍348篇/4,441节/34,476单元，18,901机器候选独立保留，故默认混合模式不是PASS-only。批准数仍0。旧索引有本地备份、348个旧分片全部字节哈希保持；新索引SHA `a28d67ded1b5924903398ec4af487877eb9c59b6a97607c1625f46bf34dd08db`，独立只读实现核查确认760卡及原候选文档/显示卡面绑定一致，核348分片通过。

独立实现核查另留两个LOW：一次性refresh脚本没有自己强制URL唯一（本次累计每URL一版且35个选择确为35篇，未触发），以及发布前旧index重检与最终replace并非跨发布者CAS。没有观察到竞争，旧代分片仍保留；后续刷新须加显式唯一性断言并维持单发布者。风险核查非语义评审，也不批准机器候选。

桌面DOM冒烟仅抽一个双栈队列文章（1552×719）：348目录、DS过滤133项、精编模式12卡、加载题答、翻面后答案可见、无文档横向溢出；没有写评分/笔记，关闭自建标签，未改用户既有标签。两次截图请求均CDP超时，未取得可用截图，不能说像素/移动/全部卡渲染通过。界面保守的“未通过或待审”总标签尚未按精确AI状态区分，当前需查本地独立台账，不当人工批准。

本地证据：
- r61累计审计：`fccf77f99f8a30eaef197c6841b4404ccf5376d33161503eeb4c4a4b2fc06370`。
- CRC r2全卡报告：`009f5ab73f5b4cebdf204bc1d7f97c4f479e653fade040d1d0d09ba737616a9e`。
- CO r2全卡报告：`1b7a79cf59c86df1b8954f23a3a6c4abc0815d846c31551671c561213483ff30`。
- 工作台刷新记录：`710d04854bee5db4263920ec2a46d88a8df482608709f24df2e176b0b12c5987`。
- 工作台独立实现核查：`129573eff1e7c8d611320ea9b8bfb0b0cef35a03ed26bdbef055eadd823e6c30`。
- 桌面单篇DOM记录：`3be3be1ca19842d493411de8081ad11b7021509ae81008659dc0e58d5baa9285`。

逐科快照 `m3-scope-snapshot-r51.json` SHA `356c66cde4b0a7577f6b92ab78377c183712484eb5f96e21530f7cea997dd4c8`，统计37个被选评审版本、34,476活跃单元。页面试用包仍固定r59，r61评审不会自动更新其760张精选卡。


## r62本地试用快照更新与候选状态文案

CRC r2全卡P纳入后，以r61累计审计为输入新建r62本地试用快照，36篇整包全卡P候选、807张精编卡。存储器概述r2唯一U仍整包排除，r3只作者修好还未进入本次快照；不拼裁已审候选子集。refresh脚本新增文章URL唯一硬断言（36选择=36 URL）并在build后重核全部审计inputs、候选导出哈希、旧索引未变，旧348快照分片保留并检查通过；单发布者运行，跨发布者CAS/锁仍未实现。新索引SHA `2ca56ef3c24145c991a16ce413c7b5056644c562eaf44d007de840a70fa5ff37`；`m3-trial-workspace-refresh-r62.json` SHA `091948250a318074d92b551d1ca65dc106fc31f3268adc3b384e8bc7431f57bb`。

页面原精编总标签“独立评审未通过或待审”无法准确表示有限AI卡面P与未正式批准的区别，现改中性的“精编候选 · 未获内容批准”；机器候选仍待语义核验，空池标“当前筛选无候选”不再误叫机器。标签只依存在性/卡池，不能据题答、文件名或未信任审批字段推测PASS/正式批准。新增5项离线回归，包括执行实际renderCard函数body的Node最小DOM用例（精编/机器、从二者转空池、伪造审批字段无效、翻面/前后导航禁用与过期答案清除）；主线程实跑5/5和Node进度17/17。未把最小DOM当桌面/移动浏览器像素验收；独立代码审仍在排队，不提前宣称通过。

当前公开仅原创代码/测试/摘要，本地第三方快照未推送。M3卡面计数仍以r61账本37篇846P/1U/0F为准，试用807卡不等于覆盖全37篇或全站。官方2027详细要求null、官方原题及答案仍0。

标签改动后全量回归实测：Python共405项，393通过、12跳过、0失败（46.390s，`.cache/test-suite-20261124-r62.log`，exit0）；Node进度17/17。全量程序回归仍不代替内容语义或浏览器像素验收。


## r62—r63：奈奎斯特香农首轮、CO存储器概述r3复评、标签代码审

CN奈奎斯特-香农r1由Newton对49卡独立全卡评审为36 PASS/13 UNPROVEN/0 FAIL，作为新文章纳入累计账后，r62为38/348篇、882P/14U/0F、310篇批外。原文94单元/16节仅65单元有卡映射；73单元/14节仍列全文缺口，含1空节、2空Mermaid图及练习入口。未证卡中的核心边界包括：净信息率/熵率定义、Nyquist脉冲性质与采样重建充分条件、渐近编码定理、幅度与功率平方关系、以及RTT/端到端时延扩写缺直接证据。Dalton正在依据r1结果制作r2；r2不继承r1任何卡面PASS，须待其精确SHA落盘后由Newton全卡重审。

CO存储器概述r3作者版本SHA `c16ea9b0f574eefc8f3bf398e55b9e9ce3367b1ba3758ffa2b2f8b41f2c7d48a`，由非作者Peirce从零全审40卡，40P/0U/0F，修复r2磁带访问分类缺直接来源问题。验证批次及结构/哈希审计保留在本地。该结论只覆盖卡面，不继承原r2的39P/1U；8整卡、5部分能力仍deferred且不计覆盖，全文46单元/11节仍有缺口、12单元未映射、1空节、5项文章问题及18项missing issues。合入r63后累计为 **38/348篇、883P/13U/0F、310篇批外**。

工作台标签代码变更由非作者Zeno独立审查，结论`PASS_WITH_TEST_BOUNDARY`：只覆盖绑定SHA的单行标签表达式及5项新增离线测试，不是人工批准或内容批准；真实浏览器、全页集成/可访问性未覆盖，未来新增pool类型需补显式分支测试。生产变更后全量离线测试实测405项、393通过、12跳过、0失败，Node进度测试17/17。

**r62和r66试用快照各自绑定不同的评审账本版本**：r62输入累计r61，36篇/807卡；当前工作台已更新为r66，fresh audit累计r65后只选37个不同URL的全卡P整包候选，共847卡。刷新保护了原348文章分片并验证新快照348篇；获批数仍0。r66输入r65，不能把它误称“评审累计r66”。独立只读核查仅针对r62，不为r66背书；后者仍有单发布者TOCTOU/CAS风险。公开仓库仅同步原创代码及摘要，不含第三方正文/候选/报告/缓存。M3未达全站闭环。M4 audit r26仍记录2027官方详细要求数、逐条映射率为null，官方完整题目证据0、`full408Acceptance=false`；目录/书目或二手扫描不能替代完整官方大纲与原题/权威答案。

本轮本地证据哈希（原始字节SHA-256）：
- r63累计审计：`1d76fde955c4cc7a72c8ca904e9ceaa6b0c2aa99b060990cea86ebacdf3b93f6`。
- r53逐科范围快照：`4b316a5d0c2fc1dde92240af2186d613a0b8452d3915c522d5cfa5306733aae3`。
- CO存储器概述r3独立全卡报告：`c95c800828927754f4f49d69d4e8fcf0b3a2314257b32ebe7730bfc68e8df3f2`。
- 标签独立代码审报告（包含实测运行环境）：`6ac1af466bdb6947cac4a01586c91151b113b10bc1167bb906aecb03891d6978`。


## r64—r65：DS链栈、OS同步概念独立复评

链栈作者版本全卡AI独立复评为19P/5U/0F（24卡），OS同步概念为31P/2U/0F（33卡）。r64以r63为基底纳链栈：39篇/348、902P/18U/0F、309篇批外；r65再纳OS同步概念：40篇/348、933P/20U/0F、308篇批外。均为仅候选卡面、非全文批准。链栈5项U集中在free(NULL)的C标准证据、结构体ABI/分配器前提、size_t/SIZE_MAX契约、栈ADT接口边界及动态顺序栈/扩容范围；OS同步概念2项U涉及吞吐改善前提和“必须共用同一把锁”的过强通则。两篇r2均已返修落盘，分别由r1评委转任修订作者；其r2不得自评，已换交另一位未参与修订的评委逐卡复审。后续必须以新SHA全卡复评，旧P不继承。

CO I/O概述r2复评当前仍12P；一次误派r3修订任务已撤销，因为未发现需要新版本的缺陷，不以无理由重写替代新文章评审。OS目录复评尚无落盘报告，不计r65。累计账仍有不同文章的全文缺口、deferred能力及批外文章，未达到M3全站闭环。

- r65累计审计SHA-256：`9cfb5ea8b3591dc41cbbd1235bd6f0b4266b2ed7b68ddadab0de968ccb749f9f`
- r54逐科范围快照SHA-256：`edf35a7a631d9af236010152c6e7204b689b169a5b455bf147537eec98e77483`


r62本地试用快照的非作者只读实现核查已完成（Newton）：按固定累计r61新鲜audit重算，确认36个不同URL、36整包807卡，逐字段/顺序对应原候选，当前348分片和备份引用的348旧分片校验通过。核查没有publish或浏览器操作；不证明内容语义、全部历史世代或跨发布者CAS。报告SHA-256 `7b100dec49fee2459403d5ddeeb811ed4926b2860928e1ed0cf141047e806372`。


## r66本地工作台试用刷新（输入累计r65）

新的r66刷新器在不覆盖旧r62 runner、报告或备份的情况下，以fresh累计算审r65为唯一内容输入，按article URL唯一性和整包P规则选出37/37篇、847张精编候选。机器候选仍在独立pool；内容/人工/408批准均false。发布后`verify_study_workspace.py`验证348片完整性通过，旧348片哈希均保留，旧索引备份位于`.cache/workspace-refresh-r66/previous-index.json`。刷新脚本还强制断言预期37篇/847卡、核输入SHA、导出候选SHA及旧index未变。该次单写入者成功不等于并发安全；builder仍无跨发布者CAS锁，备份仅代表发布前索引/分片。桌面r62独立核查未重用为r66结论，当前r66未作独立实现审或真实浏览器像素验收。

- r66 refresh报告SHA-256：`fae84ae307afe05597cad94b91dfb0de400852a589791765dd324f8f45750afa`。
- r66发布索引SHA-256：`a651addb3dcdc87b0346a7a79f31c4192a66d0918cc30d55f7c7289992c6187a`。
- runner：`.cache/refresh-workspace-r66.py`（忽略目录，不入公开仓库）。
- r65试用选择的基准评审账本SHA仍以r65审计记录为准；r65统计40篇/348、933P/20U/0F，超出试用选择的文章或任何U包均未塞入精编筛选。


## r66—r67：奈奎斯特—香农与链栈修订后全卡复审

CN奈奎斯特—香农r2（Dalton返修，49卡）由非作者Newton重新评审 **49P/0U/0F**，不继承r1的36P/13U；核心是将缺证的熵率、可达性、功率模型及RTT扩展收窄，并把13个关键教学目标明确列为deferred，不计覆盖。DS链栈r2（Zeno返修，24卡）由非作者Laplace重审 **24P/0U/0F**，不继承r1的19P/5U；free(NULL)、ABI/分配器、计数边界、ADT接口和动态数组扩容能力依然deferred。两份均是AI卡面语义声明，非人工批准、全文覆盖或官方408通过。

r66以r65为底纳CN奈奎斯特r2，结果40篇/348、946P/7U/0F；r67再替换DS链栈为r2，最终仍40篇/348、**951P/2U/0F**、308篇批外。r67剩余2U仍在OS同步概念r1（017吞吐结论前提、027共用同一把锁过强泛化）；OS同步r2作者返修后等待非作者全卡复审。OS目录和CO指令周期新文章评审未落盘，均不计入此账。候选库存现163版本/4,899卡面，包含同篇旧版本，不是去重知识量。

- r66累计审计SHA-256：`402516b3f40c699b8bdbf3654a94280d99dfba04520a680894fbfdfbe2bb2949`
- r67累计审计SHA-256：`78204d0fe1b956a63183c37a596cbbf0c629cb198cd66f77df840e700cfabb6c`
- r55逐科范围快照SHA-256：`a35a5976369bd5d3e5d0062adc6bf1e615aa44c97142734d846274f48e6e2119`
- CN奈奎斯特r2评审SHA-256：`aafbf81d018e45e6370c3c6828addc7475e7eb64c28f0d06f63613d06b5f17a7`
- DS链栈r2评审SHA-256：`33488ee5c523b5810732871dc509b349c74bffcbe8a2df5c36148ac6f563798d`

## M4代码执行附件审计r27

`audit_exam_evidence.py` 现在对可选`secondaryCandidateExecution`做严格字段、候选/报告/评委报告/runner、harness、stdout、题面转录及独立评审输入的本地字节SHA校验，并将绑定加入新audit的input set。它不运行代码、不验证oracle、不判断语义正确性、不认证评委身份或来源真伪；修订回归以合成fixture涵盖篡改、错误关联、路径逃逸、批准伪造、类型/计数错误和审计期间文件漂移。既有2027证据重审r27中该附件声明7,680个案例且字节绑定通过，但`executionRerun=false`、`semanticCorrectnessVerified=false`；官方详细要求和映射覆盖仍null，官方完整原题证据0，整体408 `false`。

- M4本地证据审计r27 SHA-256：`fa1e706f4ecd357973718d88a6f4948cc2047a4b8aa887961a387158aaa17bb0`。


## r68—r69：新文章评审与同步r2追加来源问题

CO指令周期全28卡由非作者Dalton独立首评，16P/12U/0F，新增进入r68后为41/348篇、967P/14U/0F、307篇批外。12U涉及超出绑定单元的实现/协议断言和缺直接表行映射；91单元/12节已静态核读，空Mermaid、教材原页/图8.5及21练习入口仍缺。作者r2已安排，不能继承本版16P。

OS同步概念r2的017/027已修复，但Zeno全33卡复评发现001/003/005/006/019/024/029来源映射不足，结果26P/7U/0F。按新精确SHA替换r1后r69为 **41/348篇、962P/19U/0F、307篇批外**。不是把原31P保留再只审2张；即便有新发现令P下降也如实入账。Laplace继续作者r3补正文已有直接单元/反向映射，纠正024对原文“满足有限等待”的过度归属，不靠删题刷P，完成后再由非作者全33卡验收。OS目录94卡仍待评审落盘，不能计入本轮。

r66试用快照的非作者只读实现核查已由Laplace完成：fresh audit累计r65，核37个唯一URL的847张整包候选，逐字段/顺序与原稿一致，当前348分片及备份引用的348旧分片完整。该核查没有publish、没有浏览器或语义验收；报告明确无CAS/跨进程锁、单发布者仅运行假设。固定r66包不自动纳入稍后的CN/DS r2及其他新增评审结果。

M4新增附件审计功能全量离线回归：418项、406通过、12跳过、0失败（48.992秒，`.cache/test-suite-20261124-r67.log`）；定向考试证据测试35/35、Node进度17/17通过。新增代码仍待非作者代码审结论，测试通过不替代评审。

- r69累计审计 SHA-256：`402959c5c7bfec87a1d1a2f414a87144c5c6e68f905f366a663453658dc3c54f`。
- r57逐科范围快照 SHA-256：`911bc080092daf23a67ba76d7b5fdf393d22c3c6e49b7201129f23c4ce0659cd`。
- CO指令周期首评 SHA-256：`a446811873409b515c65278f2eafd6d86b936a9d52d3db7247844a8d815c8d9c`。
- OS同步r2复评 SHA-256：`cd257a4b35adfa1eeeb8c41f8d797840ff3bcd596158d9b5e3a60f1cf012f213`。
- r66试用独立实现核查 SHA-256：`eae1e9fa82fcbc0548f55cf0c043fc5adc5e7b83c45835c96538642ffef8563e`。


## r70：OS目录94卡独立首评及M4代码审FAIL修复

Peirce对OS目录全94卡独立首评：84P/10U/0F，完整113单元/21节、83映射/30未映射、3空节，全文113单元/21节仍列未闭环。10U主要是打开文件引用保活、Unix对象身份键、缓冲回收/目录压缩实现规则，以及两个单元映射缺直接来源。纳入r70后累计为 **42/348篇、1,046P/29U/0F、306篇批外**。CO指令周期r2和OS同步r3虽已作者返修且结构通过，未获得新独立报告前不计通过。

M4附件审计首轮独立代码审为FAIL：跨报告显式目标字段未对齐、深JSON未结构化失败、矛盾的批准/官方计数声明未被拒。原报告和旧r27审计字节保留；此前418项回归不充当独立代码验收。作者修复为v2复核报告必须显式绑定candidate/execution、独立题面转录及review.inputs、严格顶层字段集合/递归已知边界字段检查、16MiB和64层限制及RecursionError失败转换。新增7组反例，定向42/42通过；最新全量425项、413通过/12跳过/0失败（48.858秒，`.cache/test-suite-20261124-r70.log`）。修复版等待同一非作者第二轮独立代码审，不提前宣称通过。

原证据r19使用version1复核，按新规应拒绝；不修改原r19或伪造原评委签署。另安排Peirce独立只读重核旧产物字节及显式目标关系，新增version2复核报告和后续新manifest；本次不重新运行代码，也不继承为新评委已重跑。官方题/答案计数和2027正文缺口不因工具修复增加或关闭。

- r70累计审计 SHA-256：`9ed9dffd8a467d38e34abba400523cce4ac365a3110db9e99df2411a5e0d6666`。
- r58逐科快照 SHA-256：`d2653f6ee514330c35ab6466deab938f9efd50e17f1b026ac0bbb390c4e6453b`。
- M4附件审计首轮代码审FAIL SHA-256：`6d6048283ab22c3b0c4afdf9fe3e6f828c16a5da21ebd6f224ec4278e5ca9b31`。


## r71—r73：三份独立报告入账及证据解析加固

按实际落盘并通过绑定审计的validation-batch顺序合入：CO指令周期r2（27P/1U）替换r1为r71，OS同步r3（32P/1U）替换r2为r72，新增DS数组左移首评（9P/3U）为r73。累计43/348篇、**1,072P/15U/0F、305篇批外**。分科OS10/81（282P/11U）、CO12/72（283P/1U）、CN10/62（281P）、DS11/133（226P/3U）。r59 scope重新核34,476个来源单元；94篇作者候选与43篇当前已独立评审版本是不同库存，不能把候选数量当验收数量。OS同步r4、CO指令周期r3、DS数组左移r2和OS目录r2仍须新哈希全卡复评，不继承旧P。

M4审计代码第二轮独立审仍为FAIL：JSON重复键可在相同原始字节中同时携带相反声明，默认last-wins会掩盖冲突。修复对四类JSON附件逐层拒绝重复键（含转义后同名键）、非标准NaN/Infinity及1e999等非有限浮点，保留16MiB/64层/编码异常失败边界。测试整理为显式原始字节反例并刷新父绑定，避免测试仅因stale而误通过；定向45/45通过。第三轮独立代码审以冻结源码/测试SHA重新运行45/45定向测试及130项探针，结论PASS，但范围仅限附件字节绑定与声明防歧义，不是候选算法或语义审批；旧两轮FAIL保留。

新v2执行复核r2仅核字节，未运行7680例；r20/r28当时绑定当前审计源。源代码再次修复后，r20被fresh audit拒绝为stale reviewInput:21。这是预期fail-closed，不允许原地替换SHA冒用旧复核。另行非作者复核将绑定不可覆盖工具快照；旧r19/r20和报告保留。官方详细大纲要求数/映射率仍null、官方完整题证据0、整体408验收false。

本次源文件冻结后的全量回归：Python428项，416通过/12跳过/0失败，52.043秒（`.cache/test-suite-20261124-r73.log`）；Node17/17通过。12项跳过涉及本机无符号链接权限等既有环境限制，不声称这些路径已在本机覆盖。工具回归不等于内容或官方能力验收。本地试用仍固定r66（输入累计r65）的37篇847卡，未自动加入后来评审。

- r73累计审计 SHA-256：`edd6297e4b904de6612cc935a9824cec9a0c01fd2b7ddbd397cd718060052063`。
- r59范围快照 SHA-256：`7e22ccd3058a89da02d48dbd56e2dd4a585c7c9da77bd3cf6802cebefabd5f87`。
- 待第三审源SHA：`295e275d205eda301ef983ac2e127cf9cdc0537cb15da2b462ff70eae1641fdc`。
- 待第三审测试SHA：`829ad5c688161c8d2c8816a3c7408e24cbb26ed5083365a7fef0c75492a4c14d`。


### M4附件审计代码第三轮独立验收结果

Newton对最终冻结的`audit_exam_evidence.py`与`test_exam_evidence.py` SHA作独立代码审：**PASS，仅限本地附件字节绑定/声明校验**。独立执行45项定向测试、130项攻击探针，复核原r1/r2缺陷并验证重复键（含转义后同名）、非标准与溢出浮点、大小/深度/编码边界；报告明确未运行候选/harness/compiler或联网，无算法语义、来源官方性、评委身份认证或人工批准效力。r1/r2 FAIL历史报告不覆盖。r20仍因其输入指向后续发生变化的工具源SHA而被拒绝；旧评审不能靠重写输入SHA恢复效力，后续需不可覆盖代码快照和新的独立报告后再建manifest。
- r3独立代码审报告SHA-256：`3be7055fac77756452cc7d0e4b56b36c0b4a26c0dbbaf1b2a96c05c65fb49d4f`。
- M4官方详细条款映射仍未知（null），已核验官方完整题目/答案证据增量0，整体408验收false。


## r74：DS数组左移r2全卡复审与M4执行附件新绑定

Peirce（非作者）对DS数组左移r2新12卡全量评审：**12P/0U/0F**，绑定52个原文来源单元、10节；signed任意p的负余数/溢出仍在deferred/全文待证范围，没有因正向右移左移收窄而宣称覆盖。合入后r74：43/348篇、**1,075P/12U/0F、305篇批外**。这是AI卡面复评，不是人工批准、完整文章或官方408验收。

Q42执行附件独立复核r3核30项哈希绑定，只通过不可变审计工具快照重跑只读绑定检查，未编译/运行候选/重新执行7680例或视觉查看。新manifest r21引用该报告和不可覆盖工具快照；fresh audit r29绑定通过，但官方详细考纲和映射仍null，官方完整题目/答案证据0，整体408 false。r20/r28历史审计仍保留且因live源码SHA漂移stale拒绝，不回写。
- r74累计审计SHA：`7ec242a711cfb60d7a31def97c06b5b71a33b71637eac96459fbe7cff7430be9`。
- r60范围快照对应r74输入，重新核34,476个来源单元；SHA：`d8e15a4c59c7a98909b066048c5fd1dc9b3fdba2aa46e214fdb302c46db0a79c`。
- r21 manifest SHA：`ef60c21bcbd1decde807fece91a643656254809e32f97f889ef2f818f6a57c99`；r29审计SHA：`9fc3e10fd05dc57cae940bde09d131e39cde8189c54a028030b69c108c5c214e`。
- Q42 r3报告SHA：`a1ea536fb7ee1eddec830ef41b62b45cafe85c366849f00216f8dbb934a481fd`。


## 本地精选试用快照 r75（输入累计 r75）

从**精确累计r75审核清单**构建并实际发布整包全卡PASS候选：41篇/960卡，按URL去重；只有41篇合格全P版本进入精选池，其余2篇有UNPROVEN卡的版本不发布，机器候选仍另池。此为未批准学习试用包，不代表408/人工/整篇通过。发布核348文章，旧348分片哈希全保留，旧索引另存`.cache/workspace-refresh-r75/previous-index.json`；学习进度/笔记不写入刷新器。固定旧r66及更早快照、报告、备份均未覆盖。builder仍无跨进程CAS，刷新以单写者运行为假设，不宣称并发安全。
- r75索引SHA：`d18087ead4bce40bb2a28febd01e09679711c7017839c002208d54e81e034695`
- r75刷新报告SHA：`2c888b88d7f75cb68a7196f05c16e23a192c6b38c6db458e9e50df864148c60b`
- 选择源为r75累计审计SHA：`ae0e944af2e2955b0dd477ad3c05d9fb3fa4a4349a41643124e07503c53f9d60`
- 已通过fresh `verify_study_workspace.py` 的348片完整性核验；像素/桌面真实浏览器验收仍未完成。


## r76：OS目录r2修订版全卡复评

Newton对Peirce修订的OS目录r2候选94卡独立重审，不继承r1的84P/10U：**94P/0U/0F**。候选SHA `5817ea04445f5b4c167e45a3491516544558c8e75f1b8545af8df3a6e60fbcc2`；核主文113单元/21节及指定的12条补充引文，双向映射10个唯一外引unit。r76合入后43/348篇、**1,086P/1U/0F**、305篇批外。唯一U为OS同步概念r3，不能因其他文章全P而误报批次全P。OS目录本身依旧不是全文通过：30个主文unit无卡、3空节、7练习正文/答案、外部引文文章全文、官方题源/官方2027考纲与UI视觉范围均未闭环。
- 报告SHA：`3ff5badd9ff9ec07ea332cf51e3cb94debcc1dc9f96dbf21013ec3c32f3a6629`；r76累计审计SHA：`c6f00411f706e49342a4d09f32ee0befc213527e16d7d2a5828114467eb3031c`；r61 scope SHA：`60881bb5bed2ba6157fda12e0a1bb41d50e6716680be246b753eff69f08ef4cf`。


## r77：OS同步概念r4复审，当前43篇已审候选全卡P

Dalton（非作者）对OS同步r4全33卡重审，**33P/0U/0F**，不继承r3结论；card018限定一般层次比较、只用U30/U31支持，没有过度添加逐项后果。合入后43/348篇均为当前绑定版本，**1,087P/0U/0F**、305篇批外。r62 scope重新审计34,476个活跃来源单元。

此“43篇全P”只描述批内卡面AI评审，不代表全文通过；精编候选库存94篇/169版本是作者候选库存，未审版本不能计入；全站348篇中305篇仍批外。r75可用试用包的41篇/960张整包卡已构建并完成348分片核验，另两篇虽现已全P但未进入冻结快照。OS目录94卡补丁评审在此累计全P边界中仅表示94卡卡面决策，不抵消30个未映射单元、空节/练习/富内容缺口。官方详细考纲逐条要求数与映射仍null，官方完整真题/答案证据0，408整体false。
- r77累计审计SHA：`e88592a911906690860bcbc9a95b0795e5f5678e24d63c0aa077849dcc59ff42`；r62 scope SHA：`0353e69de772526e9cc3a89e0149e632103b1079b1fc7934d8aa082bf2b6e0e7`。
- OS同步r4报告SHA：`3ac13f9ccaaa43cabc26edde274967a49faf53ad93810598ff4bd3542d70ad27`。
- 最新本地试用仍是r75，不自动吸收r76/r77的OS目录/OS同步新卡；不得把r77称“试用包已包含全部43篇”。


## r78—r80：CN HTTP独立复评与CO/DS首评推进

CN HTTP r3经Peirce全17卡独立复评为16P/1U，发现POST/GET暴露面与HTTPS传输保护被并成一题，U13及已有安全补充未支持GET日志泛化、TLS安全属性和配置前提。作者已产出18卡HTTP r4，须另一评委全18卡复审后才可替换入账。CO bus standard首评：25P/7U，主要是把PIPE补充外推为建立/保持/抖动、8b/10b受限游程、反射机制及端到端交换瓶颈等证据不足；DS linked queue首评34P/2U，缓存机制解释和只给题目链接的环形队列初始状态均未证明。按实际validation batch，CN HTTP r3→r78、CO bus standard→r79、DS linked queue→r80；最终46/348篇、**1,162P/10U/0F**、302篇批外，scope r63重核34,476单元。卡面有UNPROVEN的版本不进入精选整包包。

试用r75独立只读核查通过所声明41篇/960卡的字节与选包边界，检查499项；AI核查不等于语义/全文通过，且builder无CAS。另作新localhost源的工作台桌面DOM冒烟：348/348目录加载、精选池切换、翻答案显示、标签“精编候选·未获内容批准”、answer/source DOM有内容、页面无水平溢出；未写笔记/评分/重置/导入，也未读私人学习状态。旧`127.0.0.1`标签命中陈旧JS标签，而新origin读到当前中性标签；五项前端标签回归全通过。CDP截图超时，故无像素/视觉通过；只覆盖一文章/桌面，非全站UI验收。
- r80累计审计SHA：`45ab48a6b32d3317d208d84c261a3a27051ff2fb9defd81238b6b03dbd3935c3`；r63 scope SHA：`84aa9d9330dde759e06c5b1f14a1af2d0a470d627b86443356d20636ee84dc3d`。
- DS链队来源卡评审报告SHA：`9cf12278539450275d75e99a6a56cd3c44be7a6cdbc614787690e9734bba2c1e`；OS目录r2报告SHA：保留于前节。
- HTTP/CO/DS三篇未因旧版结果而宣告作者新版通过；变更后必须重新全卡核对候选哈希。


## r81：HTTP r4跨评委复审新增4项待证，统计如实回退

HTTP r4将原安全复合题拆为18卡后，由Newton全量重新独评为**14P/4U/0F**，不是沿用r3的16P。安全拆分的015/016均P，但复审新发现005定界主张缺U29/U32直映且Host为额外目标、008的流水线3 RTT缺N≥1条件（N=0反例）、009题面未给并行M=5而681ms不唯一、018仅可靠流的U74未证加密传输。因此r81真实替换r3：46/348篇、**1,160P/13U/0F**，302篇批外；r64 scope重新核34,476单元。保留r3/r4各自旧结论，不通过只审原U或选择较高P旧版来隐去新问题，HTTP整包仍不纳入冻结精选包。返修r5后须全新哈希全卡复评。
- r81累计审计SHA：`d8f9c7ee5676838c892f0326d6da5013173456c782949eeb09ae3dec9dcf36e7`；r64 scope SHA：`0b75af45169f63ecdeb6141cf473843f275269b50f49008f50c5e0a5169dee1f`。
- HTTP r4报告SHA：`1f773a8be0470c14addc21e04aa2233659130f514819f456e743cf55485c9f4f`。


## r82：CN传输媒体首评发现13项FAIL，保持阻断状态

Peirce对Antigravity的CN传输媒体26卡独立首评：**9P/4U/13F**，全86单元/13节重读且哈希/双向映射对齐。FAIL涉及事实错误、适用前提错误与映射不足，并非仅格式问题；另4张U保持未证。累计如实加入后47/348篇，**1,169P/17U/13F**、301篇批外。r65 scope重核34,476活跃来源单元。该候选不得进入试用包，也不应先改评审报告“消除”失败；必须保存逐条FAIL，作者基于新候选版本修正，再由非作者全卡重审。其它文章的P不抵消本篇失败。
- 候选SHA：`973d1eddc695362cc6c6286f9eddb2af13119e714f1909cf3c0f23548bd18154`；报告SHA：`6fa2d07471b5326d4e52ef03bb7d579da255a7b1841cc87a1540e51e1e36d75f`。
- r82累计审计SHA：`d750a20923fff2b14e0ad92a12e4deb2b86b84203d9c6510fd975b0bdb6793eb`；r65 scope SHA：`8d7031856e986ca263ee42525335e16aa1a72eb72e5894cab49eec0dee6ebcdc`。


本轮r82源码回归：Python428项，416通过/12跳过/0失败（94.552秒，`.cache/test-suite-20261124-r82.log`）；Node17/17通过。十二个跳项是Windows符号链接权限限制；这仅验证工具/UI回归，不替代本轮13张FAIL修复或全站内容通过。


## r83：DS静态链表独立首评

新增静态链表全23卡独立首评（Zeno非作者）：17P/6U/0F。待证为：初始化保留头槽缺U20/U31直接映射；复杂度/ASL复合检索目标；“上一状态”删除题缺自足初态和直接映射；物理/逻辑顺序与data清除两个目标复合；静态/动态表对照过宽复合；位置无关性未约束ElemType内部指针/外部资源且序列化细节无直证。没有凭常识补证，也不将正确来源哈希等同知识/原子性通过。

r83累计为48/348篇、**1,186P/23U/13F**、300篇批外；r66 scope核34,476活跃来源单元。CN传输媒体13F返修已分配作者，不得将失败候选纳入试用包。精选工作台仍固定r75的41篇960卡，与本累计分离。
- r83累计审计SHA：`a8252eee01de612dc60583575fbe110c96ecae57806de4e8c44e7f079fe0fba2`；r66 scope SHA：`8ac51a5ea653295e0a4d268f8d013a104db50c5113308a9efd0f29e72b0af6d3`。
- 静态链表报告SHA：`9b5e53b7328b0a48eaa8c4fe8fc30d36e534bced5d1e2e2d9b66b4f4baa01471`。


## M2：旧r10空提取轴独立分层抽样（非全量语义闭环）

Newton对已存忽略目录的r10旧账本按5个非零静态解释类分层，17个真实章节locator均从原HTML缓存重新解析：动态/图示4、章节归属4、真题子链接4、兄弟组件2/2全数、来源缺失/懒加载3；另外两个零总体类未伪造样本。所有样本均核对当前缓存SHA、内容哈希、证据元组和结构计数，与旧r10静态解释相符，结论`SAMPLED_STATIC_AXIS_MATCH_WITH_LIMITS`。范围仅对17条静态DOM解释轴做抽查，不是416空节逐项语义验收，不是闭环。账本仍416条`contentGapClosed=false`、待证，M2整份输入也未fresh重验：当前knowledge-units SHA与r10记录不同，因此不能称M2目标完成。旧r10中0 unexplained只表示解释存在，不是图示/真题/动态内容补齐。
- 抽样报告SHA：`9ad4f4cdc92b4b1127d361a444fc39e4d11f48ccd3bd1bc86d1acde70a3d9372`；旧账本SHA `be4a1f381a22e54b4aace2e001b428bb0da4fa8bea005dde8f75e5ca457dcd1d`。


## r84—r85：CO标准r2与DS链式队列r2复评

CO总线标准r2全32卡新评：28P/4U/0F；收窄后的数字/抽象容量模型P不等于实际PCIe协议证明。四U为012串扰映射、016同时收发映射、019被引用PIPE官方PDF当前无法重新读取、027仲裁范围需外篇证据；七项deferred能力不算覆盖。合入r84。

DS链式队列r2全36卡新评：25P/11U/0F，不继承r1的34P。020缓存复杂度为明示地址模型可推导，035已把原创队列前后指针及count初态自足化，二者P；但025–034与036仍映射到原卷链接入口而非可读取题干/完整算法证据，原题与选项身份未证，不能把链接标签升级为真题证明。r2累计r85：48/348篇、**1,180P/29U/13F**、300篇批外，r68 scope审计34,476单元。官方原题证据M4仍为0，因此DS链队列若要提升需要完整证据链；否则作者只能分离自足能力训练与原题身份待证声明，不能删除整个能力范围或伪造来源。
- r85累计审计SHA：`36a1ff8491b6bf2b6f4529dc36b51f8e4df6d0c5a3f9f9b232bd13fc2ac65c05`；r68 scope SHA：`16935f8d632973e6e7ced048df478f3b85740d67e4e9455ea9217fb4b2be7ca2`。
- CO r2报告SHA：`6c9824effdb6b97e4ed086b1f3acbbefd15273e26e67e8468676330a3b188a47`；DS队列r2报告SHA：`07eae75328534ea8d32f48839738189912c8212982b97244bc2da844bb1df1e9`。

## r86：OS文件的基本概念r1并入；M2台账r12重验

OS「文件的基本概念」r1全41卡独立首评（Dalton非作者）：19P/22U/0F，合入r86。r86累计为49/348篇、**1,199P/51U/13F**、299篇批外；r69 scope核34,476活跃来源单元。UNPROVEN不计入通过；CN传输媒体13F仍未闭环（r2待非作者独立评审），失败候选不得纳入试用包。精选工作台仍固定r75的41篇960卡，与本累计分离。
- r86累计审计SHA：`39a57a5a887af8b845b75b5b34d31e6614a3c5c274870f364bab0eced372b9d2`；r86批次SHA：`14ae8af24ddb011b601225aecd80174d613770e859f93fd037df08e08c23db76`；r69 scope SHA：`1e7085417a64dc142811e2e1997ec9836238225837a2e16a9ed12bedad9c5e61`。
- OS文件概念报告SHA：`9df8c252a6ab7afee33da900e57291efba19cb698e704816eaf9405cc2c242e1`。

M2：curated候选枚举修复，`*-structure-check.json`结构检查产物不再计为作者提案（提交`7032ea1`，含回归测试），历史文件未改动。新台账`m2-accounting-20261124-r12`经`verify_disposition_ledger.py`逐项重验`verified=true`：348篇/4,441节/34,476单元/416空节；175个候选审计，其中3个结构无效；416空节均有静态解释但`closedEmptyContentGaps=0`，`humanApprovalsGenerated=0`，`full408Acceptance=false`；25,921单元仍无结构有效的精编处置。这只证明台账绑定与逐项计数一致，不是416空节语义闭环，也不是内容通过。
- r12 ledger SHA：`2bf06fe7b81f5c14aa3920401bf6211e6f11da451c00b2192dd17acce0aabf3d`。

本轮源码回归：Python429项，417通过/12跳过/0失败（跳项为Windows符号链接权限）；Node本轮未重跑。仅验证工具回归，不替代内容验收。


## r87：CN HTTP r5 纳入累计账；2027官方年度来源核验

CN「HTTP」r5于r87替换r86中旧版：16P/3U/0F（19卡）。U项为Content-Length/分块定界卡漏列U32、GET/POST暴露渠道超出当前来源证据、四个HTTP版本并卡不原子。合并后r87累计49/348篇、**1,201P/50U/13F**，299篇不在批次；UNPROVEN与FAIL均不计通过。范围快照r70逐篇绑定当前版本，并记录34,476活跃来源单元。此批次逐卡AI审查不是人工批准，也不是全文章或全站408验收。
- r87累计批次SHA：`1d24c21cf0c109776f45b48d50f17a62826a77348a47d5ecddc707d2d1461147`；审计SHA：`bf08ae0dfa496e86d85b4f35cdb7a55f50513531130d854f0ae2bc4094f69276`；r70范围快照SHA：`9432e358be0e8bdccb9d78872567d4d7585b61a1c3936d926612c03e14453923`。
- r87 scope仅表示49篇已评文章与299篇批外目录范围，不代表34,476单元均已精编或通过。

### M4 2027年度来源核验边界（2026-11-24）

采用2027为目标年度：教育部2027招生规定确认“计算机学科专业基础”为全国统考科目；高教社目录确认2027版大纲书目（教育部教育考试院署名，ISBN 978-7-04-068451-3，2026-09出版）。但是，官方大纲正文/逐条考点未取得，要求数和条文级映射保持`null`；历年官方原题一手证据仍为0。官方网页、书目目录、院校预通知、二手培训材料和CodeBrick练习入口各自证明力不同，不得互相替代。故本轮只能记录年度来源状态，**不能宣称完成官方考纲逐条映射或真题证据链**。核验记录：`data/_reviews/mass-20261123/m4-official-year-source-verification-r1.json`，SHA-256 `8e9a42f4a339983edbece72b0ae4fabd7e9b5f970daf633fdc0882b1fc165cfe`。该记录由AI生成、身份未认证，不是人工批准；HTTP来源原始快照保留于本机忽略缓存，不进入公开仓库。

M4 r22证据清单已纳入本轮5份官方/出版社来源快照（另2份门户观察仅在来源报告中保留），7份原始快照均重核字节数与SHA；本机`audit_exam_evidence.py`对r22检查通过。该检查只验证来源声明与本地绑定，不认证网页真实性；官方要求数/映射覆盖仍为null，官方原题证据仍为0。r22清单SHA：`e6ae45abd6a80d0fd20591a735981c668b47d634a2d4a27dcdd7a52a7037a009`；r30审计SHA：`b0e8f56adeba6672ead70c68822736d515fa409b615fd03a33f42341825485e0`。
