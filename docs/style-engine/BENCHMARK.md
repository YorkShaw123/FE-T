# Style Engine Benchmark 规范

## 1. 目标

Benchmark 用来回答四个问题：

1. 文风信号是否真的能区分语言习惯，而不只是区分主题？
2. 同一作者/语料在切片、长度和重复运行下是否稳定？
3. Style Engine 是否能让生成结果更接近目标风格？
4. 引用参考片段是否提高了复制原文的风险？

Benchmark 不证明生成文本“文学性更高”，也不把单一综合分数当成最终真相。

## 2. 数据治理

- Git 中只允许提交：程序生成文本、明确可再分发文本、短小人工 fixture，以及相应来源/许可证说明。
- 百万字私人语料、受版权保护的完整作品和用户数据库不得加入 Git。
- 本地大型测试集应放在被 `.gitignore` 排除的目录，并以 manifest 记录匿名 ID、字符数、体裁和许可状态，不记录私人文件名或正文。
- 对外报告只保存聚合指标；失败样例若包含私人原文，只在本地检查。
- 固定训练/校准集、验证集和最终保留测试集，避免反复调参污染结论。

## 3. 测试集设计

至少建立以下对照：

### 3.1 同风格、不同主题

同一作者或同一稳定语料来源的不同作品/章节，主题尽量不同。用于验证 Style Engine 不会只靠主题词判断相似。

### 3.2 同主题、不同风格

由不同作者写相近题材，或对同一事实使用不同写法的授权/合成文本。用于验证风格信号能压过主题相似性。

### 3.3 体裁和对话比例对照

小说叙述、对话密集片段、散文、说明性文章分别评测。报告体裁内结果和跨体裁结果，避免把体裁差异误当作者风格。

### 3.4 合成扰动

从同一文本生成可控版本：拆句、并句、增删逗号、改变段落、替换连接词、增加语气词、主动/被动改写。用于检查单个 Feature 与 Style Diff 的方向是否正确。

### 3.5 长度阶梯

同一来源分别取约 300、500、1000、3000、10000 个有效字符，重复抽样。用于确定最小有效样本和置信度。

## 4. Feature 稳定性验证

### 4.1 确定性

- 同一输入连续运行至少 10 次，原始 Feature 应逐项一致。
- 在支持的 Python/Windows 环境上复跑固定 fixture；浮点误差必须小于文档冻结值。

### 4.2 切片稳定性

对同一长文本做多个不重叠抽样，计算每个 Feature 的中位绝对偏差、变异系数或 bootstrap 置信区间。需要报告随文本长度增加是否收敛。

### 4.3 长度敏感性

Feature 与样本有效字符数的相关性不应来自公式本身。每千字和比例指标若在短样本上高方差，应提高最小样本门槛或降低置信度，而不是强行填值。

### 4.4 共线性

在校准语料上计算 Spearman 相关矩阵。绝对相关系数长期高于候选阈值（初始观察值可用 `0.90`，最终由 M1 冻结）的 Feature 必须解释为何同时保留，并采用删除、降权或相关簇聚合之一。

## 5. 文风匹配能力

### 5.1 检索离线指标

- `Recall@K` / `MRR`：查询片段能否优先找到同一风格来源的不同主题文本。
- Pairwise accuracy：同风格不同主题是否比同主题不同风格更近。
- nDCG@K：存在分级相关标签时评估排序质量。
- Diversity@K：返回片段之间的重复程度和来源分布。

报告必须包含以下消融：

- 当前 BM25；
- 当前 Embedding（环境可用时）；
- 仅本地 Style Feature；
- Style Feature + BM25；
- 目标混合与重排方案。

### 5.2 生成结果匹配

对同一内容提示、同一模型参数和固定随机性设置，比较：

- 不使用 Style Engine；
- 现有 Style RAG；
- 新 Style Engine；
- 必要时的新旧混合方案。

自动指标至少包括目标 Feature 距离、句/段统计偏差和标点/功能词组偏差。结果按一级特征组分别报告，不只给总分。

### 5.3 人工盲评

在条件允许时，让评审者不知道样本由哪个方案生成，回答：

- 哪个文本在语言习惯上更接近目标参考？
- 哪个文本更像是在复述参考内容而非学习风格？
- 是否出现明显生硬、为了凑指标而改写的痕迹？

使用成对比较，并记录平局和评审一致性。样本量不足时只报告探索性结果，不宣称显著提升。

## 6. 文本复用风险

必须同时检查参考片段选择阶段和最终生成结果。

### 6.1 精确连续复用

规范化空白后，计算生成文本与每个源片段的最长公共连续字符子串。报告最大长度及超过候选阈值的样本比例。阈值不能在本阶段写死，应通过中文标点、固定短语和人名对结果的影响校准。

### 6.2 字符 n-gram 重合

对多个字符 n 值计算去重后的 Jaccard/containment，并排除过短的高频通用片段。至少报告最大源片段重合和整个语料库重合。

### 6.3 近重复

使用轻量局部方法比较句子或滑动窗口，例如归一化编辑距离、MinHash 候选或现有可用的字符串算法。不得为了该检查引入大型神经模型。

### 6.4 内容实体泄漏

人工或规则检查源语料中特有的人名、地名、事件和专有名词是否进入无关生成结果。该项用于发现“检索了主题/剧情而不是风格”。

### 6.5 验收原则

新方案相对当前基线不得显著增加长连续复用、近重复或专有实体泄漏。发现高风险样本时必须保留可定位的匿名 source/chunk ID，并优先修改检索、片段长度或 Prompt 约束，而不是只调低报告分数。

## 7. 性能与资源

在普通 Windows CPU 基准机上分别测试 10 万、50 万和约 100 万有效字符：

- 冷启动和重复分析耗时；
- 峰值进程内存与增量内存；
- SQLite 文件增长；
- 单次 Profile 比较和 Top-K 检索延迟；
- Sidecar 启动时间及发行包体积变化。

测试应预热一次、正式运行至少 5 次，报告中位数和 P95。具体硬件、Python 版本、提交号、语料规模和缓存状态必须随结果记录。最终性能门槛由 M1/M2 的真实基线决定，不在没有测量前虚构数字。

## 8. 回归与通过条件

每个 milestone 至少满足：

- 固定 fixture 的 Feature 快照只在版本变化时改变；
- 相关 pytest 和 Ruff 实际通过；
- 旧数据库、旧 API 和关闭 Style Engine 的路径保持兼容；
- 文风匹配指标不低于该 milestone 预先记录的基线；
- 文本复用风险不劣化；
- 性能变化在已批准预算内；
- 报告记录失败样例和限制，不只报告平均值。

Benchmark 结果建议保存在不含私人正文的版本化 JSON/Markdown 报告中。只有评测方案、数据许可、运行环境和原始聚合结果都可追踪时，才能把某项算法标记为已验收。

## 9. 最终 A/B/C/D Benchmark（已实现）

最终 Benchmark 使用“先生成并冻结、再离线评分”的两阶段流程。评分工具不会调用 LLM、Embedding API 或网络，也不会重新实现任何检索算法。

### 9.1 四种候选

- `baseline`：普通提示词，不使用 Style Retrieval，不启用 Strict Style Rewrite。
- `existing`：升级前旧 Style RAG 的真实历史生成稿。旧算法已被原地升级，若没有保存历史稿，不得用 New 结果冒充。
- `new`：当前 Style Retrieval 注入参考片段后的生成稿，不启用自动 Style Diff Rewrite。
- `strict`：当前 Style Retrieval，并在显著 Style Diff 时允许最多一次 Strict Style Rewrite 后的最终稿。

四种方法必须使用相同 `writing_task`，并尽量固定 provider、model、思考模式、输出长度要求和其他生成设置。模型 API 未必提供完全确定的采样，因此本 Benchmark 的“可重复”指：冻结输入文件后，评分、报告和匿名顺序可重复；不声称重新请求 LLM 会逐字一致。

### 9.2 Manifest

复制 [benchmark-manifest.example.json](benchmark-manifest.example.json) 到私人工作目录，再填写真实路径。`author_profile` 支持两种形式：

```json
{"author_profile": {"corpus_id": 1}}
```

以上形式从 Flora 当前本地数据库读取已建立且未失效的 Profile；也可以指向单独导出的 Profile JSON：

```json
{"author_profile": "D:/PrivateBenchmark/author-profile.json"}
```

每个任务必须包含：

- 唯一 `id`；
- 四种方法共同使用的 `writing_task`；
- 目标 `scene_type`；
- 供人工盲测阅读的 `reference_author_samples`；
- A/B/C/D 候选正文；
- Existing/New/Strict 当次实际注入的 reference chunk 文件。Baseline 的注入列表必须为空。

实际注入片段应从当次保存的组装 Prompt 或检索快照中提取，不能用后来重新检索的片段替换，否则 Content Leakage 不再对应真实生成过程。正文和 reference 支持 TXT/DOCX。

### 9.3 运行命令

```powershell
.\.venv\Scripts\python scripts\benchmark_style_engine.py "D:\PrivateBenchmark\manifest.json"
```

可指定输出目录：

```powershell
.\.venv\Scripts\python scripts\benchmark_style_engine.py `
  "D:\PrivateBenchmark\manifest.json" `
  --output "D:\PrivateBenchmark\report"
```

默认输出到项目中已被 Git 忽略的 `style-benchmark-reports/`。私人 manifest、正文、reference、报告和盲测包不应加入 Git。

### 9.4 自动指标口径

工具使用当前冻结实现计算：

- `style_distance = 1 - style_score`；
- `rhythm_distance = 1 - rhythm_score`；
- `punctuation_distance = 1 - punctuation_score`；
- `function_word_distance = 1 - function_word_score`；
- `scene_compatibility`：候选本地规则场景与任务目标场景的现有兼容分；
- `content_leakage`：候选与所有实际注入片段中最大的现有 Leakage Penalty。

同时分别报告：

- 最大字符 8-gram containment；
- 最大关键词重合；
- 最大连续公共字符串长度；
- 产生最高综合重合的匿名 reference ID。

距离和 Leakage 越低越好，Scene compatibility 越高越好。指标可能受文本长度、体裁、场景规则和 Profile confidence 影响，不能单独证明“更像作者”或“文学质量更高”。

### 9.5 输出

- `summary.json`：版本、输入内容哈希和四种方案的聚合均值；
- `task_scores.csv`：每个任务、每种方案的完整指标；
- `report.md`：便于阅读的聚合报告和限制声明；
- `blind-test/<task-id>/`：参考样本、匿名 Candidate A/B/C/D 和提问说明；
- `blind-test-admin-key.json`：A/B/C/D 与真实方法的映射，只交给组织者，不交给评审者。

匿名顺序由 `blind_seed + task_id` 稳定生成。同一 manifest、Profile 和正文重复运行会得到相同评分、候选顺序与管理员映射。

### 9.6 人工盲测

评审者只接收 `blind-test/` 子目录，不接收管理员映射。核心问题是：

1. 哪篇在语言习惯上最像参考作者？
2. 哪篇最像在复述或复制参考内容？
3. 哪篇最自然？

允许平局并要求简短理由。任务数或评审人数较少时只报告探索性结果；自动指标与人工偏好不一致时，应保留两者，而不是用自动分数覆盖人工判断。
