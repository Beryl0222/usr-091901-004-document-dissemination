"""领域场景测试：以长征早期文献专题的典型传播史为脚本。"""

import unittest

from domain import (DocumentLineage, DomainError, NotFound,
                    DERIVED_TO_SOURCE)

TODAY = "2026-09-22"


def new_domain():
    return DocumentLineage(clock=lambda: TODAY)


class LongMarchTopicTest(unittest.TestCase):
    def setUp(self):
        self.d = new_domain()

    # ------------------------------------------------------------------ 基础建档

    def _build_work_one(self):
        """《随军西行见闻录》：异名、笔名、连载、手稿、多底本译本。"""
        d = self.d
        work = d.create_work(
            "随军西行见闻录", alt_titles=["从福建到陕西", "随军目击记"])
        chen = d.register_person("陈云", aliases=["廉臣"])
        other = d.register_person("疑似外籍军医", aliases=[])

        serial = d.create_version(
            work["id"], "连载", "《见闻录》报刊连载",
            publication="海外救国报刊", issue="第1-4期", pages="3-46")
        manuscript = d.create_version(
            work["id"], "手稿", "《见闻录》作者手稿（一度失佚，后由档案渠道发现）")
        pamphlet = d.create_version(
            work["id"], "单行本", "国内单行本（中文版一度失佚）")
        translation = d.create_version(
            work["id"], "译本", "《见闻录》英译本", language="英语")
        return (work, chen, other, serial, manuscript, pamphlet, translation)

    def test_alt_titles_and_pen_name_contribution(self):
        d = self.d
        work, chen, _, serial, *_ = self._build_work_one()
        self.assertEqual(work["alt_titles"][0], "从福建到陕西")

        ev_serial = d.add_evidence(
            "刊物期次", "海外救国报刊1936年连载第3期",
            {"container": "海外救国报刊", "issue": "第3期", "page": "12"},
            certainty="确证")
        contrib = d.add_contribution(
            serial["id"], chen["id"], "署名", signed_name="廉臣",
            evidence_ids=[ev_serial["id"]])
        self.assertEqual(contrib["signed_name"], "廉臣")

        # 未登记为别名的署名不得直接归集到该人
        with self.assertRaises(DomainError):
            d.add_contribution(
                serial["id"], chen["id"], "执笔", signed_name="陌生人甲",
                evidence_ids=[ev_serial["id"]])

    def test_evidence_must_be_locatable(self):
        d = self.d
        with self.assertRaises(DomainError):
            d.add_evidence("书影", "只写了出处但没有任何定位", {})
        with self.assertRaises(DomainError):
            d.add_evidence("书影", "", {"page": "1"})
        # 有索取号即可定位
        ev = d.add_evidence(
            "档案记录", "某档案馆藏件", {"shelfmark": "甲-1-2"})
        self.assertIn("shelfmark", ev["locator"])

    # ----------------------------------------------------- 作者身份：竞争主张并存

    def test_competing_authorship_claims_coexist_and_adoption_rules(self):
        d = self.d
        work, chen, other, serial, *_ = self._build_work_one()
        ev_serial = d.add_evidence(
            "刊物期次", "报刊连载署名廉臣",
            {"issue": "第3期", "page": "12"}, certainty="确证")
        ev_paper = d.add_evidence(
            "档案记录", "延安时期组织部门作者情况说明",
            {"shelfmark": "档-88-7"}, certainty="确证")
        ev_hearsay = d.add_evidence(
            "署名著录", "后人转述的署名印象",
            {"container": "某回忆文集", "page": "201"}, certainty="存疑")

        claim_chen = d.add_claim(
            "版本署名", chen["id"], "廉臣是陈云的笔名",
            [ev_serial["id"]], certainty="推定", version_id=serial["id"])
        claim_other = d.add_claim(
            "版本署名", other["id"], "廉臣是被红军俘虏的外籍军医",
            [ev_hearsay["id"]], certainty="存疑", version_id=serial["id"])

        # 没有确证级证据的主张不能采纳
        with self.assertRaises(DomainError):
            d.adopt_claim(claim_other["id"])

        d.adopt_claim(claim_chen["id"])
        # 异说仍在，只是未采纳
        self.assertEqual(d.claims[claim_other["id"]]["status"], "候选")

        # 更强证据（两条确证）出现后可取代旧采纳结论，旧结论转为“曾采纳”
        stronger = d.add_claim(
            "版本署名", chen["id"], "据档案与连载双重证据，廉臣即陈云",
            [ev_serial["id"], ev_paper["id"]], certainty="确证",
            version_id=serial["id"])
        d.adopt_claim(stronger["id"])
        self.assertEqual(d.claims[claim_chen["id"]]["status"], "曾采纳")
        self.assertEqual(d.claims[stronger["id"]]["status"], "已采纳")

        # 证据不占优时不能覆盖
        weak_new = d.add_claim(
            "版本署名", other["id"], "仅一条确证的异说不能覆盖两条确证",
            [ev_paper["id"]], certainty="推定", version_id=serial["id"])
        with self.assertRaises(DomainError):
            d.adopt_claim(weak_new["id"])

    # ----------------------------------------------------------- 多底本与谱系

    def test_translation_with_multiple_base_versions(self):
        d = self.d
        work, _, _, serial, manuscript, pamphlet, translation = \
            self._build_work_one()
        ev_a = d.add_evidence(
            "刊物期次", "英译本与连载文字对勘",
            {"issue": "第1期", "page": "5"}, certainty="确证")
        ev_b = d.add_evidence(
            "手稿影像", "英译本独有序言见于手稿",
            {"shelfmark": "稿-9"}, certainty="确证")

        # 一个译本对应两个底本，关系分别登记、各附证据
        d.add_link("译自", translation["id"], serial["id"], [ev_a["id"]])
        d.add_link("译自", translation["id"], manuscript["id"], [ev_b["id"]])
        self.assertIn("译本 → 底本", DERIVED_TO_SOURCE["译自"])

        # 再版自：后出单行本源自连载
        d.add_link("再版自", pamphlet["id"], serial["id"], [ev_a["id"]])

        graph = d.traverse_lineage(translation["id"])
        related = {r["other_version_id"]: r["direction"]
                   for node in graph["nodes"] for r in node["relations"]}
        self.assertEqual(related[serial["id"]], "derived_to_source")
        self.assertEqual(related[manuscript["id"]], "derived_to_source")

        # 无证据的谱系关系不予登记
        with self.assertRaises(DomainError):
            d.add_link("译自", translation["id"], pamphlet["id"], [])

    def test_alt_title_missing_volume_and_cycle_warning(self):
        d = self.d
        work, _, _, serial, manuscript, *_ = self._build_work_one()
        ev = d.add_evidence(
            "档案记录", "馆藏目录标注缺卷", {"shelfmark": "目-2"})
        d.register_missing_volume(
            work["id"], position="第3卷", reason="战争环境中散佚",
            evidence_ids=[ev["id"]])
        graph = d.traverse_lineage(serial["id"])
        self.assertTrue(any("缺卷" in w for w in graph["warnings"]))

        # 缺卷登记也必须有证据
        with self.assertRaises(DomainError):
            d.register_missing_volume(work["id"], "第4卷", "无著录")

    # ----------------------------------------------- 两百多篇亲历者来稿与结集

    def test_public_edition_absorbs_over_two_hundred_submissions(self):
        d = self.d
        work = d.create_work("红军长征记", alt_titles=["二万五千里"])
        editor = d.register_person("编委会")
        ev_call = d.add_evidence(
            "亲历者来稿", "征稿启事与编辑说明",
            {"container": "征稿档案", "page": "1"}, certainty="确证")

        submissions = [
            d.create_version(work["id"], "来稿", f"亲历者来稿第{i:03d}篇")
            for i in range(1, 206)]
        self.assertEqual(len(submissions), 205)

        public = d.create_version(
            work["id"], "单行本", "《红军长征记》公开整理本", pages="1-412")
        # 公开本逐篇吸收来稿：205 条“源自稿”关系，证据可复用
        for sub in submissions:
            d.add_link("源自稿", public["id"], sub["id"], [ev_call["id"]])
        source_links = [l for l in d.links.values()
                        if l["relation"] == "源自稿"
                        and l["source_version_id"] == public["id"]]
        self.assertEqual(len(source_links), 205)

        # 结集连载关系示例：某段曾先在刊物连载
        digest = d.create_version(
            work["id"], "连载", "《二万五千里》报刊摘载", issue="第7期")
        d.add_link("连载为", public["id"], digest["id"], [ev_call["id"]])

    # ----------------------------------------------------------- 跨书文字复用

    def test_fragment_reused_across_books(self):
        d = self.d
        w1 = d.create_work("随军西行见闻录")
        w2 = d.create_work("红军长征记")
        v1 = d.create_version(w1["id"], "连载", "见闻录连载", issue="第2期")
        v2 = d.create_version(w2["id"], "单行本", "红军长征记公开本")
        frag = d.create_fragment("关于遵义城防的同一段描写", excerpt="……")
        d.register_fragment_use(frag["id"], v1["id"], pages="18")
        d.register_fragment_use(frag["id"], v2["id"], pages="96")
        reuse = d.fragment_reuse(frag["id"])
        self.assertEqual(len(reuse), 2)
        self.assertEqual({r["work_title"] for r in reuse},
                         {"随军西行见闻录", "红军长征记"})

    # --------------------------------------- 补充版本只追加，快照不被悄悄改写

    def test_supplements_append_and_published_snapshot_is_immutable(self):
        d = self.d
        work = d.create_work("遵义会议文献")
        author = d.register_person("某亲历者")
        ver = d.create_version(
            work["id"], "内部资料", "传达提纲油印本", pages="33")
        ev_old = d.add_evidence(
            "页码著录", "旧目录著录页码", {"page": "33"}, certainty="推定")
        d.add_contribution(ver["id"], author["id"], "执笔",
                           evidence_ids=[ev_old["id"]])
        d.transition_version(ver["id"], "考证中")
        d.transition_version(ver["id"], "待授权")
        d.transition_version(ver["id"], "可采用")

        topic = d.create_topic("长征早期文献专题", work_ids=[work["id"]])
        d.add_statement(
            topic["id"],
            "该油印本是目前所见最早的遵义会议传达文献。",
            kind="最早", certainty="推定", evidence_ids=[ev_old["id"]],
            cited_version_ids=[ver["id"]])
        pub = d.publish_topic(topic["id"])
        snap = d.restore_snapshot(pub["snapshot_id"])
        self.assertEqual(snap["frozen"]["versions"][ver["id"]]["pages"], "33")
        self.assertEqual(snap["frozen"]["version_supplements"][ver["id"]], [])

        # 出版后再发现书影、做出署名考证与页码订正——全部以补充版本追加
        ev_photo = d.add_evidence(
            "书影", "新见原书书影", {"shelfmark": "新入藏-04"},
            certainty="确证", asset_id=None)
        asset = d.register_asset("书影照片", "高清")
        ev_page = d.add_evidence(
            "页码著录", "据书影订正页码",
            {"shelfmark": "新入藏-04", "page": "38"}, certainty="确证",
            asset_id=asset["id"])
        d.add_supplement(
            "新增书影", "evidence", ev_old["id"], "补充原书书影一件",
            evidence_id=ev_photo["id"])
        d.add_supplement(
            "页码订正", "version", ver["id"], "原著录33页，据书影应为38页",
            evidence_id=ev_page["id"],
            correction={"field": "pages", "from": "33", "to": "38"})

        # 工作态可见订正；已出版快照原样不变
        view = d.view_version(ver["id"])
        self.assertTrue(view["has_corrections"])
        self.assertEqual(view["pages"], "33")  # 原内容保留，不就地改
        self.assertEqual(view["supplements"][0]["correction"]["to"], "38")
        snap_after = d.restore_snapshot(pub["snapshot_id"])
        self.assertEqual(
            snap_after["frozen"]["versions"][ver["id"]]["pages"], "33")
        self.assertEqual(
            snap_after["frozen"]["version_supplements"][ver["id"]], [])

        # 已出版专题不得直接增改说明
        with self.assertRaises(DomainError):
            d.add_statement(topic["id"], "补一句", evidence_ids=[ev_page["id"]],
                            cited_version_ids=[ver["id"]])

        # 页码订正缺少 field/from/to 时拒绝
        with self.assertRaises(DomainError):
            d.add_supplement("页码订正", "version", ver["id"], "缺字段",
                             evidence_id=ev_page["id"], correction={"to": "39"})

    # ------------------------------------------------- 授权/清晰度/地域导出判定

    def test_export_gate_permission_quality_region_dates(self):
        d = self.d
        a_hd = d.register_asset("遵义文献书影", "高清")
        a_mid = d.register_asset("长征记插图", "可用")
        a_exp = d.register_asset("过期授权件", "高清")

        d.grant_permission(
            a_hd["id"], "某纪念馆", ["展览", "电子出版"], ["北京"],
            "2026-01-01", "2026-12-31")
        d.grant_permission(
            a_mid["id"], "某图书馆", ["展览"], ["全球"],
            "2026-01-01", "2026-12-31")
        # 先有一条过期许可
        d.grant_permission(
            a_exp["id"], "某档案馆", ["展览", "电子出版"], ["上海"],
            "2020-01-01", "2020-12-31")

        # 北京展览：高清件许可用途/地域/有效期均满足 → 通过
        ok = d.evaluate_export("展览", "北京", [a_hd["id"]])
        self.assertTrue(ok["export_allowed"])

        # 电子出版只授权到北京地域，上海不行
        sh = d.evaluate_export("电子出版", "上海", [a_hd["id"]])
        self.assertFalse(sh["export_allowed"])
        self.assertTrue(any("地域" in r for r in sh["results"][0]["reasons"]))

        # 电子出版要求高清：可用清晰度件即使展览通过，电子出版也被拦
        ep = d.evaluate_export("电子出版", "北京", [a_mid["id"]])
        self.assertFalse(ep["export_allowed"])
        self.assertTrue(any("清晰度" in r for r in ep["results"][0]["reasons"]))
        ex_show = d.evaluate_export("展览", "广东", [a_mid["id"]])
        self.assertTrue(ex_show["export_allowed"])  # 全球地域

        # 许可过期 → 不可导出
        expired = d.evaluate_export("展览", "上海", [a_exp["id"]])
        self.assertFalse(expired["export_allowed"])
        self.assertTrue(any("有效期" in r for r in expired["results"][0]["reasons"]))

        # 补办一条新许可后同一素材即可导出（以覆盖许可为准）
        d.grant_permission(
            a_exp["id"], "某档案馆", ["展览"], ["上海"],
            "2026-01-01", "2027-12-31")
        renewed = d.evaluate_export("展览", "上海", [a_exp["id"]])
        self.assertTrue(renewed["export_allowed"])

        # 无任何许可的素材
        a_none = d.register_asset("来源不明件", "高清")
        none = d.evaluate_export("展览", "北京", [a_none["id"]])
        self.assertFalse(none["export_allowed"])
        self.assertIn("无任何馆藏许可", none["results"][0]["reasons"])

        # 整批导出：一件不过则整批不过
        batch = d.evaluate_export(
            "展览", "北京", [a_hd["id"], a_mid["id"], a_none["id"]])
        self.assertFalse(batch["export_allowed"])
        self.assertEqual([r["allowed"] for r in batch["results"]],
                         [True, True, False])

    # --------------------------------------------- 争议、首创说明与一句说明溯源

    def test_statement_requires_evidence_and_full_traceability(self):
        d = self.d
        work, chen, other, serial, manuscript, pamphlet, translation = \
            self._build_work_one()
        ev = d.add_evidence(
            "刊物期次", "连载第1期出版信息",
            {"issue": "第1期", "page": "3"}, certainty="确证")
        ev2 = d.add_evidence(
            "手稿影像", "手稿署年", {"shelfmark": "稿-1"}, certainty="确证")
        d.add_contribution(serial["id"], chen["id"], "署名",
                           signed_name="廉臣", evidence_ids=[ev["id"]])

        claim = d.add_claim(
            "版本署名", chen["id"], "廉臣即陈云",
            [ev["id"], ev2["id"]], certainty="确证", version_id=serial["id"])
        rival = d.add_claim(
            "版本署名", other["id"], "廉臣另有其人",
            [ev["id"]], certainty="存疑", version_id=serial["id"])
        d.adopt_claim(claim["id"])

        for v in (serial, manuscript):
            d.transition_version(v["id"], "考证中")
            d.transition_version(v["id"], "待授权")
            d.transition_version(v["id"], "可采用")

        contro = d.open_controversy(
            "“廉臣”署名之争",
            subject_refs=[{"type": "version", "id": serial["id"]},
                          {"type": "claim", "id": claim["id"]}])
        d.add_controversy_position(
            contro["id"], "档案与署名互证为陈云", claim_id=claim["id"],
            evidence_ids=[ev["id"], ev2["id"]])
        d.add_controversy_position(
            contro["id"], "仍有研究者持异说", claim_id=rival["id"],
            evidence_ids=[ev["id"]])

        topic = d.create_topic("长征早期文献专题", work_ids=[work["id"]])

        # “最早”说明缺确定性或缺证据或缺版本，一律拒绝
        with self.assertRaises(DomainError):
            d.add_statement(topic["id"], "最早见于连载。", kind="最早",
                            cited_version_ids=[serial["id"]],
                            evidence_ids=[ev["id"]])
        with self.assertRaises(DomainError):
            d.add_statement(topic["id"], "最早见于连载。", kind="最早",
                            certainty="推定", cited_version_ids=[serial["id"]])
        with self.assertRaises(DomainError):
            d.add_statement(topic["id"], "最早见于连载。", kind="最早",
                            certainty="推定", evidence_ids=[ev["id"]])

        stmt = d.add_statement(
            topic["id"],
            "1936年海外连载是该文目前可证的最早公开形态（推定）。",
            kind="最早", certainty="推定", evidence_ids=[ev["id"]],
            cited_version_ids=[serial["id"], manuscript["id"]],
            adopted_claim_id=claim["id"])

        # 只能挂已采纳主张
        with self.assertRaises(DomainError):
            d.add_statement(
                topic["id"], "异说。", kind="其他",
                evidence_ids=[ev["id"]], cited_version_ids=[serial["id"]],
                adopted_claim_id=rival["id"])

        pub = d.publish_topic(topic["id"])

        trace = d.trace_statement(stmt["id"])
        # 一句说明回到：版本、贡献者（笔名+真人）、证据、授权、竞争观点、争议、快照
        self.assertEqual(trace["topic"]["title"], "长征早期文献专题")
        self.assertEqual({v["id"] for v in trace["versions"]},
                         {serial["id"], manuscript["id"]})
        contributors = {(c["person_name"], c["signed_name"])
                         for c in trace["contributors"]}
        self.assertIn(("陈云", "廉臣"), contributors)
        self.assertGreaterEqual(len(trace["evidence"]), 2)
        adopted = trace["adopted_claim"]
        self.assertEqual(adopted["status"], "已采纳")
        self.assertEqual({c["id"] for c in trace["competing_claims"]},
                         {claim["id"], rival["id"]})
        self.assertEqual(trace["controversies"][0]["title"],
                         "“廉臣”署名之争")
        self.assertEqual(trace["snapshots"][0]["id"], pub["snapshot_id"])

        # “源自某稿”说明同样受证据+确定性约束
        t2 = d.create_topic("源流专题", work_ids=[work["id"]])
        with self.assertRaises(DomainError):
            d.add_statement(t2["id"], "英译本源自手稿。", kind="源自稿")
        s2 = d.add_statement(
            t2["id"], "英译本序文源自手稿（确证）。", kind="源自稿",
            certainty="确证", evidence_ids=[ev2["id"]],
            cited_version_ids=[manuscript["id"]])
        self.assertEqual(s2["kind"], "源自稿")

    # ------------------------------------------------------------------ 出版门槛

    def test_publish_requires_adoptable_versions(self):
        d = self.d
        work = d.create_work("未整理完的文献")
        ver = d.create_version(work["id"], "手稿", "散稿")
        ev = d.add_evidence("档案记录", "馆藏", {"shelfmark": "x-1"})
        topic = d.create_topic("草稿专题", work_ids=[work["id"]])
        d.add_statement(
            topic["id"], "最早手稿（存疑）。", kind="最早", certainty="存疑",
            evidence_ids=[ev["id"]], cited_version_ids=[ver["id"]])
        # 版本尚在待编目，不能出版
        with self.assertRaises(DomainError):
            d.publish_topic(topic["id"])
        d.transition_version(ver["id"], "考证中")
        # 非法跳转：考证中不能直接出版，须先进入可采用
        with self.assertRaises(DomainError):
            d.transition_version(ver["id"], "已出版")
        d.transition_version(ver["id"], "待授权")
        d.transition_version(ver["id"], "可采用")
        d.publish_topic(topic["id"])
        self.assertEqual(d.get_version(ver["id"])["state"], "已出版")
        # 已出版为终态
        with self.assertRaises(DomainError):
            d.transition_version(ver["id"], "考证中")

    def test_empty_topic_cannot_publish(self):
        d = self.d
        topic = d.create_topic("空专题")
        with self.assertRaises(DomainError):
            d.publish_topic(topic["id"])

    def test_missing_reference_errors_are_explicit(self):
        d = self.d
        with self.assertRaises(NotFound):
            d.get_work("work_999")
        with self.assertRaises(NotFound):
            d.trace_statement("stmt_999")

    # --------------------------------------------------------------- 追加式日志

    def test_event_log_is_append_only(self):
        d = self.d
        d.register_person("甲")
        d.register_person("乙")
        events = d.list_events()
        self.assertEqual([e["seq"] for e in events], [1, 2])
        self.assertEqual([e["op"] for e in events],
                         ["person.registered", "person.registered"])
        # 返回副本，外部修改不影响内部日志
        events.clear()
        self.assertEqual(len(d.list_events()), 2)


if __name__ == "__main__":
    unittest.main()
