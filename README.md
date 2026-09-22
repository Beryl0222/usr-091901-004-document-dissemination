# 历史文献传播谱系

记录手稿、连载、单行本、合刊、译本、内部资料与亲历者来稿之间的来源、考证与授权关系，
并把专题中的每一句结论性说明溯源到所采用的文献版本、贡献者、证据、授权与历次争议。

项目以领域契约约定参与者、状态、受控词表和不可破坏的业务原则；纯标准库实现的领域层
（`domain.py`）负责全部业务规则，HTTP 层（`service.py`）只做协议转换。所有写操作只向
事件日志追加事件，不做物理删除或就地覆盖。

## 核心模型（见 `domain_contract.json`）

- **作品 work**：抽象文字单元，挂多个异名（初题名/伪装题名/外文题名），可登记缺卷。
- **文献版本 document_version**：手稿、来稿、连载、单行本、合刊、译本、内部资料；
  状态流转 `待编目 → 考证中 → 待授权 → 可采用 → 已出版`，已出版为终态。
- **贡献 contribution**：署名/执笔/口译/辑录/校订，`signed_name` 记录实际署名（笔名须先在人物别名中登记）。
- **证据 evidence**：书影/刊物期次/档案/手稿影像/页码著录/署名著录/亲历者来稿，
  必须可定位——页码、期次、馆藏索取号或链接至少一项，且标注确定性（确证/推定/存疑）。
- **主张 claim**：作品作者/版本署名/版本底本的竞争性观点，默认“候选”；须有确证级证据
  才能采纳，更强证据可取代旧结论（旧结论转“曾采纳”，异说永不删除）。
- **谱系 link**：再版自/译自/修订自/源自稿/合刊收录/连载为，方向一律为
  **派生版本 → 来源版本**；一个译本可分别挂多个底本，每条关系各附证据。
- **片段 fragment / 复用 use**：同一段文字跨书复用的定位记录。
- **补充版本 supplement**：新增书影/署名考证/页码订正只追加，订正须给出 field/from/to，
  被订正原内容保留，已出版快照引用不被替换。
- **素材 asset / 许可 permission / 导出检查 export-check**：导出逐素材校验
  用途、有效期、地域（支持“全球/全国/*”通配）与清晰度门槛
  （展览≥可用，电子出版≥高清）；一件不过整批不可导出。
- **争议 controversy**：开放观点与结论并存，可挂主张与证据。
- **专题 topic / 说明 statement / 快照 snapshot**：
  - “最早/首部/源自稿”类说明必须同时给确定性、引证据、引版本；作者结论只能挂“已采纳”主张。
  - 出版时冻结快照（说明、版本、贡献、人物、证据、主张、谱系、素材授权、争议、当时的补充版本）。
  - 出版后只能追加补充版本并以新版次出版，不能改动旧说明；快照可随时原样复原。
  - `trace_statement` 从一句说明展开：版本、贡献者（笔名→真人）、证据、竞争主张、
    谱系、素材与许可、争议、以及收录该说明的所有快照。

## 运行与测试

```bash
python3 service.py --check            # 契约词表与领域实例自检
python3 service.py --port 8000        # 启动 HTTP 服务
python3 -m unittest -v                # 19 个测试（契约/领域场景/HTTP 端到端）
```

## 主要 HTTP 接口

服务保持无状态协议约定，内存态适用于演示与测试；事件日志（`GET /api/events`）即事实流，
可据此持久化或重放。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` `/contract` | 健康检查、领域契约 |
| POST | `/api/works` `/api/people` | 建作品（含异名）、登记人物（含笔名） |
| POST | `/api/works/:id/missing-volumes` | 登记缺卷（须证据） |
| POST | `/api/versions` | 建版本（kind 受控：手稿/来稿/连载/单行本/合刊/译本/内部资料） |
| POST | `/api/versions/:id/transitions` | 状态流转 |
| GET | `/api/versions/:id/view` `/lineage` | 版本视图（含追加的订正）、谱系遍历（含缺卷/循环告警） |
| POST | `/api/contributions` | 署名等贡献（笔名须为已登记别名） |
| POST | `/api/evidence` | 可定位证据（page/issue/shelfmark/url 至少一项） |
| POST | `/api/claims` `/api/claims/:id/adopt` | 竞争主张并存、按证据强度采纳 |
| POST | `/api/links` | 谱系关系（派生→来源；多底本分别登记） |
| POST | `/api/fragments` `/api/fragments/:id/uses`；GET `…/reuse` | 跨书文字复用 |
| POST | `/api/supplements` | 新增书影/署名考证/页码订正（只追加） |
| POST | `/api/assets` `/api/permissions` `/api/export-checks` | 素材、馆藏许可、导出判定 |
| POST | `/api/controversies` 及其 `positions`/`resolve` | 争议 |
| POST | `/api/topics` 及其 `statements`/`publish` | 专题、结论说明、出版冻结 |
| GET | `/api/statements/:id/trace` | 一句说明的全链溯源 |
| GET | `/api/snapshots/:id` | 复原某次出版快照 |
| GET | `/api/events` | 追加式事件日志 |

语义错误返回 `400 {"error":400,"message":...}`，引用不存在返回 `404`。

## 一条主线示例

```bash
# 连载证据 → 笔名署名 → 竞争主张按确证证据采纳 → 版本流转至可采用
# → “最早”说明（确定性+证据+版本）→ 出版冻结
# → 新见书影与页码订正以补充版本追加 → 旧快照仍是旧页码，trace 完整可回
```
