# SenseNova Registry R1 实施规划

## 目标与现状

在 `veildawn/ai-model-registry` 为 SenseNova Token Plan 的 7 个有效模型新增一个按 Provider 隔离的注册表。当前仓库基线为 `6568ca97932b154e67fc3f2755b7e5cdd55568f5`，分支为 `feat/sensenova-registry-r1`。

现有数据由三份注册数据共同发布：`index.json` 决定消费者读取哪些 Provider，`providers/<name>.json` 保存 Provider 行，`all.json` 是二者和所有 Provider 文件的生成镜像。`scripts/bundle.py` 会按路径收集全部 `providers/*.json`；`all.json` 不可手工编辑。Provider/模型的价格键是 `(provider, model)`，因此同一底模在 SenseNova 下必须保留独立的一行和独立的价格判断。

本次只增加 SenseNova 的 7 个明确模型；不处理 `sensenova-6.7-flash-lite` 的展示、隐藏或过滤，也不改变任何既有 Provider。

## Schema 与仓库约束

- 新文件为 `providers/sensenova.json`，顶层仅使用已知词汇：`name`、`display_name`、`models`；不写 `list_prices`，因为缺省为 `false`，且 SenseNova Token Plan 不是按 USD/token 发布的供应商标价表。也不新增 `hidden_models`。
- Provider 身份字段为 `name: "sensenova"`、`display_name: "SenseNova"`。在 `index.json` 的现有字母顺序中，将 `sensenova` 放在 `qoder-intl` 与 `siliconflow` 之间。
- 每个模型 ID 采用小写、平铺行（不使用 `variants`），并包含当前 schema 已使用的价格、能力和归属字段：`model`、`pricing_style`、四个 `*_per_1m`、`source`、`price_reviewed`、`context_window`、`input_modalities`、`effort_levels`、`surface`。所有行都保留 `price_reviewed`，但其值必须按复用价格或全零未定价这两个价格类别选择；不添加 `max_output_length` 或其他未正式定义字段。
- `pricing_style` 一律为 `openai`；`source` 一律为 `manual`，防止每日委托同步重写这些人工价格判断。`input_modalities` 表示可读输入媒体，`surface` 表示请求应路由到的 API Surface，二者不可互相推断。
- `effort_levels` 按仓库定义的从弱到强顺序书写；`["none"]` 是无思考档位的显式声明，适用于两个 image Surface 模型。
- 现有 Go 测试会核对 index/嵌入 Provider 文件、Provider 内模型 ID（大小写无关）的唯一性、合法 `source`，以及 bundle 与磁盘文件的一致性；它们不提供这 7 行字段值的专门 schema 断言。因此实现时必须按下表逐项复核，不能依赖通用测试替代内容验收。

## 精确模型映射

下表是 `providers/sensenova.json` 的 7 个平铺 `models` 行的能力事实。所有行还应具备后文统一的 `pricing_style`、`source` 与 `price_reviewed` 字段；`price_reviewed` 的具体英文值按后文价格类别确定，并非所有行相同。

| 模型 ID | surface | context_window | input_modalities | effort_levels |
|---|---:|---:|---|---|
| `sensenova-6.8-flash-lite` | `chat` | 262144 | `["text", "image"]` | `["none", "low", "medium", "high"]` |
| `deepseek-v4-pro` | `chat` | 1048576 | `["text"]` | `["none", "low", "medium", "high", "xhigh", "max"]` |
| `deepseek-v4-flash` | `chat` | 1048576 | `["text"]` | `["none", "low", "medium", "high"]` |
| `glm-5.2` | `chat` | 1048576 | `["text"]` | `["none", "low", "medium", "high"]` |
| `kimi-k3` | `chat` | 1048576 | `["text", "image"]` | `["low", "high", "max"]` |
| `sensenova-u1-fast` | `image` | 262144 | `["text"]` | `["none"]` |
| `sensenova-u1.5-lite` | `image` | 262144 | `["text", "image"]` | `["none"]` |

这意味着前五行必须是 `chat`，两个 U1 必须是 `image`；不要因为名称或输入模态改写它们的 Surface。也不要为 U1 增加 `images/edits`、multipart、尺寸或思考响应字段。

## 价格与审阅说明

所有行均写入：

```json
"pricing_style": "openai",
"source": "manual"
```

所有行也都写入 `price_reviewed`，但必须按下列两类使用固定英文值：

```json
// 仅用于复用同底模 canonical vendor list price 的四行。
"price_reviewed": "Canonical vendor list price estimate for reference; SenseNova Token Plan is billed in subscription credits, not USD/token."

// 仅用于四项价格均为 0 的三个 SenseNova 自有模型。
"price_reviewed": "Unpriced: SenseNova Token Plan settles in subscription credits and publishes no USD-per-token list price for this model."
```

前一条说明仅适用于 `deepseek-v4-flash`、`deepseek-v4-pro`、`glm-5.2` 和 `kimi-k3`：其 USD 数字只作 canonical vendor list price 的估值参考，SenseNova Token Plan 的实际结算为订阅积分，绝不可把积分费率写成 USD/token。后一条说明仅适用于 `sensenova-6.8-flash-lite`、`sensenova-u1-fast` 和 `sensenova-u1.5-lite`：它们没有发布 USD-per-token list price，四项零值表示未定价而非免费，也不构成 canonical vendor list price estimate。

| SenseNova 模型 | `prompt_per_1m` | `completion_per_1m` | `cache_read_per_1m` | `cache_write_per_1m` | 值的来源与处理 |
|---|---:|---:|---:|---:|---|
| `deepseek-v4-flash` | 0.22 | 0.66 | 0.007 | 0 | 复用 `providers/deepseek.json` 的同 ID 原厂权威价格。 |
| `deepseek-v4-pro` | 0.66 | 1.98 | 0.022 | 0 | 复用 `providers/deepseek.json` 的同 ID 原厂权威价格。 |
| `glm-5.2` | 1.182225 | 4.137788 | 0.295556 | 0 | 复用 `providers/glm.json` 的同 ID 原厂权威价格。 |
| `kimi-k3` | 2.955563 | 14.777816 | 0.295556 | 0 | 复用 `providers/kimi.json` 中同底模 `k3` 的原厂权威价格。 |
| `sensenova-6.8-flash-lite` | 0 | 0 | 0 | 0 | 未定价；保持 `manual`，不把积分折算为 USD，并使用未定价 `price_reviewed` 文案。 |
| `sensenova-u1-fast` | 0 | 0 | 0 | 0 | 未定价；保持 `manual`，不把积分折算为 USD，并使用未定价 `price_reviewed` 文案。 |
| `sensenova-u1.5-lite` | 0 | 0 | 0 | 0 | 未定价；保持 `manual`，不把积分折算为 USD，并使用未定价 `price_reviewed` 文案。 |

三个全零行表示“未定价”，不是免费模型，也不是可由订阅积分推导出的 token 单价。

## 允许与禁止的文件

实施阶段允许变更且仅限以下文件：

1. `providers/sensenova.json`：新增 7 个 SenseNova 模型行。
2. `index.json`：注册 `sensenova`，保持现有排序惯例。
3. `all.json`：只由 `python3 scripts/bundle.py` 生成，包含新的 index 和 Provider 内容。
4. `docs/plans/2026-09-05-sensenova-registry-r1.md`：保留本规划及实施依据。

禁止变更 `README.md`、`scripts/bundle.py`、任何 Go 测试、任何既有 `providers/*.json`、`ai-provider-source`、`ai-provider-plugins`、生产 AIProxy、数据库和配置。不得写入凭据，且不创建 Commit、Push、PR、发布、部署或合并。

## 实施顺序

1. 新建 `providers/sensenova.json`，按上面的模型映射写入 7 个无 variants 的模型行；省略 `list_prices`，并逐行写入四项价格、能力字段、`manual` 和与其价格类别对应的 `price_reviewed` 文案：四个复用价格行使用 canonical vendor list price 文案，三个全零自有模型使用未定价文案。
2. 更新 `index.json`，将 `sensenova` 注册在 `qoder-intl` 后、`siliconflow` 前，确保其名称与 Provider 文件的 `name` 精确一致。
3. 运行 `python3 scripts/bundle.py` 生成 `all.json`；不以编辑器或格式化工具手动改写该文件。
4. 先以结构化 JSON 检查逐行对照本规划，再运行以下验证命令。只在这些检查通过后确认三份注册数据一致。

```sh
python3 scripts/bundle.py --check
go test ./...
```

## 验收映射

| 验收目标 | 验证证据 |
|---|---|
| 7 个目标模型 ID 唯一 | 检查 `providers/sensenova.json` 仅有表中 7 个小写平铺 ID，且 `go test ./...` 的 `TestExpandedModelIDsAreUnique` 通过。 |
| 两个 U1 为 `image` + `["none"]` | 对照模型映射表与 Provider JSON；它们分别只声明指定输入模态。 |
| 五个文本模型为 `chat` | 对照模型映射表与 Provider JSON，确认前五行的 `surface` 全为 `chat`。 |
| 能力和价格逐项一致 | 将每行的 context、模态、档位、Surface、四个价格、`openai`、`manual` 和对应价格类别的审阅说明逐项与两个表比对；四个复用同底模价格的行必须使用 canonical vendor list price 文案并再比对列出的权威源文件，三个全零自有模型必须使用未定价文案。 |
| SenseNova 非 vendor USD list | Provider 顶层不出现 `list_prices: true`，全零行也不表示免费。 |
| 三份注册数据一致 | `index.json` 包含 `sensenova`、Provider 文件存在且 `name` 匹配；重新生成的 `all.json` 包含二者；`python3 scripts/bundle.py --check` 与 `go test ./...` 均成功。 |

## 风险与回滚

- 最大风险是把订阅积分误报为 USD/token，或将全零未定价误解为免费。两类准确的 `price_reviewed`、`manual` 来源和四项零值保留这一语义；评审时不得以费率换算替换它们，也不得把 canonical vendor list price 文案写到三个全零自有模型。
- 第二个风险是将 image Surface 与图像输入模态混同，导致 U1 被错误路由到 chat，或为 chat 模型错误宣称 image Surface。按字段表逐项核对可避免此问题。
- 第三个风险是只更新 index 或 Provider 而遗漏 bundle。生成器加 `--check` 和 bundle Go 测试用于阻止该类漂移。
- 若实施后发现其中任一事实错误，回滚仅撤销这次新增的 `providers/sensenova.json`、`index.json` 注册项和由此生成的 `all.json` 差异；随后重新运行生成器和两条验证命令。不得借此回滚或修改其他 Provider。

## 无生产变更声明

本变更仅更新静态 registry 数据及其生成 bundle；不修改生产 AIProxy、运行时服务、数据库、配置、凭据、部署或外部系统，也不发布或合并任何内容。
