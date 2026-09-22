"""验证基础服务、领域契约与端到端 API。"""

import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from domain import DocumentLineage
from service import (Handler, SERVICE_ID, health_payload, load_contract,
                     make_handler)


class ServiceContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def read_json(self, path):
        with urlopen(f"{self.base_url}{path}", timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "application/json")
            return json.load(response)

    def test_health_identity(self):
        self.assertEqual(self.read_json("/health"), health_payload())

    def test_contract_identity_and_rules(self):
        contract = self.read_json("/contract")
        self.assertEqual(contract, load_contract())
        self.assertEqual(contract["service_id"], SERVICE_ID)
        self.assertGreaterEqual(len(contract["invariants"]), 3)

    def test_unknown_route_is_hidden(self):
        with self.assertRaises(HTTPError) as error:
            urlopen(f"{self.base_url}/unknown", timeout=2)
        self.assertEqual(error.exception.code, 404)
        error.exception.close()


class ApiEndToEndTest(unittest.TestCase):
    """通过 HTTP 走通建档、考证、出版、补充与溯源全链路。"""

    @classmethod
    def setUpClass(cls):
        cls.domain = DocumentLineage(clock=lambda: "2026-09-22")
        cls.handler = make_handler(cls.domain)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), cls.handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request(self, method, path, payload=None):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") \
            if payload is not None else None
        req = Request(f"{self.base_url}{path}", data=data, method=method,
                      headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=2) as response:
            self.assertEqual(response.status, 200)
            return json.load(response)

    def request_error(self, method, path, payload=None):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") \
            if payload is not None else None
        req = Request(f"{self.base_url}{path}", data=data, method=method,
                      headers={"Content-Type": "application/json"})
        try:
            urlopen(req, timeout=2)
        except HTTPError as error:
            body = json.load(error)
            return error.code, body
        self.fail("应当返回错误状态码")

    def test_full_workflow_over_http(self):
        work = self.request("POST", "/api/works",
                            {"title": "随军西行见闻录", "alt_titles": ["从福建到陕西"]})
        person = self.request("POST", "/api/people",
                              {"name": "陈云", "aliases": ["廉臣"]})
        version = self.request("POST", "/api/versions", {
            "work_id": work["id"], "kind": "连载",
            "title": "海外报刊连载", "issue": "第1期", "pages": "3"})
        evidence = self.request("POST", "/api/evidence", {
            "evidence_type": "刊物期次", "citation": "报刊第1期",
            "locator": {"issue": "第1期", "page": "3"},
            "certainty": "确证"})
        self.request("POST", "/api/contributions", {
            "version_id": version["id"], "person_id": person["id"],
            "role": "署名", "signed_name": "廉臣",
            "evidence_ids": [evidence["id"]]})
        claim = self.request("POST", "/api/claims", {
            "subject": "版本署名", "person_id": person["id"],
            "summary": "廉臣即陈云", "evidence_ids": [evidence["id"]],
            "certainty": "确证", "version_id": version["id"]})
        self.request("POST", f"/api/claims/{claim['id']}/adopt")

        # 受控词表外的值 → 400 JSON
        code, body = self.request_error("POST", "/api/versions", {
            "work_id": work["id"], "kind": "非法类型", "title": "x"})
        self.assertEqual(code, 400)
        self.assertIn("受控词表", body["message"])

        # 无定位的证据 → 400
        code, _ = self.request_error("POST", "/api/evidence", {
            "evidence_type": "书影", "citation": "无定位", "locator": {}})
        self.assertEqual(code, 400)

        # 不存在的资源 → 404
        code, _ = self.request_error("GET", "/api/works/work_42")
        self.assertEqual(code, 404)

        for to_state in ("考证中", "待授权", "可采用"):
            self.request("POST", f"/api/versions/{version['id']}/transitions",
                         {"to_state": to_state})

        topic = self.request("POST", "/api/topics",
                             {"title": "长征早期文献专题", "work_ids": [work["id"]]})
        # “最早”说明不带确定性 → 400
        code, _ = self.request_error(
            "POST", f"/api/topics/{topic['id']}/statements", {
                "text": "最早刊载。", "kind": "最早",
                "evidence_ids": [evidence["id"]],
                "cited_version_ids": [version["id"]]})
        self.assertEqual(code, 400)

        statement = self.request(
            "POST", f"/api/topics/{topic['id']}/statements", {
                "text": "目前可证的最早公开形态（推定）。", "kind": "最早",
                "certainty": "推定", "evidence_ids": [evidence["id"]],
                "cited_version_ids": [version["id"]],
                "adopted_claim_id": claim["id"]})
        pub = self.request("POST", f"/api/topics/{topic['id']}/publish")
        self.assertEqual(pub["edition"], 1)

        trace = self.request("GET", f"/api/statements/{statement['id']}/trace")
        self.assertEqual(trace["contributors"][0]["signed_name"], "廉臣")
        self.assertEqual(trace["contributors"][0]["person_name"], "陈云")
        self.assertEqual(trace["snapshots"][0]["id"], pub["snapshot_id"])

        snap = self.request("GET", f"/api/snapshots/{pub['snapshot_id']}")
        self.assertEqual(
            snap["frozen"]["versions"][version["id"]]["issue"], "第1期")

        events = self.request("GET", "/api/events")
        ops = {e["op"] for e in events["events"]}
        self.assertIn("topic.published", ops)
        self.assertIn("claim.adopted", ops)

    def test_export_gate_over_http(self):
        asset = self.request("POST", "/api/assets",
                             {"name": "书影", "quality": "高清"})
        self.request("POST", "/api/permissions", {
            "asset_id": asset["id"], "holder": "某纪念馆",
            "scopes": ["展览"], "regions": ["北京"],
            "valid_from": "2026-01-01", "valid_to": "2026-12-31"})
        allowed = self.request("POST", "/api/export-checks", {
            "purpose": "展览", "region": "北京", "asset_ids": [asset["id"]]})
        self.assertTrue(allowed["export_allowed"])
        denied = self.request("POST", "/api/export-checks", {
            "purpose": "电子出版", "region": "上海", "asset_ids": [asset["id"]]})
        self.assertFalse(denied["export_allowed"])
        self.assertFalse(denied["results"][0]["allowed"])
        self.assertTrue(
            any("清晰度" in r or "地域" in r
                for r in denied["results"][0]["reasons"]))


if __name__ == "__main__":
    unittest.main()

