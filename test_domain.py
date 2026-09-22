"""以“长征早期文献专题”场景验证领域层规则。

场景线索：笔名连载、中文本一度失佚、译本对应多个底本、公开本吸收
两百余篇亲历者来稿、竞争性作者主张并存、跨书复用段落、出版后以补充
版本追加新见书影/署名考证/页码订正，以及导出素材的三项核验。
"""

import unittest
from datetime import date

from domain import (
    Archive,
    Certainty,
    ClaimType,
    Contribution,
    DomainError,
    Locator,
    RelationType,
    VersionStatus,
    VersionType,
)


def build_long_march_archive():
    """构造一个贴近专题编辑过程的完整存档。"""
    a = Archive()

    work = a.register_work("随军西行见闻录", aliases=["长征随军见闻", "西行见闻"])
    a.add_alias(work.id, "一个西方作者的中国纪事")

    issue = a.register_issue("全民月刊", "第1卷", "3", "12-48",
                             published_on=date(1936, 3, 1))
    ev_serial = a.add_evidence(Locator(
        detail="连载首页署名书影", scan_id="IMG-QMYK-v1n3-p12"))
    ev_shelf = a.add_evidence(Locator(
        detail="国图藏本", holding="中国国家图书馆", shelfmark="KM-1936-Q031"))

    # 手稿以笔名“廉臣”发表于连载
    manuscript = a.register_version(
        work.id, VersionType.MANUSCRIPT, "随军西行见闻录（手稿誊抄本）",
        contributors=[Contribution("某作者", "撰稿", signed_as="廉臣")],
        note="以笔名廉臣传世", created_by="编目员甲")
    serial = a.register_version(
        work.id, VersionType.SERIAL, "随军西行见闻录（连载）",
        contributors=[Contribution("某作者", "撰稿", signed_as="廉臣"),
                      Contribution("全民月刊社", "编辑")],
        issue_id=issue.id, published_on=date(1936, 3, 1), created_by="编目员甲")
    a.add_relation(RelationType.SERIALIZED_IN, manuscript.id, serial.id,
                   evidence=ev_serial)

    # 中文单行本一度失佚，后来重见
    mono_ev = a.add_evidence(Locator(
        detail="明月出版社1937年版版权页", holding="上海图书馆",
        shelfmark="SH-1937-MY-007", scan_id="IMG-MY-1937-colophon"))
    lost_ev = a.add_evidence(Locator(
        detail="1960年馆际核查记录", archive_code="NA-CAT-1960-221"))
    monograph = a.register_version(
        work.id, VersionType.MONOGRAPH, "随军西行见闻录（明月出版社本）",
        contributors=[Contribution("某作者", "撰稿", signed_as="廉臣")],
        published_on=date(1937, 1, 15), created_by="编目员甲")
    a.add_relation(RelationType.REISSUED_AS, serial.id, monograph.id,
                   evidence=mono_ev)
    a.transition_status(monograph.id, VersionStatus.RESEARCHING, "编目员甲")
    a.transition_status(monograph.id, VersionStatus.ADOPTABLE, "编目员甲")
    a.mark_lost(monograph.id, "历次馆藏核查未见传本", lost_ev,
                date(1960, 6, 1), "编目员乙")

    # 英文译本：整体译自连载，但若干章节另以单行本为底本（多底本）
    en_ev = a.add_evidence(Locator(
        detail="英译本译者序述及底本", holding="哈佛燕京图书馆",
        shelfmark="HY-1938-LM-112", scan_id="IMG-EN-1938-preface"))
    translation = a.register_version(
        work.id, VersionType.TRANSLATION, "Eyewitness on the Long March",
        contributors=[Contribution("某作者", "原著"),
                      Contribution("H. Smith", "翻译")],
        language="英文", published_on=date(1938, 6, 1), created_by="编目员丙")
    a.add_relation(RelationType.TRANSLATED_FROM, translation.id, serial.id,
                   portion="整体", note="主体据全民月刊连载译出", evidence=en_ev)

    # 内部资料本（1950年代校印）
    internal = a.register_version(
        work.id, VersionType.INTERNAL, "长征史料（内部参考·第三种）",
        contributors=[Contribution("史料编辑组", "编校")],
        published_on=date(1955, 9, 1), created_by="编目员乙")

    return a, {
        "work": work, "issue": issue, "manuscript": manuscript, "serial": serial,
        "monograph": monograph, "translation": translation, "internal": internal,
        "ev_serial": ev_serial, "ev_shelf": ev_shelf, "mono_ev": mono_ev,
        "lost_ev": lost_ev, "en_ev": en_ev,
    }


class WorkCatalogueTest(unittest.TestCase):
    def setUp(self):
        self.a, self.ctx = build_long_march_archive()

    def test_aliases_kept_individually(self):
        work = self.ctx["work"]
        self.assertIn("长征随军见闻", work.aliases)
        self.assertIn("一个西方作者的中国纪事", work.aliases)
        self.assertEqual(len(work.aliases), 3)
        with self.assertRaises(DomainError):
            self.a.add_alias(work.id, "随军西行见闻录")  # 与正名重复

    def test_gap_requires_basis_and_evidence(self):
        work = self.ctx["work"]
        gap_ev = self.a.add_evidence(Locator(
            detail="期刊总目核对单", archive_code="NA-CAT-1938-014"))
        gap = self.a.record_gap(work.id, "第2卷第4期", "总目著录而各家馆藏俱缺",
                                gap_ev, date(1985, 4, 1), "编目员乙")
        self.assertEqual(len(work.gaps), 1)
        self.assertEqual(gap.evidence_id, gap_ev.id)

    def test_evidence_must_be_locateable(self):
        with self.assertRaises(DomainError):
            self.a.add_evidence(Locator(detail="据说见过"))  # 无任何定位项

    def test_lost_and_rediscovered_history_preserved(self):
        mono = self.ctx["monograph"]
        self.assertTrue(mono.lost)
        re_ev = self.a.add_evidence(Locator(
            detail="重庆私人藏书现身书影", scan_id="IMG-REDISC-2005-01"))
        self.a.mark_rediscovered(mono.id, re_ev, date(2005, 10, 1), "考证人丁")
        self.assertFalse(mono.lost)
        lineage = self.a.lineage(mono.id)
        kinds = {e["kind"] for e in lineage["events"]}
        self.assertIn("失佚登记", kinds)
        self.assertIn("重见", kinds)
        with self.assertRaises(DomainError):
            self.a.mark_rediscovered(mono.id, re_ev, date(2006, 1, 1), "考证人丁")


class ClaimAndDisputeTest(unittest.TestCase):
    def setUp(self):
        self.a, self.ctx = build_long_march_archive()

    def test_competing_authorship_claims_coexist(self):
        serial = self.ctx["serial"]
        work = self.ctx["work"]
        e1 = self.a.add_evidence(Locator(
            detail="当事人回忆录指认", archive_code="ORAL-1984-07"))
        e2 = self.a.add_evidence(Locator(
            detail="笔名索引考释", holding="中央档案馆", shelfmark="ZY-WX-331-9"))

        c1 = self.a.add_claim(
            ClaimType.PSEUDONYM, "“廉臣”为陈云所作", "考证人丁",
            Certainty.PROBABLE, [e1], work_id=work.id, version_id=serial.id)
        c2 = self.a.add_claim(
            ClaimType.PSEUDONYM, "“廉臣”为另一位随军作者", "学者戊",
            Certainty.DOUBTFUL, [e2], work_id=work.id, version_id=serial.id)

        dispute = self.a.open_dispute("“廉臣”署名之争", [c1.id, c2.id],
                                      date(1995, 2, 1), "编辑己", work_id=work.id)
        self.assertEqual(c1.certainty, Certainty.DISPUTED)
        self.assertEqual(c2.certainty, Certainty.DISPUTED)
        self.assertEqual(len(dispute.claim_ids), 2)
        # 两说并存：新增主张不删除旧主张
        self.assertEqual(len(self.a.claims), 2)

        self.a.resolve_dispute(dispute.id, "维持并存，暂从较大可能说",
                               date(2010, 5, 1), status="存疑")
        self.assertEqual(dispute.status, "存疑")

    def test_priority_claim_requires_evidence_and_certainty(self):
        work = self.ctx["work"]
        with self.assertRaises(DomainError):
            self.a.add_claim(ClaimType.PRIORITY, "这是首部向世界介绍长征的作品",
                             "编辑己", Certainty.CONFIRMED, [], work_id=work.id)

    def test_conjecture_cannot_be_published(self):
        work = self.ctx["work"]
        guess = self.a.register_conjecture(
            ClaimType.AUTHORSHIP, "手稿可能出自外国传教士", "网友庚",
            work_id=work.id)
        self.assertFalse(guess.grounded)
        topic = self.a.create_topic("长征早期文献专题")
        with self.assertRaises(DomainError):
            self.a.add_statement(
                topic.id, "手稿出自外国传教士之手。",
                claim_ids=[guess.id], version_ids=[self.ctx["manuscript"].id],
                asset_ids=[])


class VersionRelationTest(unittest.TestCase):
    def setUp(self):
        self.a, self.ctx = build_long_march_archive()

    def test_translation_can_have_multiple_sources_by_portion(self):
        tr, serial, mono = self.ctx["translation"], self.ctx["serial"], self.ctx["monograph"]
        en_ev2 = self.a.add_evidence(Locator(
            detail="第三章译文与明月本互校记录", scan_id="IMG-EN-1938-ch3-note"))
        # 重见后才能引用单行本作为逐段底本
        re_ev = self.a.add_evidence(Locator(
            detail="重庆私人藏书现身书影", scan_id="IMG-REDISC-2005-01"))
        self.a.mark_rediscovered(mono.id, re_ev, date(2005, 10, 1), "考证人丁")
        edge = self.a.add_relation(
            RelationType.TRANSLATED_FROM, tr.id, mono.id, portion="段落",
            note="第三章“过雪山”据明月出版社单行本补译", evidence=en_ev2)

        rels = [r for r in self.a.relations
                if r.source_id == tr.id and r.rel_type is RelationType.TRANSLATED_FROM]
        self.assertEqual(len(rels), 2)
        self.assertEqual({r.target_id for r in rels}, {serial.id, mono.id})
        self.assertEqual(edge.portion, "段落")

        # 段落级关系不注明范围则拒绝
        with self.assertRaises(DomainError):
            self.a.add_relation(RelationType.TRANSLATED_FROM, tr.id, mono.id,
                                portion="段落")

    def test_only_translation_can_be_translated_from(self):
        with self.assertRaises(DomainError):
            self.a.add_relation(RelationType.TRANSLATED_FROM,
                                self.ctx["serial"].id, self.ctx["manuscript"].id)

    def test_open_edition_absorbs_submissions(self):
        work = self.ctx["work"]
        edition = self.a.register_version(
            work.id, VersionType.OPEN_EDITION, "长征亲历者说（公开本）",
            contributors=[Contribution("出版社编委会", "主编")],
            published_on=date(2016, 9, 1))
        submissions = []
        for i in range(212):
            ev = self.a.add_evidence(Locator(
                detail=f"亲历者来稿第{i + 1:03d}号",
                archive_code=f"SUB-2014-{i + 1:04d}"), form="来稿原件")
            sub = self.a.register_version(
                work.id, VersionType.SUBMISSION, f"亲历者来稿{i + 1:03d}",
                contributors=[Contribution(f"亲历者{i + 1:03d}", "口述/撰稿")],
                created_by="资料组")
            submissions.append(sub)
        edges = self.a.absorb_submissions(edition.id, [s.id for s in submissions],
                                          date(2015, 12, 1), "编辑己",
                                          note="据来稿订正路线与日期")
        self.assertEqual(len(edges), 212)
        with self.assertRaises(DomainError):
            self.a.absorb_submissions(self.ctx["internal"].id,
                                      [submissions[0].id], date(2015, 12, 1), "编辑己")

    def test_segment_reuse_across_books(self):
        seg = self.a.register_segment("飞夺泸定桥一段", excerpt="二十二名突击队员……")
        mono, internal = self.ctx["monograph"], self.ctx["internal"]
        self.a.add_segment_occurrence(seg.id, mono.id, "31-32", note="明月本原段落")
        self.a.add_segment_occurrence(seg.id, internal.id, "88-89", note="内部资料转录")
        seg_ev = self.a.add_evidence(Locator(
            detail="两书段落对勘表", scan_id="IMG-COLLATE-SEG-09"))
        edge = self.a.add_relation(
            RelationType.REUSED_SEGMENT, internal.id, mono.id, portion="段落",
            segment_id=seg.id, note="内部资料整段复用明月本", evidence=seg_ev)
        self.assertEqual(edge.segment_id, seg.id)
        # 未登记段落出现的版本不能建立复用关系
        other_work = self.a.register_work("另一本书")
        other = self.a.register_version(
            other_work.id, VersionType.MONOGRAPH, "另一本书（初版）",
            contributors=[Contribution("某人", "著")])
        with self.assertRaises(DomainError):
            self.a.add_relation(RelationType.REUSED_SEGMENT, other.id, mono.id,
                                portion="段落", segment_id=seg.id, note="查无实据的复用")


class PublishingSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.a, self.ctx = build_long_march_archive()
        work = self.ctx["work"]
        serial = self.ctx["serial"]
        self.a.transition_status(serial.id, VersionStatus.RESEARCHING, "编目员甲")
        self.a.transition_status(serial.id, VersionStatus.ADOPTABLE, "编目员甲")

        claim_ev = self.a.add_evidence(Locator(
            detail="1936年3月1日刊期版权记录", scan_id="IMG-QMYK-colophon"))
        self.claim = self.a.add_claim(
            ClaimType.PRIORITY,
            "1936年3月连载是最早以作者亲身经历向外界系统介绍长征的文字之一",
            "考证人丁", Certainty.PROBABLE, [claim_ev, self.ctx["ev_serial"]],
            work_id=work.id, version_id=serial.id)
        dispute = self.a.open_dispute("“最早介绍长征”之争", [self.claim.id],
                                      date(2009, 7, 1), "编辑己", work_id=work.id)
        self.a.resolve_dispute(dispute.id, "限定为“之一”，维持较大可能",
                               date(2012, 3, 1))

        asset_ev = self.a.add_evidence(Locator(
            detail="连载首页高清书影", scan_id="IMG-QMYK-v1n3-p12-HD"))
        self.asset = self.a.register_asset(serial.id, "连载首页书影", 300,
                                           owner="中国国家图书馆")
        self.grant = self.a.grant_license(
            self.asset.id, "中国国家图书馆", ["中国大陆"], ["展览", "电子出版"],
            date(2020, 1, 1), date(2030, 12, 31))

        self.topic = self.a.create_topic("长征早期文献专题")
        self.statement = self.a.add_statement(
            self.topic.id,
            "该作1936年3月以笔名“廉臣”在《全民月刊》连载，是最早系统介绍长征的文字之一。",
            claim_ids=[self.claim.id], version_ids=[serial.id],
            asset_ids=[self.asset.id])
        self.snapshot = self.a.publish_topic(self.topic.id, date(2021, 6, 1), "出版审核人辛")

    def test_snapshot_is_frozen(self):
        original = self.snapshot.statements[0]
        original_text = original["text"]
        original_claims = len(original["claims"])

        # 出版后不能再改说明
        with self.assertRaises(DomainError):
            self.a.add_statement(self.topic.id, "试图追加一句")

        # 后续新考证（新主张、争议变化）不影响旧快照内容
        new_ev = self.a.add_evidence(Locator(
            detail="新发现1935年外文通讯", scan_id="IMG-CF-1935-11"))
        self.a.supplement_attribution(
            self.topic.id, ClaimType.PRIORITY,
            "1935年11月已有外电长篇报道，'最早之一'的措辞需收紧",
            "学者壬", Certainty.CONFIRMED, new_ev, date(2023, 4, 1), "考证人丁",
            work_id=self.ctx["work"].id, note="新见外文报道")

        old = self.a.trace_statement(self.snapshot.id, self.statement.id)
        self.assertEqual(old["text"], original_text)
        self.assertEqual(len(old["claims"]), original_claims)
        self.assertEqual(old["edition"], 1)

    def test_supplements_append_only_three_kinds(self):
        serial = self.ctx["serial"]
        mono = self.ctx["monograph"]
        re_ev = self.a.add_evidence(Locator(
            detail="重庆私人藏书现身书影", scan_id="IMG-REDISC-2005-01"))
        self.a.mark_rediscovered(mono.id, re_ev, date(2005, 10, 1), "考证人丁")

        # 1) 新见书影
        img_ev = self.a.add_evidence(Locator(
            detail="明月本封面书影", holding="重庆民间收藏",
            shelfmark="PRIVATE-CQ-2024-01", scan_id="IMG-MY-COVER-2024"))
        sup_img = self.a.supplement_book_image(
            self.topic.id, mono.id, img_ev, dpi=400, on=date(2024, 2, 1),
            by="馆藏机构", note="明月出版社本封面")

        # 2) 署名考证（与旧说并存）
        attr_ev = self.a.add_evidence(Locator(
            detail="手稿笔迹鉴定书", archive_code="FS-JD-2024-08"))
        sup_attr = self.a.supplement_attribution(
            self.topic.id, ClaimType.AUTHORSHIP, "笔迹鉴定支持手稿为本人亲笔",
            "鉴定中心癸", Certainty.CONFIRMED, attr_ev, date(2024, 5, 1),
            "考证人丁", work_id=self.ctx["work"].id, version_id=self.ctx["manuscript"].id)

        # 3) 页码订正：旧快照页码不变，订正另存
        old_citation = self.snapshot.statements[0]["evidence"][0]["citation"]
        pg_ev = self.a.add_evidence(Locator(
            detail="原刊重新描记页码", scan_id="IMG-QMYK-pagerecheck"))
        sup_page = self.a.supplement_page_correction(
            self.topic.id, serial.id, "12-48", "13-49", pg_ev,
            date(2024, 8, 1), "编目员甲")

        self.assertEqual(len(self.topic.supplements), 3)
        self.assertEqual(sup_page.correction, {"old_pages": "12-48", "new_pages": "13-49"})
        # 旧快照中的引用文字保持原样
        self.assertEqual(
            self.a.trace_statement(self.snapshot.id, self.statement.id)["evidence"][0]["citation"],
            old_citation)

        # 新快照引用全部补充
        second = self.a.publish_new_edition(self.topic.id, date(2025, 1, 1), "出版审核人辛")
        self.assertEqual(second.edition, 2)
        self.assertEqual(second.parent_snapshot_id, self.snapshot.id)
        self.assertEqual(set(second.adopted_supplement_ids),
                         {sup_img.id, sup_attr.id, sup_page.id})
        # 第一版仍可完整复原
        self.assertEqual(len(self.a.trace_statement(self.snapshot.id,
                                                    self.statement.id)["versions"]), 1)

    def test_supplement_requires_published_topic(self):
        draft = self.a.create_topic("未出版专题")
        ev = self.a.add_evidence(Locator(detail="x", scan_id="IMG-X-1"))
        with self.assertRaises(DomainError):
            draft_topic = self.a.topics[draft.id]
            draft_topic.supplements  # 仅取属性
            self.a.supplement_book_image(draft.id, self.ctx["serial"].id, ev,
                                         300, date(2024, 1, 1), "馆藏机构")

    def test_statement_must_carry_versions_and_license(self):
        t = self.a.create_topic("缺要素专题")
        with self.assertRaises(DomainError):
            self.a.add_statement(t.id, "只有主张没有版本。",
                                 claim_ids=[self.claim.id], version_ids=[])
        st = self.a.add_statement(t.id, "有版本主张但无素材。",
                                  claim_ids=[self.claim.id],
                                  version_ids=[self.ctx["serial"].id])
        with self.assertRaises(DomainError):
            self.a.publish_topic(t.id, date(2021, 6, 1), "出版审核人辛")


class ExportGateTest(unittest.TestCase):
    def setUp(self):
        self.a, self.ctx = build_long_march_archive()
        serial = self.ctx["serial"]
        self.hd = self.a.register_asset(serial.id, "高清书影", 400, "中国国家图书馆")
        self.low = self.a.register_asset(serial.id, "低清缩略图", 96, "某省馆")
        self.a.grant_license(self.hd.id, "中国国家图书馆", ["中国大陆"],
                             ["展览", "电子出版"], date(2020, 1, 1), date(2030, 12, 31))
        self.a.grant_license(self.low.id, "某省馆", ["中国大陆"],
                             ["展览"], date(2020, 1, 1), date(2030, 12, 31))

    def test_export_passes_all_three_checks(self):
        app = self.a.apply_export("电子出版", "中国大陆", 300,
                                  [self.hd.id], date(2024, 1, 1))
        self.assertTrue(app.approved)
        self.assertEqual(set(app.checks), {"馆藏许可有效", "清晰度达标", "地域使用范围覆盖"})
        self.assertTrue(all(app.checks.values()))

    def test_region_out_of_scope_rejected(self):
        app = self.a.apply_export("展览", "欧洲", 300, [self.hd.id], date(2024, 1, 1))
        self.assertFalse(app.approved)
        self.assertTrue(app.checks["馆藏许可有效"])
        self.assertFalse(app.checks["地域使用范围覆盖"])
        self.assertTrue(any("地域" in r for r in app.reasons))

    def test_low_clarity_rejected(self):
        app = self.a.apply_export("电子出版", "中国大陆", 300, [self.low.id],
                                  date(2024, 1, 1))
        # 低清图同时缺电子出版授权且清晰度不足
        self.assertFalse(app.checks["清晰度达标"])
        self.assertFalse(app.checks["馆藏许可有效"])
        self.assertFalse(app.approved)

    def test_expired_license_rejected(self):
        app = self.a.apply_export("展览", "中国大陆", 300, [self.hd.id],
                                  date(2031, 6, 1))
        self.assertFalse(app.checks["馆藏许可有效"])
        self.assertFalse(app.approved)


class TraceabilityTest(unittest.TestCase):
    def setUp(self):
        self.a, self.ctx = build_long_march_archive()
        serial = self.ctx["serial"]
        self.a.transition_status(serial.id, VersionStatus.RESEARCHING, "编目员甲")
        self.a.transition_status(serial.id, VersionStatus.ADOPTABLE, "编目员甲")
        ev = self.a.add_evidence(Locator(
            detail="连载全份及署名", scan_id="IMG-QMYK-FULL"))
        self.claim = self.a.add_claim(
            ClaimType.PSEUDONYM, "“廉臣”即该随军作者", "考证人丁",
            Certainty.PROBABLE, [ev], work_id=self.ctx["work"].id, version_id=serial.id)
        dispute = self.a.open_dispute("廉臣署名之争", [self.claim.id],
                                      date(2009, 1, 1), "编辑己",
                                      work_id=self.ctx["work"].id)
        self.a.resolve_dispute(dispute.id, "并存待考", date(2015, 1, 1), status="存疑")
        self.asset = self.a.register_asset(serial.id, "书影", 300, "中国国家图书馆")
        self.a.grant_license(self.asset.id, "中国国家图书馆", ["中国大陆"],
                             ["展览"], date(2020, 1, 1), date(2030, 12, 31))
        self.topic = self.a.create_topic("长征早期文献专题")
        self.st = self.a.add_statement(
            self.topic.id, "连载署名“廉臣”。", claim_ids=[self.claim.id],
            version_ids=[serial.id], asset_ids=[self.asset.id])
        self.snapshot = self.a.publish_topic(self.topic.id, date(2022, 7, 1), "出版审核人辛")

    def test_one_sentence_traces_to_everything(self):
        trace = self.a.trace_statement(self.snapshot.id, self.st.id)

        # 回到采用的文献版本
        version = trace["versions"][0]
        self.assertEqual(version["type"], "连载")
        self.assertIn("全民月刊", version["issue"])

        # 回到贡献者与笔名
        signed = {(c["person"], c["signed_as"]) for c in version["contributors"]}
        self.assertIn(("某作者", "廉臣"), signed)

        # 回到证据
        self.assertTrue(trace["evidence"])
        self.assertTrue(any("IMG-QMYK-FULL" in e["citation"] for e in trace["evidence"]))

        # 回到授权
        self.assertEqual(trace["licenses"][0]["granter"], "中国国家图书馆")

        # 回到历次争议
        self.assertEqual(trace["disputes"][0]["title"], "廉臣署名之争")
        self.assertEqual(trace["disputes"][0]["status"], "存疑")

        # 主张带确定程度
        self.assertEqual(trace["claims"][0]["certainty"], "争议中")


class ContractConsistencyTest(unittest.TestCase):
    def test_contract_terms_cover_domain_enums(self):
        archive = Archive()
        contract = archive.contract
        for key in ("entities", "version_types", "claim_types", "certainty_levels",
                    "relation_types", "supplement_kinds", "policies"):
            self.assertIn(key, contract)
        self.assertGreaterEqual(len(contract["invariants"]), 7)


if __name__ == "__main__":
    unittest.main()
