# Visual suite · 原创素材生成记录

日期：2026-11-17。此文仅记录生成要求与图解设计要求；不包含运行环境路径、账户信息或第三方素材。

## 统一视觉规范

浅色精密静物与光学玻璃：冷白背景（`#f6f7f9` 色系）、拉丝铂金、浅香槟金、少量钴蓝珐琅／反射，柔和大面积棚光、自然接触阴影与细腻微纹理。主视觉保留留白，功能文字和数值由 HTML 单独呈现。

七张静物概念图使用内置 `image_gen` 原创生成。它们具有摄影质感，但不是实物拍摄、行情截图或预测证据；没有搬用第三方图片。三张教程图采用原创 SVG 代码绘制，不经过生成式图片模型。

PNG 原稿统一为 1536 × 1024（3:2），已从仓库删除，只保留 WebP。WebP 由 sharp 0.35.5 进行技术编码，quality 84；未通过裁切或重绘改变概念内容。完整尺寸、字节数、SHA-256、Git blob SHA 见 [manifest.json](manifest.json)。

以下为提交给图像工具的完整提示词，保留原文。

## H01 · 多尺度汇聚主视觉

用途：用层叠玻璃折面表达多尺度观察，不绘制行情、时间区间或胜率。

位置：`frontend/home.html` → `.hero-art .visual-media img`。

[WebP 640px](hero-640.webp) · [WebP 1536px](hero-1536.webp)

```text
Use case: stylized-concept. Asset type: original editorial hero photograph for a refined light financial research website. Create an exquisite physical sculpture called 'Convergence': a flowing fan of very thin optically clear glass sheets, each sheet gently curved like a ribbon, gathering into a quiet central fold and then opening out. It should suggest many observation windows meeting, without depicting any data. Precise cold-worked glass edges catch deep cobalt blue light, a few extremely fine champagne-metal filaments trace two edges, with clear refracted light and subtle soft shadows on a warm-white porcelain gallery plinth. A compelling sculptural silhouette, airy negative space, tactile and optically convincing; like an acclaimed museum design editorial photograph, not a simple computer icon. No ocean, no water surface, no fish, no flower, no clouds, no sun, no cartoon, no rainbow neon, no floating widgets, no graphs, numbers, labels, logos, typography or arrows. Landscape 3:2, sculptural subject centrally composed with generous clean margin, broad gentle studio illumination, sophisticated platinum/clear/cobalt/very restrained champagne palette, seamless near-white #f6f7f9 backdrop. This is decorative art only, never a financial forecast. The site renders all Chinese headings and real data separately in HTML. Full opaque background. Crisp fine material detail, fluid yet architecturally intentional; no cheap plastic, no busy shards.
```

## T01 · 汇率换算

用途：金银色金属片与环形连接，辅助识别汇率换算入口。

位置：`frontend/tools.html` → `#tools .card:has([data-tool="fx"]) .visual-media img`。

[WebP 480px](fx-480.webp) · [WebP 960px](fx-960.webp)

```text
Use case: stylized-concept. Asset type: premium financial utility card illustration, landscape 3:2 image, no UI. Create an original refined still-life for a currency conversion tool: two substantial machined metal tokens, one cool platinum with a subtle cobalt enamel rim, one pale champagne gold, facing at gently different angles and connected visually by a graceful narrow brushed-aluminium loop. They should feel like beautifully photographed tangible precision objects, not flat icons or cartoon coins. No currency symbols, no lettering, numbers, logos or banknotes. Soft warm-white seamless studio background (#f6f7f9 family), restrained cool-blue optical reflections, soft contact shadows grounded on a porcelain surface. Asymmetric balanced composition with objects centrally framed, large clean margins on every side for cropping. One clear visual idea, exquisite micro-texture, believable metal edge machining, soft large-box lighting, luxury editorial product photography, not shiny plastic, no neon, no gradients as background, no charts, no upward arrows, no scattered particles, no decorative sparkles. The image will sit above a real HTML title on a light finance website; all labels and computed numbers are rendered separately in code. Full opaque background.
```

## T02 · 时差与交易时钟

用途：双表盘表达时区差异；图内指针只作装饰，不承担实时时钟。

位置：`frontend/tools.html` → `#tools .card:has([data-tool="tz"]) .visual-media img`。

[WebP 480px](clock-480.webp) · [WebP 960px](clock-960.webp)

```text
Use case: product-mockup. Asset type: an original premium financial utility card illustration for a time-zone conversion tool. Landscape 3:2 composition, ideally 1536 x 1024. Create a beautifully photographed tangible precision instrument: two small round desktop mechanical clock faces at gently different angles, each on its own elegant light brushed-aluminium curved support, arranged as one coherent sculptural still-life. White enamel dials, very fine etched hour tick marks with absolutely no numbers or letters, slim platinum hands at clearly different decorative positions, delicate cobalt-blue enamel bezels. The clocks are decorative objects, not an actual time display. White porcelain base details. Cool soft-white seamless studio backdrop in the #f6f7f9 family, soft large-area lighting, believable grounded contact shadows and restrained cool optical reflections. Central balanced composition, generous margins, material microtexture and precise metal edges, high-end editorial product photography. Match a luxury financial tools suite of brushed platinum, pale champagne metal, porcelain white and very restrained cobalt accents. No text, logos, currency symbols, maps, UI, charts, arrows, sparkles or particles. No neon, cartoon styling, toy-like plastic or busy background. Full opaque background.
```

## T03 · 单位换算

用途：等臂秤表达单位与量纲换算；不提供实际测量读数。

位置：`frontend/tools.html` → `#tools .card:has([data-tool="unit"]) .visual-media img`。

[WebP 480px](units-480.webp) · [WebP 960px](units-960.webp)

```text
Use case: product-mockup. Asset type: an original premium financial utility card illustration for precise unit conversion. Landscape 3:2 composition, ideally 1536 x 1024. Photograph an exquisitely crafted miniature jewellery-laboratory equal-arm balance as a single tangible precision object. Physically coherent instrument: a central vertical brushed-platinum column, a visible central pivot, a fine horizontal equal-length beam, and two shallow circular metal pans each suspended with three fine wires from its beam endpoint; pans hang level. One tiny pale champagne-gold cylindrical calibration weight on one pan, the other visually empty. A modest porcelain-white elliptical base with a delicate cobalt-blue accent ring and a clean mechanical pointer, no lettering. Camera slightly above table level at three-quarter angle so construction reads clearly. Cool soft-white seamless studio background in the #f6f7f9 family, soft large-area lighting, gentle grounded contact shadow. Balanced central composition with generous margins; real machining detail, fine metal surface grain, restrained optical reflections, high-end editorial product photography. Same palette as a luxury finance tools suite: brushed platinum, pale champagne gold, porcelain white, minimal cobalt. No numbers, letters, symbols, logos, screen, UI, chart, arrows, sparkles, particles, neon or cartoon plastic. Keep engineering plausible, do not put random objects around it. Full opaque background.
```

## T04 · 金银价格换算

用途：无文字金银锭，辅助识别贵金属换算入口。

位置：`frontend/tools.html` → `#tools .card:has([data-tool="metal"]) .visual-media img`。

[WebP 480px](metals-480.webp) · [WebP 960px](metals-960.webp)

```text
Use case: product-mockup. Asset type: an original premium financial utility card illustration for gold and silver price conversion. Landscape 3:2 composition, ideally 1536 x 1024. Create one sophisticated tangible still-life: a substantial pale champagne-gold bullion bar with gently sloping sides and softly bevelled precise edges, resting diagonally across a fine brushed-silver bullion bar on a porcelain-white studio surface. Both bars are completely blank with no stamps, marks, digits, logos or lettering. Gold has subtle realistic microscopic brushing and a warm restrained satin sheen, not orange plastic; silver has cool fine linear metal grain, a very subtle cobalt optical reflection along one edge. Keep the two objects identifiable, elegant and not duplicated into a pile. Slightly elevated three-quarter product photography, central asymmetric balanced composition with generous clean margins. Cool soft-white seamless studio background in the #f6f7f9 family, soft large-area studio lights, refined believable contact shadows. Palette consistent with a luxury financial tools suite of brushed platinum, pale champagne gold, porcelain white and tiny cobalt accents. High material realism and calm editorial quality. No UI, charts, arrows, coins, sparkles, particles, neon or cartoon styling. Full opaque background.
```

## T05 · 金价汇率情景

用途：同一金锭经两块棱镜观察，表达情景对照；不表示涨跌预测。

位置：`frontend/tools.html` → `#tools .card:has([data-tool="scen"]) .visual-media img`。

[WebP 480px](scenario-480.webp) · [WebP 960px](scenario-960.webp)

```text
Use case: stylized-concept. Asset type: a premium financial utility card illustration, landscape 3:2, 1536 by 1024 composition, no UI. Create an original editorial still-life visual for comparing two exchange-rate scenarios: one small unmarked pale champagne-gold ingot is behind two precisely cut optical glass prisms positioned at gently different angles. The prisms are clear to extremely pale cobalt blue, and show subtle believable refraction of the SAME underlying gold object, suggesting two ways of looking at the same value. Keep the ingot and glass clearly distinguishable and the scene uncluttered: only these three principal objects, no coins or extra props. Refined realistic product photography with exquisite machined bevels, faint brushed metal grain, optically convincing glass edges, grounded soft contact shadows on a warm-white porcelain studio surface. Opaque seamless background in the #f6f7f9 family, soft large-box lighting, understated cool reflections, luxury materials with restraint. Centered asymmetrical composition, generous clean margin around every object for cropping, object group occupies about 65 percent of the frame. No text, numbers, logos, currency marks, axes, charts, graph lines, arrows, neon, sparkles or particles. Not a flat icon, not cartoon, not cheap translucent plastic. This image is decorative conceptual art for a light finance website; all labels and calculated results will be real HTML outside the image.
```

## T06 · 房贷计算器

用途：建筑模型与钥匙表达贷款计算入口；不表示房价或收益。

位置：`frontend/tools.html` → `#tools .card:has([data-tool="loan"]) .visual-media img`。

[WebP 480px](mortgage-480.webp) · [WebP 960px](mortgage-960.webp)

```text
Use case: stylized-concept. Asset type: premium financial utility card illustration for a mortgage calculator, landscape 3:2, 1536 by 1024 composition, no UI. Create an original exquisitely photographed architectural model of a modest modern home: a compact two-storey porcelain-white house with an elegant roofline, recessed doorway and carefully scaled pale-blue glazing. It is an architect's real physical scale model with fine construction detail, not a cartoon icon or toy. Place a single beautifully machined brushed-platinum house key on the studio surface in the foreground, with a slender pale champagne-gold ring, proportionate to the architectural model composition. Keep the image simple, three-quarter view, one clear house plus key, centrally balanced, with generous white space and clean safe margins on all sides. Entire scene opaque on a seamless cool warm-white background in #f6f7f9 family. Soft large-box studio light, believable contact shadows, restrained cobalt-blue glass reflections, tactile matte porcelain and fine brushed metallic detail, premium mature financial editorial aesthetic. No text, numbers, lettering, logos, percent marks, banknotes, coins, people, grass, trees, fences, arrows or charts. No neon, particles, decorative sparkles, glossy plastic, flat vector or cartoon styling. All loan numbers, labels and assumptions will be rendered separately in HTML outside this decorative artwork.
```

## G01 · 先看日期，再看区间

用途：历史K线止于分析截止线；未来区域只显示候选时间带，不画未来价格。主候选与次级候选保留分歧。。

位置：`frontend/guide.html` → `#read-window .guide-figure img`。

[SVG 原稿](guide-window.svg)

### 原创图解设计要求

历史K线止于分析截止线；未来区域只显示候选时间带，不画未来价格。主候选与次级候选保留分歧。

采用冷白底、深蓝灰文字、克制蓝金强调色。所有形状与文字均为可审查 SVG；明确标注示意用途。不得以示意形态表示真实行情、真实时间区间、已测胜率、首次发布记录或已完成的后端能力。

页面替代文本：操作示意：历史K线止于分析截止线；右侧未来日期槽只有两个候选时间带，没有未来价格。主候选与次级候选分别呈现。

## G02 · 行情、分析与回放分别进行

用途：分别解释行情读取、当前分析与按需历史回放，避免将任务示意误认作真实运行状态或固定耗时承诺。。

位置：`frontend/guide.html` → `#independent-tasks .guide-figure img`。

[SVG 原稿](guide-tasks.svg)

### 原创图解设计要求

分别解释行情读取、当前分析与按需历史回放，避免将任务示意误认作真实运行状态或固定耗时承诺。

采用冷白底、深蓝灰文字、克制蓝金强调色。所有形状与文字均为可审查 SVG；明确标注示意用途。不得以示意形态表示真实行情、真实时间区间、已测胜率、首次发布记录或已完成的后端能力。

页面替代文本：任务关系示意：行情读取后即可查看，当前分析独立更新，历史回放由明确操作启动。三项不是一个串行等待队列。

## G03 · 找到结果背后的证据

用途：区分历史补算与真实发布证据；计算、封存、指定受众可读、本机呈现与修订不是同一时点。未知不回填。。

位置：`frontend/guide.html` → `#evidence-replay .guide-figure img`。

[SVG 原稿](guide-evidence.svg)

### 原创图解设计要求

区分历史补算与真实发布证据；计算、封存、指定受众可读、本机呈现与修订不是同一时点。未知不回填。

采用冷白底、深蓝灰文字、克制蓝金强调色。所有形状与文字均为可审查 SVG；明确标注示意用途。不得以示意形态表示真实行情、真实时间区间、已测胜率、首次发布记录或已完成的后端能力。

页面替代文本：证据概念图：历史补算从过去的数据截止点，到之后的重新计算；发布证据则分别记录计算、封存、指定受众可读、本机呈现和后续修订。封存不等于公开可见，未知时间不能回填。

## 更新约束

改图时先确认用途与编号；标题、报价、计算值、时区状态与证据时间不写进装饰图。重新编码或修改 SVG 后重算 manifest 内全部相关哈希。图片更新不能被解释为数据源、模型逻辑、计算结果或预测能力更新。
