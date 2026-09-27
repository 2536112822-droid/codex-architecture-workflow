# 跨领域借鉴与工具选择

此文件保留可执行的取舍，不要求每次重跑 GitHub 调研。依据 2026-09-09 的公开仓库与官方文档核查；依赖接口和维护情况在实际接入时再核实。本轮采用下列方法，没有将这些上游项目安装成新的运行依赖。

## 从别的领域学什么

| 来源 | 可转译的关系 | 在设计项目中如何用 | 不能直接推出 |
|---|---|---|---|
| 摄影、电影画面 | 光线方向、明暗层次、镜头与主体关系 | 材料阅读、室内外过渡、方案表现 | 真实尺寸、建造细节、必须统一电影感 |
| 书籍、杂志、平面设计 | 阅读顺序、文字与图像主次、节奏 | PPT、作品集、分析图与版面叙事 | 每页同模板或只用同一种字体 |
| 信息可视化、地图 | 比较基准、颜色语义、图例、信息密度 | 场地分析、方案对比、图纸索引 | 数据真实性、法定边界或法规合规 |
| 展览、产品、交互 | 使用顺序、反馈、层级、可复用部件 | 空间叙事、项目汇报、参数对照 | UI组件规则等同建筑空间规则 |
| 软件工程、知识管理 | 来源追溯、选择性记忆、版本、可复现检查 | 案例保存、项目隔离、稳定交付 | 测试通过代表审美变好 |

对每个迁移写清来源中的有效关系、当前问题、采用方式和限制，重看原件。用户喜欢一个非建筑案例，不代表要将整个行业风格移入建筑。存储 domain 表示未来用途，仍使用 architecture/presentation/model/render/cad；来源行业可以写入获准保存的分析。

## 本轮吸收的具体机制

- **资料定位**：借鉴 [Docling 的文档结构](https://docling-project.github.io/docling/concepts/docling_document/)，让观察回到文件、页码和局部区域；解析失败或缺页保持未知。文本用于找页，原页用于视觉判断。复杂扫描件出现实际读取缺口时，才评估解析器及 OCR/VLM 权重，缓存配置到用户选定的本地位置。
- **检索与多样性**：借鉴 [Qdrant 的多阶段查询](https://qdrant.tech/documentation/search/hybrid-queries/) 和 [MMR](https://qdrant.tech/documentation/search/search-relevance/#maximal-marginal-relevance-mmr)。当前用项目过滤、少量同义词扩查询、案例去重和主模型重看原图实现轻量改进；这不是已经接入向量检索。以后有实际漏检证据再引入可从正式库重建的索引，未保存草稿不入索引。
- **原件与提炼分开**：借鉴 [Karakeep](https://github.com/karakeep-app/karakeep) 的收藏与来源组织，分清只存链接、归档原件、保存提炼三件事。其自动标签不是用户确认的偏好，OCR/文字语义检索也不等于图像审美理解。当前工具不自动抓取整站或后台监控收件箱。
- **带条件的记忆**：参考 [Mem0](https://github.com/mem0ai/mem0) 的持久记忆与检索思路，保留来源、时间、范围、变化和原话。不能把代理自己的判断当作用户表达的喜好。上游托管平台的 benchmark 与开源 SDK 能力必须分开；对话记忆分数不能作为个人设计效果证据。
- **可编辑输出**：参考 [PptxGenJS](https://github.com/gitbrent/PptxGenJS) 的文字、形状、图表与图片独立对象，继续由现有 presentations 工具交付可编辑内容和实际渲染。母版固定被确认的重复要素，保留每页叙事自由。并非本轮新安装 PptxGenJS。
- **互动演示适配**：[Slidev](https://sli.dev/guide/exporting.html) 可用于需要互动的网页演示；其 PPTX 导出是页面截图，不能用文件扩展名证明可编辑。用户要求普通可编辑 PPT 时使用能生成原生对象的输出层。
- **独立项目风格**：借鉴 [Penpot 的 token sets/themes](https://help.penpot.app/user-guide/design-systems/design-tokens/)，仅在需要时固化当前项目的颜色角色、文字层级、间距与图例。不同项目可有独立集合；空间感、地方性与材料逻辑不能被几个 token 取代。
- **可定位批评**：参考 [Impeccable critique](https://github.com/pbakaus/impeccable/blob/cd12f8660e2dde57b9615c8a6b8ea674101f9cfc/skill/reference/critique.md)，指出具体位置、问题对目标的影响和可操作改法。采用诊断方法，不照搬网页禁色、字体禁令、固定评分或强制美学。
- **可重复评估**：借鉴 [promptfoo 的比较评估](https://www.promptfoo.dev/docs/configuration/expected-outputs/model-graded/select-best/)，固定可比输入，分别看事实、精度、视觉和用户选择。审美评审必须看实际图像，允许旧结果更好。其 [OpenAI image provider](https://github.com/promptfoo/promptfoo/blob/39c4fb55516a405bbb04f6e300a09e6168006c08/src/providers/openai/image.ts#L480) 当前拒绝编辑/参考输入，不用它包裹原生 imagegen；评估与生产调用分开。

## 怎样判断是否值得接入

先确认实际缺口：读不出特定页面、相关案例找不到、导出不可编辑、反复发生同类错误，再选能解决该问题的最小适配。现有专业工具已能完成的工作直接复用。仓库关注度只辅助筛选，最终检查关键源码、许可证、默认分支维护和适合本项目的验证。

GPT-6 继续负责多模态理解、取舍和跨领域创造，原生图像工具继续直接接收适用的参考。辅助模型可以做 OCR/索引，不能因为它的输入限制而降低主模型可见证据，也不能将其评分当成创作边界。模型、推理级别和图像参数以实际配置及当前 schema 为准；不使用未暴露的参数宣称启用了某个后端。
