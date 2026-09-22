"""历史文献传播谱系——领域层。

设计要点（与 domain_contract.json 对应）：

* 所有写操作只向事件日志追加事件，并同步更新内存状态；不做物理删除或就地覆盖。
* “最早/首部/源自某稿”等结论必须挂接可定位证据并标注确定程度。
* 竞争性作者/底本主张允许并存；采纳只改变主张状态，不删除异说。
* 新发现以“补充版本”追加（新书影、署名考证、页码订正），被订正原内容保留。
* 出版生成冻结快照；之后的任何追加都不回溯改变快照，可随时复原。
* 素材导出逐条校验许可用途、有效期、地域范围与清晰度门槛。
"""

import copy
import datetime as _dt
import json
from pathlib import Path

CONTRACT_PATH = Path(__file__).with_name("domain_contract.json")

# 方向约定：谱系关系一律从“后出/派生版本”指向“所据/来源版本”。
DERIVED_TO_SOURCE = {
    "再版自": "新版本 → 旧版本",
    "译自": "译本 → 底本（可有多个，分别登记证据）",
    "修订自": "修订本 → 原本",
    "源自稿": "刊本/印本 → 手稿或来稿",
    "合刊收录": "合刊 → 被收录的单行本或期次",
    "连载为": "结集本 → 所据连载期次",
}

QUALITY_RANK = {"模糊": 0, "可用": 1, "高清": 2}
EXPORT_QUALITY_MIN = {"展览": "可用", "电子出版": "高清"}
REGION_WILDCARDS = {"*", "全球", "全国"}

STATEMENT_KINDS = ["最早", "首部", "源自稿", "其他"]
CLAIM_STATUSES = ["候选", "已采纳", "曾采纳", "未采纳"]
CONTROVERSY_STATUSES = ["开放", "结论"]


class DomainError(Exception):
    """请求语义不合法（400）。"""


class NotFound(DomainError):
    """引用的实体不存在（404）。"""


def load_contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _today():
    return _dt.date.today().isoformat()


class DocumentLineage:
    """文献传播谱系的内存领域服务（可整体序列化/复原）。"""

    def __init__(self, contract=None, clock=_today):
        self.contract = contract or load_contract()
        self._clock = clock
        self.events = []
        self.people = {}
        self.works = {}
        self.versions = {}
        self.contributions = {}
        self.evidence = {}
        self.claims = {}
        self.links = {}
        self.fragments = {}
        self.fragment_uses = []
        self.supplements = []
        self.assets = {}
        self.permissions = {}
        self.export_checks = {}
        self.controversies = {}
        self.topics = {}
        self.statements = {}
        self.snapshots = {}
        self._counters = {}

    # ------------------------------------------------------------------ 基础

    def _emit(self, op, details):
        event = {"seq": len(self.events) + 1, "op": op, "at": self._clock(),
                 "details": details}
        self.events.append(event)
        return event

    def _new_id(self, prefix):
        n = self._counters.get(prefix, 0) + 1
        self._counters[prefix] = n
        return f"{prefix}_{n}"

    def _vocab(self, key):
        return set(self.contract[key])

    def _check_vocab(self, key, value, label):
        if value not in self._vocab(key):
            raise DomainError(f"{label}“{value}”不在受控词表中，允许值："
                              + "、".join(self.contract[key]))

    def _get(self, store, key, label):
        if key not in store:
            raise NotFound(f"{label}不存在：{key}")
        return store[key]

    def _check_locatable(self, record):
        if not record.get("citation"):
            raise DomainError("证据必须给出出处说明 citation")
        loc = record.get("locator") or {}
        if not any(str(loc.get(k) or "").strip()
                   for k in ("page", "issue", "shelfmark", "url")):
            raise DomainError(
                f"证据“{record['id']}”缺少可定位出处：页码、期次、馆藏索取号或链接至少一项")

    def _require_evidence(self, evidence_ids, what):
        if not evidence_ids:
            raise DomainError(f"{what}必须至少引用一条可定位证据")
        for eid in evidence_ids:
            self._get(self.evidence, eid, "证据")

    # ------------------------------------------------------------------ 人物与作品

    def register_person(self, name, aliases=None, person_id=None, note=""):
        """登记人物及其笔名/别名。笔名署名的贡献据此归集到真人。"""
        pid = person_id or self._new_id("person")
        if pid in self.people:
            raise DomainError(f"人物已存在：{pid}")
        record = {"id": pid, "name": name, "aliases": list(aliases or []),
                  "note": note}
        self.people[pid] = record
        self._emit("person.registered", {"id": pid, "name": name,
                                          "aliases": record["aliases"]})
        return copy.deepcopy(record)

    def create_work(self, title, alt_titles=None, work_id=None, note=""):
        """作品：抽象文字单元。异名（初题名、伪装题名、外文题名）挂在这里。"""
        wid = work_id or self._new_id("work")
        if wid in self.works:
            raise DomainError(f"作品已存在：{wid}")
        record = {"id": wid, "title": title,
                  "alt_titles": list(alt_titles or []),
                  "missing_volumes": [], "note": note}
        self.works[wid] = record
        self._emit("work.created", {"id": wid, "title": title,
                                    "alt_titles": record["alt_titles"]})
        return copy.deepcopy(record)

    def register_missing_volume(self, work_id, position, reason, evidence_ids=None,
                                note=""):
        """显式登记缺卷。谱系遍历遇到缺卷所在作品会给出提示，不允许隐式跳过。"""
        work = self._get(self.works, work_id, "作品")
        self._require_evidence(evidence_ids or [], "缺卷登记")
        record = {"position": position, "reason": reason,
                  "evidence_ids": list(evidence_ids or []), "note": note}
        work["missing_volumes"].append(record)
        self._emit("work.missing_volume_registered",
                   {"work_id": work_id, **record})
        return copy.deepcopy(record)

    # ------------------------------------------------------------------ 版本与贡献

    def create_version(self, work_id, kind, title, version_id=None,
                       language="中文", publication="", issue="", volume="",
                       pages="", published_on="", note=""):
        """文献版本：手稿/来稿/连载/单行本/合刊/译本/内部资料等具体载体。"""
        self._get(self.works, work_id, "作品")
        self._check_vocab("version_kinds", kind, "版本类型")
        vid = version_id or self._new_id("ver")
        if vid in self.versions:
            raise DomainError(f"版本已存在：{vid}")
        record = {
            "id": vid, "work_id": work_id, "kind": kind, "title": title,
            "language": language, "publication": publication, "issue": issue,
            "volume": volume, "pages": pages, "published_on": published_on,
            "state": "待编目", "note": note,
        }
        self.versions[vid] = record
        self._emit("version.created", {"id": vid, "work_id": work_id,
                                       "kind": kind, "title": title})
        return copy.deepcopy(record)

    def transition_version(self, version_id, to_state):
        """按契约 state_transitions 推进版本状态；已出版为终态。"""
        version = self._get(self.versions, version_id, "版本")
        allowed = self.contract["state_transitions"].get(version["state"], [])
        if to_state not in allowed:
            raise DomainError(
                f"版本“{version_id}”不能从{version['state']}转为{to_state}"
                f"（允许：{'、'.join(allowed) or '无'}）")
        old = version["state"]
        version["state"] = to_state
        self._emit("version.state_transitioned",
                   {"id": version_id, "from": old, "to": to_state})
        return copy.deepcopy(version)

    def add_contribution(self, version_id, person_id, role, signed_name="",
                         evidence_ids=None, contribution_id=None, note=""):
        """登记某人对某版本的贡献。signed_name 记录该次实际署名（可笔名）。"""
        version = self._get(self.versions, version_id, "版本")
        person = self._get(self.people, person_id, "人物")
        self._check_vocab("contribution_roles", role, "贡献角色")
        self._require_evidence(evidence_ids or [], "署名贡献")
        if signed_name and signed_name != person["name"] \
                and signed_name not in person["aliases"]:
            raise DomainError(
                f"署名“{signed_name}”既不是{person['name']}本人姓名，"
                "也未登记为其别名，请先登记笔名")
        cid = contribution_id or self._new_id("contrib")
        record = {"id": cid, "version_id": version_id, "work_id": version["work_id"],
                  "person_id": person_id, "role": role,
                  "signed_name": signed_name or person["name"],
                  "evidence_ids": list(evidence_ids or []), "note": note}
        self.contributions[cid] = record
        self._emit("contribution.added",
                   {"id": cid, "version_id": version_id, "person_id": person_id,
                    "role": role, "signed_name": record["signed_name"]})
        return copy.deepcopy(record)

    # ------------------------------------------------------------------ 证据与主张

    def add_evidence(self, evidence_type, citation, locator=None, certainty="确证",
                     excerpt="", asset_id=None, evidence_id=None, note=""):
        """登记可定位证据。locator 可含 container/issue/volume/page/shelfmark/url。"""
        self._check_vocab("evidence_types", evidence_type, "证据类型")
        self._check_vocab("certainties", certainty, "确定程度")
        if asset_id:
            self._get(self.assets, asset_id, "素材")
        eid = evidence_id or self._new_id("ev")
        record = {"id": eid, "type": evidence_type, "citation": citation,
                  "locator": dict(locator or {}), "certainty": certainty,
                  "excerpt": excerpt, "asset_id": asset_id, "note": note}
        self._check_locatable(record)
        self.evidence[eid] = record
        self._emit("evidence.added", {"id": eid, "type": evidence_type,
                                      "citation": citation, "certainty": certainty})
        return copy.deepcopy(record)

    def add_claim(self, subject, person_id, summary, evidence_ids,
                  certainty="推定", work_id=None, version_id=None,
                  claim_id=None, note=""):
        """登记作者身份或底本主张。竞争性主张允许并存，默认状态为“候选”。"""
        self._check_vocab("claim_subjects", subject, "主张主题")
        self._check_vocab("certainties", certainty, "确定程度")
        self._get(self.people, person_id, "人物")
        if work_id:
            self._get(self.works, work_id, "作品")
        if version_id:
            self._get(self.versions, version_id, "版本")
        if not (work_id or version_id):
            raise DomainError("主张必须指向作品或版本之一")
        self._require_evidence(evidence_ids, "身份/底本主张")
        cid = claim_id or self._new_id("claim")
        record = {"id": cid, "subject": subject, "person_id": person_id,
                  "work_id": work_id, "version_id": version_id,
                  "summary": summary, "evidence_ids": list(evidence_ids),
                  "certainty": certainty, "status": "候选", "note": note,
                  "created_seq": len(self.events) + 1}
        self.claims[cid] = record
        self._emit("claim.added", {"id": cid, "subject": subject,
                                   "person_id": person_id, "status": "候选"})
        return copy.deepcopy(record)

    def _claim_target(self, claim):
        return (claim["subject"], claim["work_id"], claim["version_id"])

    def _confirmed_count(self, claim):
        return sum(1 for eid in claim["evidence_ids"]
                   if self.evidence[eid]["certainty"] == "确证")

    def adopt_claim(self, claim_id):
        """采纳主张：须有确证级证据；若同主题已有采纳主张，新主张须以更强证据取而代之。

        被取代的旧主张转为“曾采纳”而非删除——异说与历次结论都可回溯。
        """
        claim = self._get(self.claims, claim_id, "主张")
        if self._confirmed_count(claim) == 0:
            raise DomainError(
                f"主张“{claim_id}”没有确证级证据支撑，不能采纳；可补充证据后重试")
        strength = self._confirmed_count(claim)
        for other in self.claims.values():
            if other["id"] == claim_id:
                continue
            if other["status"] == "已采纳" \
                    and self._claim_target(other) == self._claim_target(claim) \
                    and self._confirmed_count(other) >= strength:
                raise DomainError(
                    f"同主题已采纳主张“{other['id']}”的证据不弱于本主张，"
                    "不能覆盖；如确有新证，请先补充确证级证据")
        for other in self.claims.values():
            if other["id"] != claim_id and other["status"] == "已采纳" \
                    and self._claim_target(other) == self._claim_target(claim):
                other["status"] = "曾采纳"
                self._emit("claim.superseded", {"id": other["id"],
                                                "by": claim_id})
        claim["status"] = "已采纳"
        self._emit("claim.adopted", {"id": claim_id})
        return copy.deepcopy(claim)

    # ------------------------------------------------------------------ 谱系与复用

    def add_link(self, relation, source_version_id, target_version_id,
                 evidence_ids, link_id=None, note=""):
        """登记谱系关系。方向一律为 派生版本 → 来源版本（见 DERIVED_TO_SOURCE）。"""
        self._check_vocab("lineage_relations", relation, "谱系关系")
        self._get(self.versions, source_version_id, "版本")
        self._get(self.versions, target_version_id, "版本")
        if source_version_id == target_version_id:
            raise DomainError("谱系关系不能指向版本自身")
        self._require_evidence(evidence_ids, f"{relation}关系")
        lid = link_id or self._new_id("link")
        record = {"id": lid, "relation": relation,
                  "source_version_id": source_version_id,
                  "target_version_id": target_version_id,
                  "evidence_ids": list(evidence_ids), "note": note}
        self.links[lid] = record
        self._emit("lineage.linked",
                   {"id": lid, "relation": relation,
                    "source": source_version_id, "target": target_version_id})
        return copy.deepcopy(record)

    def create_fragment(self, label, excerpt="", fragment_id=None):
        """可跨书复用的同一段文字。以 label（常用首句或编号）标识。"""
        fid = fragment_id or self._new_id("frag")
        record = {"id": fid, "label": label, "excerpt": excerpt}
        self.fragments[fid] = record
        self._emit("fragment.created", {"id": fid, "label": label})
        return copy.deepcopy(record)

    def register_fragment_use(self, fragment_id, version_id, pages="", note=""):
        """登记某段文字在某版本中的出现；多次登记即构成跨书复用链。"""
        self._get(self.fragments, fragment_id, "文字片段")
        version = self._get(self.versions, version_id, "版本")
        use = {"fragment_id": fragment_id, "version_id": version_id,
               "work_id": version["work_id"], "pages": pages, "note": note}
        self.fragment_uses.append(use)
        self._emit("fragment.use_registered", dict(use))
        return copy.deepcopy(use)

    def fragment_reuse(self, fragment_id):
        """返回某段文字的全部复用位置，按版本与作品展开。"""
        self._get(self.fragments, fragment_id, "文字片段")
        uses = [u for u in self.fragment_uses if u["fragment_id"] == fragment_id]
        return [{**u,
                 "version_title": self.versions[u["version_id"]]["title"],
                 "work_title": self.works[u["work_id"]]["title"]}
                for u in uses]

    def traverse_lineage(self, version_id):
        """从给定版本出发遍历谱系，显式标注缺卷提示，检测循环。"""
        self._get(self.versions, version_id, "版本")
        seen, order, warnings = set(), [], []

        def walk(vid, visiting):
            if vid in visiting:
                warnings.append(f"谱系存在循环，已在 {vid} 处截断")
                return
            if vid in seen:
                return
            visiting.add(vid)
            seen.add(vid)
            version = self.versions[vid]
            node = {"version_id": vid, "relations": []}
            work = self.works[version["work_id"]]
            if work["missing_volumes"]:
                warnings.append(
                    f"版本 {vid} 所属作品《{work['title']}》存在 "
                    f"{len(work['missing_volumes'])} 处缺卷登记，谱系可能不完整")
            for link in self.links.values():
                if link["source_version_id"] == vid:
                    node["relations"].append({
                        "relation": link["relation"],
                        "other_version_id": link["target_version_id"],
                        "direction": "derived_to_source",
                        "evidence_ids": link["evidence_ids"]})
                    walk(link["target_version_id"], visiting)
                if link["target_version_id"] == vid:
                    node["relations"].append({
                        "relation": link["relation"],
                        "other_version_id": link["source_version_id"],
                        "direction": "source_to_derived",
                        "evidence_ids": link["evidence_ids"]})
                    walk(link["source_version_id"], visiting)
            order.append(node)
            visiting.discard(vid)

        walk(version_id, set())
        return {"root": version_id, "nodes": order, "warnings": warnings}

    # ------------------------------------------------------------------ 补充版本（只追加）

    def add_supplement(self, kind, target_type, target_id, summary,
                       evidence_id, correction=None, supplement_id=None):
        """新增书影/署名考证/页码订正，以补充版本追加。

        被订正对象的原内容绝不改写；订正内容（如页码）只作为补充信息存在，
        已出版快照继续引用原样。
        """
        self._check_vocab("supplement_kinds", kind, "补充类型")
        stores = {"version": self.versions, "evidence": self.evidence,
                  "contribution": self.contributions, "claim": self.claims,
                  "work": self.works}
        if target_type not in stores:
            raise DomainError(f"不支持的补充对象类型：{target_type}")
        self._get(stores[target_type], target_id, "补充对象")
        self._get(self.evidence, evidence_id, "证据")
        if kind == "页码订正":
            if not correction or not correction.get("field") \
                    or "from" not in correction or "to" not in correction:
                raise DomainError("页码订正必须给出 correction：field/from/to")
        sid = supplement_id or self._new_id("supp")
        record = {"id": sid, "kind": kind, "target_type": target_type,
                  "target_id": target_id, "summary": summary,
                  "evidence_id": evidence_id,
                  "correction": copy.deepcopy(correction), "at": self._clock()}
        self.supplements.append(record)
        self._emit("supplement.added",
                   {"id": sid, "kind": kind, "target_type": target_type,
                    "target_id": target_id})
        return copy.deepcopy(record)

    def supplements_for(self, target_type, target_id):
        return [copy.deepcopy(s) for s in self.supplements
                if s["target_type"] == target_type and s["target_id"] == target_id]

    def view_version(self, version_id):
        """版本的工作态视图：原内容 + 追加其上的全部补充与订正（原样保留）。"""
        version = self._get(self.versions, version_id, "版本")
        supplements = self.supplements_for("version", version_id)
        view = copy.deepcopy(version)
        view["supplements"] = supplements
        corrections = [s["correction"] for s in supplements if s["correction"]]
        view["has_corrections"] = bool(corrections)
        return view

    # ------------------------------------------------------------------ 素材、许可与导出

    def register_asset(self, name, quality, evidence_id=None, asset_id=None,
                       note=""):
        self._check_vocab("asset_quality", quality, "素材清晰度")
        if evidence_id:
            self._get(self.evidence, evidence_id, "证据")
        aid = asset_id or self._new_id("asset")
        record = {"id": aid, "name": name, "quality": quality,
                  "evidence_id": evidence_id, "note": note}
        self.assets[aid] = record
        self._emit("asset.registered", {"id": aid, "quality": quality})
        return copy.deepcopy(record)

    def grant_permission(self, asset_id, holder, scopes, regions,
                         valid_from, valid_to, permission_id=None, note=""):
        """登记馆藏许可：用途（展览/电子出版/内部研究）、地域、起止日期。"""
        self._get(self.assets, asset_id, "素材")
        for scope in scopes:
            self._check_vocab("permission_scopes", scope, "许可用途")
        for day in (valid_from, valid_to):
            _dt.date.fromisoformat(day)
        if valid_from > valid_to:
            raise DomainError("许可起始日不能晚于截止日")
        pid = permission_id or self._new_id("perm")
        record = {"id": pid, "asset_id": asset_id, "holder": holder,
                  "scopes": list(scopes), "regions": list(regions),
                  "valid_from": valid_from, "valid_to": valid_to, "note": note}
        self.permissions[pid] = record
        self._emit("permission.granted", {"id": pid, "asset_id": asset_id,
                                          "scopes": record["scopes"],
                                          "regions": record["regions"]})
        return copy.deepcopy(record)

    def evaluate_export(self, purpose, region, asset_ids, on_date=None,
                        request_id=None):
        """判定某次展览/电子出版能否导出给定素材集合。

        逐素材校验：用途在许可范围内、日期在有效期内、地域落在许可地域
        （支持“全球/全国/*”通配）、清晰度达到该用途门槛。任一不过即该素材不可导出，
        整体仅当全部素材通过时才可导出。
        """
        self._check_vocab("export_purposes", purpose, "导出用途")
        on_date = on_date or self._clock()
        min_quality = EXPORT_QUALITY_MIN[purpose]
        results = []
        for aid in asset_ids:
            asset = self._get(self.assets, aid, "素材")
            reasons = []
            covering = [p for p in self.permissions.values()
                        if p["asset_id"] == aid]
            if not covering:
                reasons.append("无任何馆藏许可")
            pass_perm = None
            for perm in covering:
                fails = []
                if purpose not in perm["scopes"]:
                    fails.append(f"许可用途不含{purpose}")
                if not (perm["valid_from"] <= on_date <= perm["valid_to"]):
                    fails.append(
                        f"使用日期 {on_date} 不在许可有效期 "
                        f"{perm['valid_from']}~{perm['valid_to']} 内")
                region_ok = any(r in REGION_WILDCARDS or r == region
                                for r in perm["regions"])
                if not region_ok:
                    fails.append(f"许可地域{'、'.join(perm['regions'])}不含{region}")
                if not fails:
                    pass_perm = perm["id"]
                    break
                reasons.append(f"许可 {perm['id']}：" + "；".join(fails))
            if QUALITY_RANK[asset["quality"]] < QUALITY_RANK[min_quality]:
                reasons.append(
                    f"清晰度“{asset['quality']}”低于{purpose}门槛“{min_quality}”")
            results.append({"asset_id": aid, "name": asset["name"],
                            "allowed": pass_perm is not None
                            and QUALITY_RANK[asset["quality"]]
                            >= QUALITY_RANK[min_quality],
                            "permission_id": pass_perm, "reasons": reasons})
        rid = request_id or self._new_id("export")
        record = {"id": rid, "purpose": purpose, "region": region,
                  "date": on_date, "asset_ids": list(asset_ids),
                  "results": results,
                  "export_allowed": all(r["allowed"] for r in results)}
        self.export_checks[rid] = record
        self._emit("export.evaluated",
                   {"id": rid, "purpose": purpose, "region": region,
                    "allowed": record["export_allowed"]})
        return copy.deepcopy(record)

    # ------------------------------------------------------------------ 争议

    def open_controversy(self, title, subject_refs=None, positions=None,
                         controversy_id=None, note=""):
        """登记争议（作者、底本、页码等）。positions 可挂主张与证据。"""
        for ref in subject_refs or []:
            self._require_ref(ref)
        cid = controversy_id or self._new_id("contro")
        record = {"id": cid, "title": title,
                  "subject_refs": list(subject_refs or []),
                  "positions": list(positions or []), "status": "开放",
                  "resolution": "", "note": note}
        self.controversies[cid] = record
        self._emit("controversy.opened", {"id": cid, "title": title})
        return copy.deepcopy(record)

    def _require_ref(self, ref):
        kind = ref.get("type")
        rid = ref.get("id")
        stores = {"work": self.works, "version": self.versions,
                  "claim": self.claims, "evidence": self.evidence,
                  "statement": self.statements}
        if kind not in stores or rid not in stores[kind]:
            raise DomainError(f"争议引用对象不存在：{kind}:{rid}")

    def add_controversy_position(self, controversy_id, summary, claim_id=None,
                                 evidence_ids=None):
        contro = self._get(self.controversies, controversy_id, "争议")
        if claim_id:
            self._get(self.claims, claim_id, "主张")
        self._require_evidence(evidence_ids or [], "争议观点")
        position = {"summary": summary, "claim_id": claim_id,
                    "evidence_ids": list(evidence_ids or [])}
        contro["positions"].append(position)
        self._emit("controversy.position_added",
                   {"id": controversy_id, "position": summary})
        return copy.deepcopy(position)

    def resolve_controversy(self, controversy_id, resolution):
        contro = self._get(self.controversies, controversy_id, "争议")
        contro["status"] = "结论"
        contro["resolution"] = resolution
        self._emit("controversy.resolved",
                   {"id": controversy_id, "resolution": resolution})
        return copy.deepcopy(contro)

    # ------------------------------------------------------------------ 专题、说明与出版快照

    def create_topic(self, title, work_ids=None, topic_id=None, note=""):
        for wid in work_ids or []:
            self._get(self.works, wid, "作品")
        tid = topic_id or self._new_id("topic")
        record = {"id": tid, "title": title, "work_ids": list(work_ids or []),
                  "statement_ids": [], "published": False, "editions": []}
        self.topics[tid] = record
        self._emit("topic.created", {"id": tid, "title": title})
        return copy.deepcopy(record)

    def add_statement(self, topic_id, text, kind="其他", evidence_ids=None,
                      cited_version_ids=None, certainty=None,
                      adopted_claim_id=None, statement_id=None, note=""):
        """在专题中加一句说明。

        最早/首部/源自稿三类说明必须：给出确定性、引用≥1条可定位证据、
        引用≥1个文献版本；如涉及作者结论可挂已采纳主张。
        """
        topic = self._get(self.topics, topic_id, "专题")
        if topic["published"]:
            raise DomainError(
                "专题已出版，已有说明不可改动；新材料请以补充版本追加，并以新版次出版")
        if kind not in STATEMENT_KINDS:
            raise DomainError(f"说明类型允许：{'、'.join(STATEMENT_KINDS)}")
        ev_ids = list(evidence_ids or [])
        ver_ids = list(cited_version_ids or [])
        if kind in ("最早", "首部", "源自稿"):
            if certainty is None:
                raise DomainError(f"{kind}类说明必须标注确定程度")
            self._check_vocab("certainties", certainty, "确定程度")
            self._require_evidence(ev_ids, f"{kind}类说明")
            if not ver_ids:
                raise DomainError(f"{kind}类说明必须引用所依据的文献版本")
        for eid in ev_ids:
            self._get(self.evidence, eid, "证据")
        for vid in ver_ids:
            self._get(self.versions, vid, "版本")
        if adopted_claim_id:
            claim = self._get(self.claims, adopted_claim_id, "主张")
            if claim["status"] != "已采纳":
                raise DomainError("只能挂接状态为“已采纳”的主张；竞争观点请在争议中呈现")
        sid = statement_id or self._new_id("stmt")
        record = {"id": sid, "topic_id": topic_id, "text": text, "kind": kind,
                  "certainty": certainty, "evidence_ids": ev_ids,
                  "cited_version_ids": ver_ids,
                  "adopted_claim_id": adopted_claim_id, "note": note,
                  "created_seq": len(self.events) + 1}
        self.statements[sid] = record
        topic["statement_ids"].append(sid)
        self._emit("statement.added", {"id": sid, "topic_id": topic_id,
                                       "kind": kind})
        return copy.deepcopy(record)

    def _contributors_for_versions(self, version_ids):
        out = []
        for c in self.contributions.values():
            if c["version_id"] in version_ids:
                person = self.people[c["person_id"]]
                out.append({**copy.deepcopy(c),
                            "person_name": person["name"],
                            "person_aliases": list(person["aliases"])})
        return out

    def _assets_permissions_for_evidence(self, evidence_ids):
        rows = []
        for eid in evidence_ids:
            ev = self.evidence[eid]
            if not ev.get("asset_id"):
                continue
            aid = ev["asset_id"]
            perms = [copy.deepcopy(p) for p in self.permissions.values()
                     if p["asset_id"] == aid]
            rows.append({"evidence_id": eid, "asset": copy.deepcopy(self.assets[aid]),
                         "permissions": perms})
        return rows

    def _lineage_among(self, version_ids):
        vset = set(version_ids)
        return [copy.deepcopy(l) for l in self.links.values()
                if l["source_version_id"] in vset
                and l["target_version_id"] in vset]

    def _controversies_touching(self, refs):
        wanted = {(r["type"], r["id"]) for r in refs}
        out = []
        for c in self.controversies.values():
            hit = any((r.get("type"), r.get("id")) in wanted
                      for r in c["subject_refs"])
            if hit:
                out.append(copy.deepcopy(c))
        return out

    def trace_statement(self, statement_id):
        """一句说明 → 文献版本、贡献者、证据、授权、竞争观点与历次争议的全链溯源。"""
        stmt = self._get(self.statements, statement_id, "说明")
        version_ids = list(stmt["cited_version_ids"])
        evidence_ids = list(stmt["evidence_ids"])

        adopted = None
        if stmt.get("adopted_claim_id"):
            adopted = copy.deepcopy(self.claims[stmt["adopted_claim_id"]])
            target = (adopted["subject"], adopted["work_id"],
                      adopted["version_id"])
        else:
            target = None

        competing = []
        claim_refs = []
        if adopted is not None:
            claim_refs.append({"type": "claim", "id": adopted["id"]})
            for claim in self.claims.values():
                if (claim["subject"], claim["work_id"], claim["version_id"]) == target:
                    competing.append(copy.deepcopy(claim))
                    if claim["id"] != adopted["id"]:
                        claim_refs.append({"type": "claim", "id": claim["id"]})
                    for eid in claim["evidence_ids"]:
                        if eid not in evidence_ids:
                            evidence_ids.append(eid)
                    if claim["version_id"] and claim["version_id"] not in version_ids:
                        version_ids.append(claim["version_id"])

        versions = []
        work_ids = set()
        for vid in version_ids:
            view = self.view_version(vid)
            versions.append(view)
            work_ids.add(view["work_id"])

        refs = ([{"type": "statement", "id": stmt["id"]}]
                + [{"type": "version", "id": vid} for vid in version_ids]
                + [{"type": "work", "id": wid} for wid in work_ids]
                + claim_refs)
        controversies = self._controversies_touching(refs)

        snapshots = [{"id": s["id"], "topic_id": s["topic_id"],
                      "edition": s["edition"], "published_on": s["published_on"]}
                     for s in self.snapshots.values()
                     if statement_id in s["frozen"]["statement_index"]]

        return {
            "statement": copy.deepcopy(stmt),
            "topic": {"id": stmt["topic_id"],
                      "title": self.topics[stmt["topic_id"]]["title"]},
            "versions": versions,
            "works": [copy.deepcopy(self.works[w]) for w in sorted(work_ids)],
            "contributors": self._contributors_for_versions(version_ids),
            "evidence": [copy.deepcopy(self.evidence[e]) for e in evidence_ids],
            "adopted_claim": adopted,
            "competing_claims": competing,
            "lineage": self._lineage_among(version_ids),
            "assets_and_permissions":
                self._assets_permissions_for_evidence(evidence_ids),
            "controversies": controversies,
            "snapshots": snapshots,
        }

    def publish_topic(self, topic_id, published_on=None, snapshot_id=None):
        """出版专题：校验全部结论性说明，并冻结快照。所引版本转入“已出版”终态。"""
        topic = self._get(self.topics, topic_id, "专题")
        if not topic["statement_ids"]:
            raise DomainError("空专题不能出版")
        for sid in topic["statement_ids"]:
            stmt = self.statements[sid]
            for vid in stmt["cited_version_ids"]:
                state = self.versions[vid]["state"]
                if state != "可采用":
                    raise DomainError(
                        f"说明“{sid}”引用的版本 {vid} 当前为“{state}”，"
                        "须进入“可采用”后方可出版")
            if stmt["kind"] in ("最早", "首部", "源自稿"):
                for eid in stmt["evidence_ids"]:
                    self._check_locatable(self.evidence[eid])

        frozen = self._freeze_topic(topic)
        edition = len(topic["editions"]) + 1
        snap_id = snapshot_id or f"snap_{topic_id}_{edition}"
        snapshot = {"id": snap_id, "topic_id": topic_id, "edition": edition,
                    "published_on": published_on or self._clock(),
                    "frozen": frozen}
        self.snapshots[snap_id] = snapshot
        topic["published"] = True
        topic["editions"].append(snap_id)
        for sid in topic["statement_ids"]:
            for vid in self.statements[sid]["cited_version_ids"]:
                if self.versions[vid]["state"] == "可采用":
                    self.versions[vid]["state"] = "已出版"
        self._emit("topic.published",
                   {"id": topic_id, "snapshot_id": snap_id, "edition": edition})
        return {"snapshot_id": snap_id, "edition": edition,
                "published_on": snapshot["published_on"]}

    def _freeze_topic(self, topic):
        statement_records = [copy.deepcopy(self.statements[sid])
                             for sid in topic["statement_ids"]]
        version_ids, evidence_ids, contrib_ids, claim_ids = set(), set(), set(), set()
        for st in statement_records:
            version_ids.update(st["cited_version_ids"])
            evidence_ids.update(st["evidence_ids"])
            if st["adopted_claim_id"]:
                claim_ids.add(st["adopted_claim_id"])
        for c in self.contributions.values():
            if c["version_id"] in version_ids:
                contrib_ids.add(c["id"])
                evidence_ids.update(c["evidence_ids"])
        work_ids = {self.versions[v]["work_id"] for v in version_ids}
        work_ids.update(topic["work_ids"])
        # 竞争主张一并入快照，保存“历次争议”的完整面貌
        for claim in self.claims.values():
            if claim["id"] in claim_ids:
                target = (claim["subject"], claim["work_id"], claim["version_id"])
                for other in self.claims.values():
                    if (other["subject"], other["work_id"],
                            other["version_id"]) == target:
                        claim_ids.add(other["id"])
                        evidence_ids.update(other["evidence_ids"])
                        if other["version_id"]:
                            version_ids.add(other["version_id"])
        asset_rows = self._assets_permissions_for_evidence(sorted(evidence_ids))
        refs = ([{"type": "statement", "id": s["id"]} for s in statement_records]
                + [{"type": "version", "id": v} for v in sorted(version_ids)]
                + [{"type": "work", "id": w} for w in sorted(work_ids)]
                + [{"type": "claim", "id": c} for c in sorted(claim_ids)])
        return {
            "topic": copy.deepcopy(topic),
            "statements": statement_records,
            "statement_index": {sid: sid for sid in topic["statement_ids"]},
            "works": {w: copy.deepcopy(self.works[w]) for w in sorted(work_ids)},
            "versions": {v: copy.deepcopy(self.versions[v])
                         for v in sorted(version_ids)},
            "version_supplements": {v: self.supplements_for("version", v)
                                    for v in sorted(version_ids)},
            "contributions": {c: copy.deepcopy(self.contributions[c])
                              for c in sorted(contrib_ids)},
            "people": {cid: copy.deepcopy(self.people[self.contributions[cid]["person_id"]])
                       for cid in sorted(contrib_ids)},
            "evidence": {e: copy.deepcopy(self.evidence[e])
                         for e in sorted(evidence_ids) if e in self.evidence},
            "claims": {c: copy.deepcopy(self.claims[c])
                       for c in sorted(claim_ids)},
            "lineage": self._lineage_among(sorted(version_ids)),
            "assets_and_permissions": asset_rows,
            "controversies": self._controversies_touching(refs),
            "frozen_at": self._clock(),
        }

    def restore_snapshot(self, snapshot_id):
        """复原某次出版时的冻结内容（不受其后追加的补充版本影响）。"""
        snap = self._get(self.snapshots, snapshot_id, "出版快照")
        return copy.deepcopy(snap)

    # ------------------------------------------------------------------ 读取

    def get_work(self, work_id):
        return copy.deepcopy(self._get(self.works, work_id, "作品"))

    def get_version(self, version_id):
        return copy.deepcopy(self._get(self.versions, version_id, "版本"))

    def get_topic(self, topic_id):
        return copy.deepcopy(self._get(self.topics, topic_id, "专题"))

    def list_events(self):
        return copy.deepcopy(self.events)
