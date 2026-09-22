"""历史文献传播谱系领域层。

围绕手稿、来稿、连载、单行本、合刊、译本、内部资料与公开本之间的
源流关系，提供编目、考证、授权、出版快照与溯源能力。所有结论必须
挂接可定位证据并标注确定程度；已出版专题只允许追加补充版本。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from itertools import count
from typing import Dict, List, Optional, Set, Tuple

from service import load_contract


class DomainError(ValueError):
    """违反领域规则时抛出。"""


class VersionType(str, Enum):
    MANUSCRIPT = "手稿"
    SUBMISSION = "来稿"
    SERIAL = "连载"
    MONOGRAPH = "单行本"
    OMNIBUS = "合刊"
    TRANSLATION = "译本"
    INTERNAL = "内部资料"
    OPEN_EDITION = "公开本"
    SUPPLEMENT = "补充版本"


class ClaimType(str, Enum):
    AUTHORSHIP = "作者身份"
    PSEUDONYM = "笔名归属"
    SOURCE_TEXT = "底本来源"
    PRIORITY = "最早或首部"
    SEGMENT_ORIGIN = "段落源流"


class Certainty(str, Enum):
    CONFIRMED = "确证"
    PROBABLE = "较大可能"
    DOUBTFUL = "存疑"
    DISPUTED = "争议中"


class RelationType(str, Enum):
    SERIALIZED_IN = "连载于"
    COMPILED_INTO = "汇编入"
    REISSUED_AS = "再版为"
    TRANSLATED_FROM = "译自"
    ABSORBED_SUBMISSION = "吸收来稿"
    REUSED_SEGMENT = "复用段落"
    SUPPLEMENTS = "补充订正"


class SupplementKind(str, Enum):
    BOOK_IMAGE = "新见书影"
    ATTRIBUTION = "署名考证"
    PAGE_CORRECTION = "页码订正"


class VersionStatus(str, Enum):
    UNCATAALOGUED = "待编目"
    RESEARCHING = "考证中"
    AWAITING_LICENSE = "待授权"
    ADOPTABLE = "可采用"
    PUBLISHED = "已出版"


# 版本状态只允许沿编目—考证—授权—采用—出版的方向流转；
# 出版后若再起争议，活记录可以回到考证中，快照不受影响。
_ALLOWED_TRANSITIONS: Dict[VersionStatus, Set[VersionStatus]] = {
    VersionStatus.UNCATAALOGUED: {VersionStatus.RESEARCHING},
    VersionStatus.RESEARCHING: {VersionStatus.AWAITING_LICENSE, VersionStatus.ADOPTABLE},
    VersionStatus.AWAITING_LICENSE: {VersionStatus.ADOPTABLE, VersionStatus.RESEARCHING},
    VersionStatus.ADOPTABLE: {VersionStatus.PUBLISHED, VersionStatus.RESEARCHING},
    VersionStatus.PUBLISHED: {VersionStatus.RESEARCHING},
}


@dataclass(frozen=True)
class Locator:
    """文献证据的物理或目录学定位。"""

    detail: str
    holding: Optional[str] = None          # 馆藏机构
    shelfmark: Optional[str] = None        # 索取号
    periodical: Optional[str] = None       # 刊物名称
    issue: Optional[str] = None            # 卷期
    pages: Optional[str] = None            # 页码
    scan_id: Optional[str] = None          # 书影或扫描件标识
    archive_code: Optional[str] = None     # 手稿或来稿档号

    def is_locateable(self) -> bool:
        return bool(
            self.detail.strip()
            and (
                (self.holding and self.shelfmark)
                or (self.periodical and self.issue and self.pages)
                or bool(self.scan_id)
                or bool(self.archive_code)
            )
        )

    def citation(self) -> str:
        head = self.detail.strip()
        parts = []
        if self.holding:
            parts.append(f"馆藏：{self.holding}" + (f"（{self.shelfmark}）" if self.shelfmark else ""))
        if self.periodical:
            parts.append(f"载《{self.periodical}》{self.issue or ''}" + (f"，第{self.pages}页" if self.pages else ""))
        if self.scan_id:
            parts.append(f"扫描件：{self.scan_id}")
        if self.archive_code:
            parts.append(f"档号：{self.archive_code}")
        return "；".join([head, *parts]) if parts else head


@dataclass(frozen=True)
class Contribution:
    """某一版本上的贡献者署名记录：真名、角色与当时署名（可能是笔名）。"""

    person: str
    role: str
    signed_as: Optional[str] = None


@dataclass
class Evidence:
    id: str
    locator: Locator
    form: str = "原件"
    note: str = ""


@dataclass
class PeriodicalIssue:
    id: str
    periodical: str
    volume: str
    issue: str
    pages: str
    published_on: Optional[date] = None

    def label(self) -> str:
        return f"《{self.periodical}》{self.volume}第{self.issue}期（第{self.pages}页）"


@dataclass
class MissingVolume:
    label: str
    basis: str
    evidence_id: str
    recorded_on: date
    recorded_by: str


@dataclass
class Work:
    id: str
    canonical_title: str
    aliases: List[str] = field(default_factory=list)
    gaps: List[MissingVolume] = field(default_factory=list)


@dataclass
class DocumentVersion:
    id: str
    work_id: str
    vtype: VersionType
    title: str
    language: str
    contributors: List[Contribution]
    issue_id: Optional[str] = None
    published_on: Optional[date] = None
    status: VersionStatus = VersionStatus.UNCATAALOGUED
    note: str = ""
    created_by: str = ""
    lost: bool = False


@dataclass
class Claim:
    """身份、笔名、底本、优先权等主张；无证据者只能登记为待考。"""

    id: str
    claim_type: ClaimType
    proposition: str
    claimant: str
    certainty: Certainty
    work_id: Optional[str]
    version_id: Optional[str]
    evidence_ids: List[str]
    grounded: bool
    raised_on: date


@dataclass
class Relation:
    id: str
    rel_type: RelationType
    source_id: str
    target_id: str
    portion: str = "整体"                 # 整体 / 段落
    segment_id: Optional[str] = None
    note: str = ""
    evidence_id: Optional[str] = None


@dataclass
class SegmentOccurrence:
    version_id: str
    pages: str
    note: str = ""


@dataclass
class Segment:
    """可跨书复用的文字段。"""

    id: str
    label: str
    excerpt: str
    occurrences: List[SegmentOccurrence] = field(default_factory=list)


@dataclass
class EditorialEvent:
    id: str
    kind: str
    on: date
    actor: str
    note: str
    version_id: Optional[str] = None
    work_id: Optional[str] = None
    evidence_ids: List[str] = field(default_factory=list)


@dataclass
class Dispute:
    id: str
    title: str
    work_id: Optional[str]
    claim_ids: List[str]
    opened_on: date
    opened_by: str
    status: str = "进行中"               # 进行中 / 有结论 / 存疑
    conclusion: str = ""
    resolved_on: Optional[date] = None


@dataclass
class Asset:
    """可用于展览或电子出版的素材（书影、扫描页等）。"""

    id: str
    version_id: str
    kind: str
    dpi: int
    owner: str
    note: str = ""


@dataclass(frozen=True)
class LicenseGrant:
    id: str
    asset_id: str
    granter: str
    regions: Tuple[str, ...]
    purposes: Tuple[str, ...]            # 展览 / 电子出版
    valid_from: date
    valid_until: date

    def valid_on(self, day: date) -> bool:
        return self.valid_from <= day <= self.valid_until


@dataclass
class ExportApplication:
    id: str
    purpose: str
    region: str
    required_dpi: int
    asset_ids: List[str]
    on: date
    checks: Dict[str, bool]
    reasons: List[str]

    @property
    def approved(self) -> bool:
        return all(self.checks.values())


@dataclass
class Statement:
    """专题中的一句事实说明。"""

    id: str
    text: str
    claim_ids: List[str] = field(default_factory=list)
    version_ids: List[str] = field(default_factory=list)
    asset_ids: List[str] = field(default_factory=list)
    extra_evidence_ids: List[str] = field(default_factory=list)


@dataclass
class Supplement:
    """出版后的追加记录：新见书影、署名考证或页码订正。"""

    id: str
    kind: SupplementKind
    on: date
    actor: str
    note: str
    evidence_ids: List[str] = field(default_factory=list)
    claim_id: Optional[str] = None
    version_id: Optional[str] = None
    correction: Optional[Dict[str, str]] = None


@dataclass
class Snapshot:
    id: str
    edition: int
    on: date
    published_by: str
    parent_snapshot_id: Optional[str]
    statements: List[dict] = field(default_factory=list)
    adopted_supplement_ids: List[str] = field(default_factory=list)


@dataclass
class Topic:
    id: str
    title: str
    status: str = "编辑中"                # 编辑中 / 已出版
    statements: List[Statement] = field(default_factory=list)
    supplements: List[Supplement] = field(default_factory=list)
    snapshots: List[Snapshot] = field(default_factory=list)


class Archive:
    """内存领域仓储，强制执行领域契约中的全部不变量。"""

    def __init__(self) -> None:
        self.contract = load_contract()
        self._check_contract_terms()

        self.works: Dict[str, Work] = {}
        self.issues: Dict[str, PeriodicalIssue] = {}
        self.versions: Dict[str, DocumentVersion] = {}
        self.evidences: Dict[str, Evidence] = {}
        self.claims: Dict[str, Claim] = {}
        self.relations: List[Relation] = []
        self.segments: Dict[str, Segment] = {}
        self.events: List[EditorialEvent] = []
        self.disputes: Dict[str, Dispute] = {}
        self.assets: Dict[str, Asset] = {}
        self.licenses: List[LicenseGrant] = []
        self.topics: Dict[str, Topic] = {}
        self._seq = count(1)

    # —— 基础工具 ----------------------------------------------------------

    def _check_contract_terms(self) -> None:
        c = self.contract
        assert {v.value for v in VersionType} <= set(c["version_types"])
        assert {v.value for v in ClaimType} <= set(c["claim_types"])
        assert {v.value for v in Certainty} <= set(c["certainty_levels"])
        assert {v.value for v in RelationType} <= set(c["relation_types"])
        assert {v.value for v in SupplementKind} <= set(c["supplement_kinds"])
        assert {s.value for s in VersionStatus} <= set(c["states"])

    def _next_id(self, prefix: str) -> str:
        return f"{prefix}-{next(self._seq):03d}"

    def _get_version(self, version_id: str) -> DocumentVersion:
        try:
            return self.versions[version_id]
        except KeyError:
            raise DomainError(f"未知文献版本：{version_id}") from None

    def _get_work(self, work_id: str) -> Work:
        try:
            return self.works[work_id]
        except KeyError:
            raise DomainError(f"未知作品：{work_id}") from None

    def _event(self, kind: str, on: date, actor: str, note: str,
               version_id: Optional[str] = None, work_id: Optional[str] = None,
               evidence_ids: Optional[List[str]] = None) -> EditorialEvent:
        event = EditorialEvent(
            id=self._next_id("EV"), kind=kind, on=on, actor=actor, note=note,
            version_id=version_id, work_id=work_id, evidence_ids=evidence_ids or [],
        )
        self.events.append(event)
        return event

    # —— 作品、异名与缺卷 --------------------------------------------------

    def register_work(self, canonical_title: str, aliases: Optional[List[str]] = None) -> Work:
        work = Work(id=self._next_id("W"), canonical_title=canonical_title)
        self.works[work.id] = work
        for alias in aliases or []:
            self.add_alias(work.id, alias)
        return work

    def add_alias(self, work_id: str, alias: str) -> None:
        work = self._get_work(work_id)
        alias = alias.strip()
        if not alias:
            raise DomainError("异名不能为空")
        if alias == work.canonical_title or alias in work.aliases:
            raise DomainError(f"异名已存在：{alias}")
        work.aliases.append(alias)

    def record_gap(self, work_id: str, label: str, basis: str,
                   evidence: Evidence, on: date, by: str) -> MissingVolume:
        work = self._get_work(work_id)
        gap = MissingVolume(label=label, basis=basis, evidence_id=evidence.id,
                            recorded_on=on, recorded_by=by)
        work.gaps.append(gap)
        self._event("缺卷登记", on, by, f"《{work.canonical_title}》{label}：{basis}",
                    work_id=work.id, evidence_ids=[evidence.id])
        return gap

    # —— 证据与刊物期次 ----------------------------------------------------

    def add_evidence(self, locator: Locator, form: str = "原件", note: str = "") -> Evidence:
        if not locator.is_locateable():
            raise DomainError("证据必须可定位：需馆藏索取号、刊物卷期页码、扫描件或档号之一")
        evidence = Evidence(id=self._next_id("E"), locator=locator, form=form, note=note)
        self.evidences[evidence.id] = evidence
        return evidence

    def register_issue(self, periodical: str, volume: str, issue: str, pages: str,
                       published_on: Optional[date] = None) -> PeriodicalIssue:
        record = PeriodicalIssue(
            id=self._next_id("I"), periodical=periodical, volume=volume, issue=issue,
            pages=pages, published_on=published_on,
        )
        self.issues[record.id] = record
        return record

    # —— 文献版本 ----------------------------------------------------------

    def register_version(self, work_id: str, vtype: VersionType, title: str, *,
                         contributors: List[Contribution], language: str = "中文",
                         issue_id: Optional[str] = None, published_on: Optional[date] = None,
                         note: str = "", created_by: str = "") -> DocumentVersion:
        self._get_work(work_id)
        if issue_id and issue_id not in self.issues:
            raise DomainError(f"未知刊物期次：{issue_id}")
        if not contributors:
            raise DomainError("文献版本必须至少登记一名贡献者")
        version = DocumentVersion(
            id=self._next_id("V"), work_id=work_id, vtype=vtype, title=title,
            language=language, contributors=list(contributors), issue_id=issue_id,
            published_on=published_on, note=note, created_by=created_by,
        )
        self.versions[version.id] = version
        self._event("编目", published_on or date.today(), created_by or "编目员",
                    f"登记{vtype.value}《{title}》", version_id=version.id, work_id=work_id)
        return version

    def transition_status(self, version_id: str, new_status: VersionStatus, by: str) -> None:
        version = self._get_version(version_id)
        if new_status not in _ALLOWED_TRANSITIONS[version.status]:
            raise DomainError(
                f"《{version.title}》不能从{version.status.value}转为{new_status.value}"
            )
        old = version.status
        version.status = new_status
        self._event("状态变更", date.today(), by,
                    f"《{version.title}》{old.value}→{new_status.value}",
                    version_id=version.id, work_id=version.work_id)

    def mark_lost(self, version_id: str, basis: str, evidence: Evidence,
                  on: date, by: str) -> None:
        version = self._get_version(version_id)
        if version.lost:
            raise DomainError(f"《{version.title}》已登记失佚")
        version.lost = True
        self._event("失佚登记", on, by, f"《{version.title}》失佚：{basis}",
                    version_id=version.id, work_id=version.work_id, evidence_ids=[evidence.id])

    def mark_rediscovered(self, version_id: str, evidence: Evidence, on: date, by: str) -> None:
        version = self._get_version(version_id)
        if not version.lost:
            raise DomainError(f"《{version.title}》并无失佚记录")
        version.lost = False
        self._event("重见", on, by,
                    f"《{version.title}》失而复见，以新版本另行著录前须保留失佚记录",
                    version_id=version.id, work_id=version.work_id, evidence_ids=[evidence.id])

    # —— 主张与争议 --------------------------------------------------------

    def add_claim(self, claim_type: ClaimType, proposition: str, claimant: str,
                  certainty: Certainty, evidence: List[Evidence], *,
                  work_id: Optional[str] = None, version_id: Optional[str] = None,
                  raised_on: Optional[date] = None) -> Claim:
        if not evidence:
            raise DomainError("源流或身份主张必须引用至少一条可定位证据；无证据请登记为待考")
        claim = Claim(
            id=self._next_id("C"), claim_type=claim_type, proposition=proposition,
            claimant=claimant, certainty=certainty, work_id=work_id, version_id=version_id,
            evidence_ids=[e.id for e in evidence], grounded=True,
            raised_on=raised_on or date.today(),
        )
        self.claims[claim.id] = claim
        return claim

    def register_conjecture(self, claim_type: ClaimType, proposition: str, claimant: str, *,
                            work_id: Optional[str] = None,
                            version_id: Optional[str] = None) -> Claim:
        """登记无证据的猜测：只能存为待考，不得被已出版专题采用。"""
        claim = Claim(
            id=self._next_id("C"), claim_type=claim_type, proposition=proposition,
            claimant=claimant, certainty=Certainty.DOUBTFUL, work_id=work_id,
            version_id=version_id, evidence_ids=[], grounded=False,
            raised_on=date.today(),
        )
        self.claims[claim.id] = claim
        return claim

    def open_dispute(self, title: str, claim_ids: List[str], opened_on: date,
                     opened_by: str, work_id: Optional[str] = None) -> Dispute:
        for cid in claim_ids:
            if cid not in self.claims:
                raise DomainError(f"未知主张：{cid}")
            claim = self.claims[cid]
            claim.certainty = Certainty.DISPUTED
        dispute = Dispute(
            id=self._next_id("D"), title=title, work_id=work_id, claim_ids=list(claim_ids),
            opened_on=opened_on, opened_by=opened_by,
        )
        self.disputes[dispute.id] = dispute
        return dispute

    def resolve_dispute(self, dispute_id: str, conclusion: str, on: date,
                        status: str = "有结论") -> Dispute:
        dispute = self.disputes[dispute_id]
        dispute.status = status
        dispute.conclusion = conclusion
        dispute.resolved_on = on
        return dispute

    # —— 版本关系 ----------------------------------------------------------

    def add_relation(self, rel_type: RelationType, source_id: str, target_id: str, *,
                     portion: str = "整体", segment_id: Optional[str] = None,
                     note: str = "", evidence: Optional[Evidence] = None) -> Relation:
        source = self._get_version(source_id)
        target = self._get_version(target_id)

        if rel_type is RelationType.TRANSLATED_FROM and source.vtype is not VersionType.TRANSLATION:
            raise DomainError("“译自”关系的起点必须是译本")
        if portion == "整体":
            for edge in self.relations:
                if (edge.source_id == source_id and edge.rel_type is rel_type
                        and edge.portion == "整体"):
                    raise DomainError(
                        f"《{source.title}》已登记整体{rel_type.value}关系；"
                        "多个底本须按段落分别标注"
                    )
        elif portion == "段落":
            if not note:
                raise DomainError("段落级源流关系必须注明对应篇章或范围")
        else:
            raise DomainError("关系范围只能是“整体”或“段落”")

        if rel_type is RelationType.ABSORBED_SUBMISSION and target.vtype is not VersionType.SUBMISSION:
            raise DomainError("“吸收来稿”的对象必须是来稿")
        if rel_type is RelationType.REUSED_SEGMENT:
            if not segment_id:
                raise DomainError("跨书复用必须指明文字段")
            segment = self.segments[segment_id]
            appeared = {o.version_id for o in segment.occurrences}
            if source_id not in appeared or target_id not in appeared:
                raise DomainError("复用关系双方版本都须先登记该段落的出现信息")

        relation = Relation(
            id=self._next_id("R"), rel_type=rel_type, source_id=source_id,
            target_id=target_id, portion=portion, segment_id=segment_id, note=note,
            evidence_id=evidence.id if evidence else None,
        )
        self.relations.append(relation)
        return relation

    def absorb_submissions(self, open_edition_id: str, submission_ids: List[str],
                           on: date, by: str, note: str = "") -> List[Relation]:
        """公开本批量吸收亲历者来稿，逐篇保留来源关系。"""
        edition = self._get_version(open_edition_id)
        if edition.vtype is not VersionType.OPEN_EDITION:
            raise DomainError("只有公开本可以登记吸收来稿")
        edges = []
        for sid in submission_ids:
            edges.append(self.add_relation(
                RelationType.ABSORBED_SUBMISSION, open_edition_id, sid,
                portion="段落", note="据来稿修订相应篇章",
            ))
        self._event("吸收来稿", on, by,
                    f"《{edition.title}》吸收{len(submission_ids)}篇亲历者来稿"
                    + (f"：{note}" if note else ""),
                    version_id=open_edition_id, work_id=edition.work_id)
        return edges

    # —— 文字段与跨书复用 --------------------------------------------------

    def register_segment(self, label: str, excerpt: str = "") -> Segment:
        segment = Segment(id=self._next_id("S"), label=label, excerpt=excerpt)
        self.segments[segment.id] = segment
        return segment

    def add_segment_occurrence(self, segment_id: str, version_id: str,
                               pages: str, note: str = "") -> None:
        self._get_version(version_id)
        self.segments[segment_id].occurrences.append(
            SegmentOccurrence(version_id=version_id, pages=pages, note=note)
        )

    # —— 素材、授权与导出核验 ----------------------------------------------

    def register_asset(self, version_id: str, kind: str, dpi: int,
                       owner: str, note: str = "") -> Asset:
        self._get_version(version_id)
        asset = Asset(id=self._next_id("A"), version_id=version_id, kind=kind,
                      dpi=dpi, owner=owner, note=note)
        self.assets[asset.id] = asset
        return asset

    def grant_license(self, asset_id: str, granter: str, regions: List[str],
                      purposes: List[str], valid_from: date, valid_until: date) -> LicenseGrant:
        if asset_id not in self.assets:
            raise DomainError(f"未知素材：{asset_id}")
        if valid_from > valid_until:
            raise DomainError("授权生效日不得晚于截止日")
        grant = LicenseGrant(
            id=self._next_id("L"), asset_id=asset_id, granter=granter,
            regions=tuple(regions), purposes=tuple(purposes),
            valid_from=valid_from, valid_until=valid_until,
        )
        self.licenses.append(grant)
        return grant

    def _valid_grants(self, asset_id: str, purpose: str, on: date) -> List[LicenseGrant]:
        return [
            g for g in self.licenses
            if g.asset_id == asset_id and g.valid_on(on) and purpose in g.purposes
        ]

    def apply_export(self, purpose: str, region: str, required_dpi: int,
                     asset_ids: List[str], on: date) -> ExportApplication:
        """三项核验：馆藏许可有效、清晰度达标、地域使用范围覆盖。"""
        if purpose not in {"展览", "电子出版"}:
            raise DomainError("导出用途只能是展览或电子出版")
        reasons: List[str] = []
        license_ok, clarity_ok, region_ok = True, True, True
        for aid in asset_ids:
            asset = self.assets.get(aid)
            if asset is None:
                raise DomainError(f"未知素材：{aid}")
            grants = self._valid_grants(aid, purpose, on)
            # 三项核验彼此独立，逐项给出驳回原因
            if not grants:
                license_ok = False
                reasons.append(f"素材{aid}（{asset.kind}）在{on.isoformat()}无适用于{purpose}的有效馆藏许可")
            else:
                if not any(region in g.regions for g in grants):
                    region_ok = False
                    covered = sorted({r for g in grants for r in g.regions})
                    reasons.append(f"素材{aid}授权地域{covered}不覆盖{region}")
            if asset.dpi < required_dpi:
                clarity_ok = False
                reasons.append(
                    f"素材{aid}清晰度为{asset.dpi}dpi，低于{purpose}要求的{required_dpi}dpi"
                )
        checks = {
            "馆藏许可有效": license_ok,
            "清晰度达标": clarity_ok,
            "地域使用范围覆盖": region_ok,
        }
        return ExportApplication(
            id=self._next_id("X"), purpose=purpose, region=region,
            required_dpi=required_dpi, asset_ids=list(asset_ids), on=on,
            checks=checks, reasons=reasons,
        )

    # —— 专题、说明与出版快照 ----------------------------------------------

    def create_topic(self, title: str) -> Topic:
        topic = Topic(id=self._next_id("T"), title=title)
        self.topics[topic.id] = topic
        return topic

    def add_statement(self, topic_id: str, text: str, *,
                      claim_ids: Optional[List[str]] = None,
                      version_ids: Optional[List[str]] = None,
                      asset_ids: Optional[List[str]] = None,
                      extra_evidence_ids: Optional[List[str]] = None) -> Statement:
        topic = self._topic(topic_id)
        if topic.status == "已出版":
            raise DomainError("专题已出版，不能修改说明；新发现请以补充版本追加")
        if not (claim_ids or []):
            raise DomainError(f"说明“{text}”必须挂接至少一条考证主张")
        if not (version_ids or []):
            raise DomainError(f"说明“{text}”必须挂接至少一个采用的文献版本")
        for vid in version_ids:
            version = self._get_version(vid)
            if version.status not in (VersionStatus.ADOPTABLE, VersionStatus.PUBLISHED):
                raise DomainError(f"《{version.title}》尚未达到可采用状态，不能写入专题")
        statement = Statement(
            id=self._next_id("ST"), text=text, claim_ids=list(claim_ids or []),
            version_ids=list(version_ids or []), asset_ids=list(asset_ids or []),
            extra_evidence_ids=list(extra_evidence_ids or []),
        )
        topic.statements.append(statement)
        return statement

    def _topic(self, topic_id: str) -> Topic:
        try:
            return self.topics[topic_id]
        except KeyError:
            raise DomainError(f"未知专题：{topic_id}") from None

    def _statement_view(self, statement: Statement, on: date) -> dict:
        """把一句说明解析为版本、主张、证据、贡献者、授权与争议。"""
        if not statement.version_ids:
            raise DomainError(f"说明“{statement.text}”未挂接任何文献版本")
        if not statement.claim_ids:
            raise DomainError(f"说明“{statement.text}”未挂接任何考证主张")

        versions = [self._get_version(v) for v in statement.version_ids]
        claims = [self.claims[c] for c in statement.claim_ids]
        for claim in claims:
            if not claim.grounded:
                raise DomainError(
                    f"说明“{statement.text}”采用了待考主张“{claim.proposition}”，无证据不得出版"
                )

        evidence_ids = {eid for c in claims for eid in c.evidence_ids}
        evidence_ids.update(statement.extra_evidence_ids)
        if not evidence_ids:
            raise DomainError(f"说明“{statement.text}”缺少可定位证据")

        contributors: Dict[Tuple[str, str], str] = {}
        for v in versions:
            for c in v.contributors:
                contributors[(c.person, c.role)] = c.signed_as or ""
        if not contributors:
            raise DomainError(f"说明“{statement.text}”回不到任何贡献者")

        license_rows = []
        for aid in statement.asset_ids:
            grants = [g for g in self.licenses
                      if g.asset_id == aid and g.valid_on(on)]
            if not grants:
                raise DomainError(f"说明“{statement.text}”所用素材{aid}在出版日无有效授权")
            for g in grants:
                license_rows.append({
                    "license_id": g.id, "asset_id": aid, "granter": g.granter,
                    "regions": list(g.regions), "purposes": list(g.purposes),
                    "valid_until": g.valid_until.isoformat(),
                })
        if not license_rows:
            raise DomainError(f"说明“{statement.text}”未挂接任何授权许可")

        work_ids = {v.work_id for v in versions}
        work_ids.update(c.work_id for c in claims if c.work_id)
        disputes = [
            d for d in self.disputes.values()
            if (d.work_id in work_ids) or set(d.claim_ids) & set(statement.claim_ids)
        ]

        return {
            "statement_id": statement.id,
            "text": statement.text,
            "versions": [
                {
                    "version_id": v.id, "type": v.vtype.value, "title": v.title,
                    "language": v.language,
                    "issue": self.issues[v.issue_id].label() if v.issue_id else None,
                    "contributors": [
                        {"person": c.person, "role": c.role,
                         "signed_as": c.signed_as}
                        for c in v.contributors
                    ],
                }
                for v in versions
            ],
            "claims": [
                {"claim_id": c.id, "type": c.claim_type.value,
                 "proposition": c.proposition, "claimant": c.claimant,
                 "certainty": c.certainty.value}
                for c in claims
            ],
            "evidence": [
                {"evidence_id": eid, "citation": self.evidences[eid].locator.citation()}
                for eid in sorted(evidence_ids)
            ],
            "licenses": license_rows,
            "disputes": [
                {"dispute_id": d.id, "title": d.title, "status": d.status,
                 "conclusion": d.conclusion}
                for d in disputes
            ],
        }

    def publish_topic(self, topic_id: str, on: date, by: str) -> Snapshot:
        topic = self._topic(topic_id)
        if not topic.statements:
            raise DomainError("空专题不能出版")
        frozen = [self._statement_view(st, on) for st in topic.statements]
        parent = topic.snapshots[-1].id if topic.snapshots else None
        adopted = [s.id for s in topic.supplements] if parent else []
        snapshot = Snapshot(
            id=self._next_id("SN"), edition=len(topic.snapshots) + 1, on=on,
            published_by=by, parent_snapshot_id=parent, statements=frozen,
            adopted_supplement_ids=adopted,
        )
        topic.snapshots.append(snapshot)
        topic.status = "已出版"
        for st in topic.statements:
            for vid in st.version_ids:
                version = self.versions[vid]
                if version.status is VersionStatus.ADOPTABLE:
                    version.status = VersionStatus.PUBLISHED
        return snapshot

    # —— 出版后的补充版本 --------------------------------------------------

    def _published(self, topic_id: str) -> Topic:
        topic = self._topic(topic_id)
        if topic.status != "已出版":
            raise DomainError("只有已出版专题才走补充版本流程")
        return topic

    def supplement_book_image(self, topic_id: str, referenced_version_id: str,
                              evidence: Evidence, dpi: int, on: date, by: str,
                              note: str = "") -> Supplement:
        """新见书影：以补充版本追加，并著录为素材。"""
        topic = self._published(topic_id)
        referenced = self._get_version(referenced_version_id)
        supplement_version = self.register_version(
            referenced.work_id, VersionType.SUPPLEMENT,
            f"《{referenced.title}》新见书影", contributors=[Contribution(by, "供图")],
            note=note, created_by=by,
        )
        self.register_asset(supplement_version.id, "书影", dpi, evidence.locator.holding or "馆藏机构")
        self.add_relation(RelationType.SUPPLEMENTS, supplement_version.id,
                          referenced_version_id, note=note or "新见书影", evidence=evidence)
        record = Supplement(
            id=self._next_id("SP"), kind=SupplementKind.BOOK_IMAGE, on=on, actor=by,
            note=note or f"《{referenced.title}》新见书影", evidence_ids=[evidence.id],
            version_id=supplement_version.id,
        )
        topic.supplements.append(record)
        return record

    def supplement_attribution(self, topic_id: str, claim_type: ClaimType,
                               proposition: str, claimant: str, certainty: Certainty,
                               evidence: Evidence, on: date, by: str,
                               work_id: Optional[str] = None,
                               version_id: Optional[str] = None,
                               note: str = "") -> Supplement:
        """署名考证：新增主张，与旧说并存，不改写已出版快照。"""
        topic = self._published(topic_id)
        claim = self.add_claim(claim_type, proposition, claimant, certainty, [evidence],
                               work_id=work_id, version_id=version_id, raised_on=on)
        record = Supplement(
            id=self._next_id("SP"), kind=SupplementKind.ATTRIBUTION, on=on, actor=by,
            note=note or proposition, evidence_ids=[evidence.id], claim_id=claim.id,
        )
        topic.supplements.append(record)
        return record

    def supplement_page_correction(self, topic_id: str, version_id: str,
                                   old_pages: str, new_pages: str,
                                   evidence: Evidence, on: date, by: str,
                                   note: str = "") -> Supplement:
        """页码订正：只追加订正记录，绝不改动版本原页码与旧快照。"""
        topic = self._published(topic_id)
        version = self._get_version(version_id)
        record = Supplement(
            id=self._next_id("SP"), kind=SupplementKind.PAGE_CORRECTION, on=on, actor=by,
            note=note or f"《{version.title}》页码由{old_pages}订正为{new_pages}",
            evidence_ids=[evidence.id], version_id=version_id,
            correction={"old_pages": old_pages, "new_pages": new_pages},
        )
        topic.supplements.append(record)
        self._event("页码订正", on, by, record.note, version_id=version_id,
                    work_id=version.work_id, evidence_ids=[evidence.id])
        return record

    def publish_new_edition(self, topic_id: str, on: date, by: str) -> Snapshot:
        """再版：冻结当下说明与已采纳补充，旧版快照仍可完整复原。"""
        topic = self._published(topic_id)
        frozen = [self._statement_view(st, on) for st in topic.statements]
        parent = topic.snapshots[-1].id
        snapshot = Snapshot(
            id=self._next_id("SN"), edition=len(topic.snapshots) + 1, on=on,
            published_by=by, parent_snapshot_id=parent, statements=frozen,
            adopted_supplement_ids=[s.id for s in topic.supplements],
        )
        topic.snapshots.append(snapshot)
        return snapshot

    # —— 溯源 --------------------------------------------------------------

    def trace_statement(self, snapshot_id: str, statement_id: str) -> dict:
        """从出版快照中的一句说明，回到版本、贡献者、证据、授权与争议。"""
        snapshot = self._snapshot(snapshot_id)
        for view in snapshot.statements:
            if view["statement_id"] == statement_id:
                return {
                    "snapshot_id": snapshot.id,
                    "edition": snapshot.edition,
                    "published_on": snapshot.on.isoformat(),
                    "adopted_supplements": snapshot.adopted_supplement_ids,
                    **view,
                }
        raise DomainError(f"快照{snapshot_id}中找不到说明{statement_id}")

    def _snapshot(self, snapshot_id: str) -> Snapshot:
        for topic in self.topics.values():
            for snapshot in topic.snapshots:
                if snapshot.id == snapshot_id:
                    return snapshot
        raise DomainError(f"未知出版快照：{snapshot_id}")

    def lineage(self, version_id: str) -> dict:
        """版本的完整源流：关系、编辑事件与相关争议。"""
        version = self._get_version(version_id)
        edges = [
            e for e in self.relations
            if e.source_id == version_id or e.target_id == version_id
        ]
        events = [e for e in self.events if e.version_id == version_id]
        claim_ids = [c.id for c in self.claims.values() if c.version_id == version_id]
        disputes = [d for d in self.disputes.values() if set(d.claim_ids) & set(claim_ids)]
        return {
            "version_id": version.id, "title": version.title, "type": version.vtype.value,
            "status": version.status.value, "lost": version.lost,
            "relations": [
                {
                    "relation_id": e.id, "type": e.rel_type.value,
                    "direction": "出" if e.source_id == version_id else "入",
                    "other_version_id": e.target_id if e.source_id == version_id else e.source_id,
                    "portion": e.portion, "segment_id": e.segment_id, "note": e.note,
                }
                for e in edges
            ],
            "events": [
                {"event_id": e.id, "kind": e.kind, "on": e.on.isoformat(),
                 "actor": e.actor, "note": e.note}
                for e in events
            ],
            "disputes": [
                {"dispute_id": d.id, "title": d.title, "status": d.status}
                for d in disputes
            ],
        }
