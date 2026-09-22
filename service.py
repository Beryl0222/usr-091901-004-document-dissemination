"""历史文献传播谱系的服务入口。

在 /health 与 /contract 两个基础接口之上，把 domain.DocumentLineage 的领域操作
以资源式 HTTP 接口暴露：POST 创建/动作、GET 读取，错误统一返回 JSON。
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from domain import DocumentLineage, DomainError, NotFound, load_contract

SERVICE_ID = "document-dissemination"
SERVICE_NAME = "历史文献传播谱系"
CONTRACT_PATH = Path(__file__).with_name("domain_contract.json")


def health_payload():
    """返回服务运行状态。"""
    return {"status": "ok", "service": SERVICE_ID, "name": SERVICE_NAME}


def pick(body, *keys):
    """仅取请求体中实际提供的字段，透传给领域方法。"""
    return {k: body[k] for k in keys if k in body}


def build_routes():
    """返回 (method, 路径段, 处理函数) 列表；以“:”开头的段为路径参数。"""
    P, G = "POST", "GET"
    return [
        (P, ["api", "people"],
         lambda d, p, b: d.register_person(**pick(
             b, "name", "aliases", "person_id", "note"))),
        (P, ["api", "works"],
         lambda d, p, b: d.create_work(**pick(
             b, "title", "alt_titles", "work_id", "note"))),
        (G, ["api", "works", ":id"],
         lambda d, p, b: d.get_work(p["id"])),
        (P, ["api", "works", ":id", "missing-volumes"],
         lambda d, p, b: d.register_missing_volume(
             p["id"], **pick(b, "position", "reason", "evidence_ids", "note"))),

        (P, ["api", "versions"],
         lambda d, p, b: d.create_version(**pick(
             b, "work_id", "kind", "title", "version_id", "language",
             "publication", "issue", "volume", "pages", "published_on", "note"))),
        (G, ["api", "versions", ":id"],
         lambda d, p, b: d.get_version(p["id"])),
        (G, ["api", "versions", ":id", "view"],
         lambda d, p, b: d.view_version(p["id"])),
        (G, ["api", "versions", ":id", "lineage"],
         lambda d, p, b: d.traverse_lineage(p["id"])),
        (P, ["api", "versions", ":id", "transitions"],
         lambda d, p, b: d.transition_version(p["id"], b["to_state"])),

        (P, ["api", "contributions"],
         lambda d, p, b: d.add_contribution(**pick(
             b, "version_id", "person_id", "role", "signed_name",
             "evidence_ids", "contribution_id", "note"))),

        (P, ["api", "evidence"],
         lambda d, p, b: d.add_evidence(**pick(
             b, "evidence_type", "citation", "locator", "certainty",
             "excerpt", "asset_id", "evidence_id", "note"))),

        (P, ["api", "claims"],
         lambda d, p, b: d.add_claim(**pick(
             b, "subject", "person_id", "summary", "evidence_ids",
             "certainty", "work_id", "version_id", "claim_id", "note"))),
        (P, ["api", "claims", ":id", "adopt"],
         lambda d, p, b: d.adopt_claim(p["id"])),

        (P, ["api", "links"],
         lambda d, p, b: d.add_link(**pick(
             b, "relation", "source_version_id", "target_version_id",
             "evidence_ids", "link_id", "note"))),

        (P, ["api", "fragments"],
         lambda d, p, b: d.create_fragment(**pick(
             b, "label", "excerpt", "fragment_id"))),
        (P, ["api", "fragments", ":id", "uses"],
         lambda d, p, b: d.register_fragment_use(
             p["id"], **pick(b, "version_id", "pages", "note"))),
        (G, ["api", "fragments", ":id", "reuse"],
         lambda d, p, b: d.fragment_reuse(p["id"])),

        (P, ["api", "supplements"],
         lambda d, p, b: d.add_supplement(**pick(
             b, "kind", "target_type", "target_id", "summary",
             "evidence_id", "correction", "supplement_id"))),

        (P, ["api", "assets"],
         lambda d, p, b: d.register_asset(**pick(
             b, "name", "quality", "evidence_id", "asset_id", "note"))),
        (P, ["api", "permissions"],
         lambda d, p, b: d.grant_permission(**pick(
             b, "asset_id", "holder", "scopes", "regions",
             "valid_from", "valid_to", "permission_id", "note"))),
        (P, ["api", "export-checks"],
         lambda d, p, b: d.evaluate_export(**pick(
             b, "purpose", "region", "asset_ids", "on_date", "request_id"))),

        (P, ["api", "controversies"],
         lambda d, p, b: d.open_controversy(**pick(
             b, "title", "subject_refs", "positions", "controversy_id", "note"))),
        (P, ["api", "controversies", ":id", "positions"],
         lambda d, p, b: d.add_controversy_position(
             p["id"], **pick(b, "summary", "claim_id", "evidence_ids"))),
        (P, ["api", "controversies", ":id", "resolve"],
         lambda d, p, b: d.resolve_controversy(p["id"], b["resolution"])),

        (P, ["api", "topics"],
         lambda d, p, b: d.create_topic(**pick(
             b, "title", "work_ids", "topic_id", "note"))),
        (G, ["api", "topics", ":id"],
         lambda d, p, b: d.get_topic(p["id"])),
        (P, ["api", "topics", ":id", "statements"],
         lambda d, p, b: d.add_statement(
             p["id"], **pick(b, "text", "kind", "evidence_ids",
                            "cited_version_ids", "certainty",
                            "adopted_claim_id", "statement_id", "note"))),
        (P, ["api", "topics", ":id", "publish"],
         lambda d, p, b: d.publish_topic(
             p["id"], **pick(b, "published_on", "snapshot_id"))),

        (G, ["api", "statements", ":id", "trace"],
         lambda d, p, b: d.trace_statement(p["id"])),
        (G, ["api", "snapshots", ":id"],
         lambda d, p, b: d.restore_snapshot(p["id"])),
        (G, ["api", "events"],
         lambda d, p, b: {"events": d.list_events()}),
    ]


def match_route(method, segments):
    """匹配路由并提取路径参数。"""
    for route_method, pattern, handler in ROUTES:
        if method != route_method or len(pattern) != len(segments):
            continue
        params = {}
        for pat, seg in zip(pattern, segments):
            if pat.startswith(":"):
                params[pat[1:]] = seg
            elif pat != seg:
                break
        else:
            return handler, params
    return None, None


def make_handler(domain):
    """为给定领域实例构造一个 Handler 类（便于测试隔离）。"""

    class Handler(BaseHTTPRequestHandler):
        """提供健康检查、契约读取与领域操作接口。"""

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def _dispatch(self, method):
            path = self.path.split("?", 1)[0].rstrip("/") or "/"
            segments = [s for s in path.split("/") if s]
            if method == "GET" and path == "/health":
                self._send_json(health_payload())
                return
            if method == "GET" and path == "/contract":
                self._send_json(load_contract())
                return
            handler, params = match_route(method, segments)
            if handler is None:
                self._send_error_json(404, "未知路由")
                return
            body = {}
            if method == "POST":
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if raw:
                    try:
                        body = json.loads(raw.decode("utf-8"))
                    except json.JSONDecodeError as exc:
                        self._send_error_json(400, f"请求体不是合法 JSON：{exc}")
                        return
                if not isinstance(body, dict):
                    self._send_error_json(400, "请求体必须是 JSON 对象")
                    return
            try:
                result = handler(domain, params, body)
            except NotFound as exc:
                self._send_error_json(404, str(exc))
            except (DomainError, KeyError, TypeError, ValueError) as exc:
                self._send_error_json(400, str(exc))
            else:
                self._send_json(result if result is not None else {"ok": True})

        def _send_json(self, payload, status=200):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_error_json(self, status, message):
            self._send_json({"error": status, "message": message}, status)

        def log_message(self, *_args):
            return

    return Handler


ROUTES = build_routes()
Handler = make_handler(DocumentLineage())


def main():
    parser = argparse.ArgumentParser(description=SERVICE_NAME)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        contract = load_contract()
        assert contract["states"] and contract["invariants"]
        assert len(contract["invariants"]) >= 9
        DocumentLineage(contract)
        print("基础检查通过")
        return
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
