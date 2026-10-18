"""Optional loopback llama.cpp schema proxy; never repairs or invents responses.

llama.cpp documents schema-bearing json_object response_format and json_schema:
https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
Only exact engine system prompts receive schemas. Normal call_json callers retain
their original response format. No request, response or access logs are emitted.
"""
from __future__ import annotations

from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from contracts.models import Evaluation, RATING_ANCHORS, RatingDimension, RunMode
from engine.agent import Action, SYSTEM as ACTION_SYSTEM
from engine.evaluate import SYSTEM as EVALUATION_SYSTEM

try:
    from jsonschema import Draft202012Validator as _JsonSchemaValidator
except ImportError:  # Optional diagnostics must not add a runtime dependency.
    _JsonSchemaValidator = None

MAX_REQUEST_BYTES = 4 * 1024 * 1024
DIAGNOSTICS = False


def _inline(node, definitions):
    """Avoid nested references unsupported by some llama.cpp grammar converters."""
    if isinstance(node, list):
        return [_inline(item, definitions) for item in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        return _inline(definitions[node["$ref"].removeprefix("#/$defs/")], definitions)
    return {key: _inline(value, definitions) for key, value in node.items()
            if key not in {"$defs", "title", "default"}}


def _identity(prompt: str) -> dict:
    # Parse only the exact engine-authored prefix. Do not inspect, unescape or
    # interpret anything in <evidence>, <page>, or a previous repair response.
    prefix = "Rating anchors: " + json.dumps(RATING_ANCHORS) + "\nJSON shape: "
    if not prompt.startswith(prefix):
        return {}
    trusted = prompt[len(prefix):].split("\n<evidence>", 1)[0]
    try:
        shape, end = json.JSONDecoder().raw_decode(trusted)
        if not trusted[end:].startswith("\nProblems use "):
            return {}
        if not isinstance(shape, dict) or set(shape) != set(Evaluation.model_fields):
            return {}
        if not all(isinstance(shape.get(key), str) and shape[key] for key in ("run_id", "user_id")):
            return {}
        if shape.get("mode") not in {mode.value for mode in RunMode}:
            return {}
        return {key: shape[key] for key in ("run_id", "user_id", "mode")}
    except (ValueError, TypeError):
        return {}


def evaluation_schema(prompt: str) -> dict:
    schema = Evaluation.model_json_schema()
    # Pydantic model validators are not represented in its JSON Schema.
    # Disjoint branches express Rating._exactly_one without choosing a score.
    rating = {"oneOf": [
        {"type": "object", "properties": {
            "score": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
            "not_assessable_reason": {"type": "null"}},
         "required": ["score", "not_assessable_reason"], "additionalProperties": False},
        {"type": "object", "properties": {
            "score": {"type": "null"},
            "not_assessable_reason": {"type": "string", "minLength": 1, "maxLength": 120}},
         "required": ["score", "not_assessable_reason"], "additionalProperties": False},
    ]}
    schema["properties"]["ratings"] = {
        "type": "object", "properties": {dimension.value: deepcopy(rating) for dimension in RatingDimension},
        "required": [dimension.value for dimension in RatingDimension], "additionalProperties": False}
    schema["properties"]["rating_reasons"].update(minLength=1, maxLength=320)
    for field in ("strengths", "suggestions"):
        schema["properties"][field]["maxItems"] = 3
        schema["properties"][field]["items"]["maxLength"] = 120
    schema["properties"]["problems"]["maxItems"] = 3
    schema["$defs"]["Problem"]["properties"]["text"]["maxLength"] = 200
    for branch in schema["properties"]["pricing_feedback"]["anyOf"]:
        if branch.get("type") == "string":
            branch["maxLength"] = 240
    schema["additionalProperties"] = False
    for key, value in _identity(prompt).items():
        schema["properties"][key] = {"type": "string", "const": value}
    return _inline(schema, schema.get("$defs", {}))


def _action_arguments(prompt: str) -> dict | None:
    prefix = "Allowed action arguments: "
    first_line = prompt.split("\n", 1)[0]
    if not first_line.startswith(prefix):
        return None
    try:
        data = json.loads(first_line[len(prefix):])
        if not isinstance(data, dict) or set(data) != {"click", "type", "select", "type_values", "back"}:
            return None
        for field in ("click", "type"):
            values = data[field]
            if (not isinstance(values, list) or len(values) > 60
                    or any(type(value) is not int or not 1 <= value <= 60 for value in values)
                    or len(set(values)) != len(values)):
                return None
        if not set(data["type"]).issubset(data["click"]) or not isinstance(data["select"], dict):
            return None
        for key, values in data["select"].items():
            if (not isinstance(key, str) or not key.isascii() or not key.isdigit()
                    or str(int(key)) != key or int(key) not in data["click"]
                    or not isinstance(values, list) or any(not isinstance(value, str) for value in values)):
                return None
        values = data["type_values"]
        if (not isinstance(values, list) or len(values) != 3
                or any(not isinstance(value, str) or not value for value in values)
                or len(set(values)) != 3 or type(data["back"]) is not bool):
            return None
        return data
    except (ValueError, TypeError):
        return None


def action_schema(prompt: str = "") -> dict:
    """Constrain action-field combinations without selecting an action."""
    base = _inline(Action.model_json_schema(), {})
    base["properties"]["reason"]["maxLength"] = 160
    allowed = _action_arguments(prompt)
    branches = []
    for name in base["properties"]["action"]["enum"]:
        if allowed is not None:
            if name in {"click", "type"} and not allowed[name]:
                continue
            if name == "back" and not allowed["back"]:
                continue
            if name == "select":
                for element, options in allowed["select"].items():
                    if options:
                        branch = deepcopy(base)
                        branch["properties"].update({
                            "action": {"type": "string", "const": "select"},
                            "element": {"type": "integer", "const": int(element)},
                            "value": {"type": "string", "enum": list(dict.fromkeys(options))}})
                        branches.append(branch)
                continue
        branch = deepcopy(base)
        properties = branch["properties"]
        properties["action"] = {"type": "string", "const": name}
        properties["element"] = ({"type": "integer", "minimum": 1}
                                 if name in {"click", "type", "select"} else {"type": "null"})
        if name in {"type", "select"}:
            properties["value"] = {"type": "string"}
        elif name == "scroll":
            properties["value"] = {"anyOf": [{"type": "null"},
                {"type": "string", "enum": ["up", "down"]}]}
        else:
            properties["value"] = {"type": "null"}
        if allowed is not None:
            if name in {"click", "type"}:
                properties["element"] = {"type": "integer", "enum": allowed[name]}
            if name == "type":
                properties["value"] = {"type": "string", "enum": allowed["type_values"]}
        branches.append(branch)
    # llama.cpp does not support mixing properties with oneOf at one node.
    return {"oneOf": branches}


def constrain_request(payload: dict) -> dict:
    """Copy a trusted engine request and add documented llama.cpp constraints."""
    messages = payload.get("messages")
    if not isinstance(messages, list) or len(messages) != 2 or not all(isinstance(item, dict) for item in messages):
        return payload
    system, user = messages
    if system.get("role") != "system" or user.get("role") != "user" or not isinstance(user.get("content"), str):
        return payload
    if system.get("content") == ACTION_SYSTEM:
        schema = action_schema(user["content"])
    elif system.get("content") == EVALUATION_SYSTEM:
        schema = evaluation_schema(user["content"])
    else:
        return payload
    result = dict(payload)
    result["response_format"] = {"type": "json_object", "schema": schema}
    result["json_schema"] = schema
    return result


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def _upstream(url: str) -> str:
    try:
        parts = urlsplit(url)
        parts.port
        valid = (parts.scheme == "http" and parts.hostname in {"127.0.0.1", "localhost"}
                 and not parts.username and not parts.password and not parts.query
                 and not parts.fragment and parts.path in {"", "/"})
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("upstream must be a loopback HTTP server URL without a path or credentials")
    return url.rstrip("/")


def _diagnose(request_body: bytes | None, status: int, response_body: bytes) -> None:
    if not DIAGNOSTICS:
        return
    def object_from(raw):
        try:
            value = json.loads(raw or b"{}")
            return value if isinstance(value, dict) else {}
        except (ValueError, UnicodeError):
            return {}
    request = object_from(request_body)
    response = object_from(response_body)
    format_ = request.get("response_format")
    format_ = format_ if isinstance(format_, dict) else {}
    choices = response.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    message = choice.get("message")
    message = message if isinstance(message, dict) else {}
    usage = response.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    format_type = format_.get("type")
    finish = choice.get("finish_reason")
    count = lambda value: len(value) if isinstance(value, str) else 0
    tokens = lambda value: value if type(value) is int and value >= 0 else None
    content, content_valid = None, False
    try:
        if isinstance(message.get("content"), str):
            content = json.loads(message["content"])
            content_valid = True
    except (ValueError, UnicodeError):
        pass
    kinds = ((dict, "dict"), (list, "list"), (str, "str"), (bool, "bool"), (int, "int"), (float, "float"))
    kind = next((label for type_, label in kinds if isinstance(content, type_)), "null") if content_valid else None
    messages = request.get("messages")
    action_expected = bool(isinstance(messages, list) and messages and isinstance(messages[0], dict)
                           and messages[0].get("role") == "system" and messages[0].get("content") == ACTION_SYSTEM)
    action_content = content if action_expected and isinstance(content, dict) else {}
    # Never include unknown response keys or their values in diagnostics.
    known = list(Action.model_fields)
    missing = [key for key in known if key not in action_content] if action_expected else []
    action = action_content.get("action")
    element = action_content.get("element")
    schema = request.get("json_schema") or format_.get("schema")
    error_count = None
    if (_JsonSchemaValidator is not None and content_valid and isinstance(schema, dict)
            and '"$ref"' not in json.dumps(schema)):
        try:
            error_count = sum(1 for _ in _JsonSchemaValidator(schema).iter_errors(content))
        except Exception:
            pass  # Invalid diagnostic schema never changes a provider response.
    diagnostic = {
        "response_format": format_type if format_type in ("json_schema", "json_object", "text") else None,
        "schema_supplied": isinstance(schema, dict) or isinstance(format_.get("json_schema"), dict),
        "http_status": status,
        "finish_reason": finish if finish in ("stop", "length", "tool_calls", "content_filter", "function_call") else None,
        "content_chars": count(message.get("content")),
        "reasoning_chars": count(message.get("reasoning_content") or message.get("reasoning")),
        "input_tokens": tokens(usage.get("prompt_tokens")),
        "output_tokens": tokens(usage.get("completion_tokens")),
        "content_json_valid": content_valid, "content_kind": kind,
        "knownmissing_action_keys": missing,
        "action": action if action in ("click", "type", "select", "scroll", "back", "done", "give_up") else None,
        "element": element if type(element) is int else None,
        "schema_validation_error_count": error_count,
    }
    try:
        print(json.dumps(diagnostic), flush=True)
    except OSError:
        pass


def _response_headers(status: int, headers: dict) -> dict:
    if status < 400:
        return dict(headers)
    # Let the engine's explicit retry policy own retries. The OpenAI SDK checks
    # this server response header before automatically retrying HTTP failures.
    result = {key: value for key, value in headers.items() if key.lower() != "x-should-retry"}
    result["x-should-retry"] = "false"
    return result


def forward_request(upstream_url: str, method: str, path: str, body: bytes | None,
                    headers: dict, timeout: float = 120.0) -> tuple[int, dict, bytes]:
    """Return the upstream status, headers and body without rewriting responses."""
    upstream_url = _upstream(upstream_url)
    if path not in {"/health", "/v1/models", "/v1/chat/completions"}:
        return 404, _response_headers(404, {"Content-Type": "application/json"}), b'{"error":"unsupported proxy endpoint"}'
    if (method == "POST") != (path == "/v1/chat/completions") or method not in {"GET", "POST"}:
        return 405, _response_headers(405, {"Content-Type": "application/json"}), b'{"error":"unsupported proxy method"}'
    if method == "POST" and body:
        try:
            payload = json.loads(body)
            if isinstance(payload, dict):
                constrained = constrain_request(payload)
                if constrained is not payload:
                    body = json.dumps(constrained, ensure_ascii=False).encode("utf-8")
        except (ValueError, UnicodeError):
            pass  # The upstream retains responsibility for malformed requests.
    forwarded = {key: value for key, value in headers.items()
                 if key.lower() in {"authorization", "content-type", "accept"}}
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    request = Request(upstream_url + path, data=body, headers=forwarded, method=method)
    try:
        with opener.open(request, timeout=timeout) as response:
            content = response.read()
            if path == "/v1/chat/completions":
                _diagnose(body, response.status, content)
            return response.status, _response_headers(response.status, dict(response.headers)), content
    except HTTPError as response:
        try:
            content = response.read()
            if path == "/v1/chat/completions":
                _diagnose(body, response.code, content)
            return response.code, _response_headers(response.code, dict(response.headers)), content
        finally:
            response.close()
    except OSError:
        return 502, _response_headers(502, {"Content-Type": "application/json"}), b'{"error":"local upstream unavailable"}'


def create_proxy(upstream_url: str, port: int, host: str = "127.0.0.1",
                 timeout: float = 120.0) -> ThreadingHTTPServer:
    """Create a bound proxy; caller owns serve_forever/shutdown/server_close."""
    upstream_url = _upstream(upstream_url)
    if host not in {"127.0.0.1", "localhost"} or type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("proxy must bind a loopback host and port in 1024..65535")
    if (urlsplit(upstream_url).port or 80) == port:
        raise ValueError("proxy and upstream must use different ports")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, headers, content):
            try:
                self.send_response(status)
                excluded = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
                            "te", "trailer", "transfer-encoding", "upgrade", "content-length"}
                for key, value in _response_headers(status, headers).items():
                    if key.lower() not in excluded:
                        self.send_header(key, value)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def relay(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.reply(400, {"Content-Type": "application/json"}, b'{"error":"invalid content length"}')
                return
            if not 0 <= length <= MAX_REQUEST_BYTES:
                self.reply(413, {"Content-Type": "application/json"}, b'{"error":"request too large"}')
                return
            body = self.rfile.read(length) if length else None
            self.reply(*forward_request(upstream_url, self.command, self.path, body,
                                        dict(self.headers), timeout))

        do_GET = do_POST = relay

    class Server(ThreadingHTTPServer):
        daemon_threads = True

        def handle_error(self, request, client_address):
            # Exceptions must not dump request data or provider content.
            pass

    return Server((host, port), Handler)


def serve_proxy(upstream_url: str, port: int, host: str = "127.0.0.1",
                timeout: float = 170.0) -> None:
    with create_proxy(upstream_url, port, host, timeout) as server:
        server.serve_forever()


def main() -> None:
    global DIAGNOSTICS
    import argparse
    import math
    from dotenv import load_dotenv
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--timeout", type=float, default=170.0,
                        help="Upstream timeout in seconds; keep below the calling client's timeout")
    parser.add_argument("--diagnostics", action="store_true", help="Print status, token counts and lengths only")
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("timeout must be finite and positive")
    DIAGNOSTICS = args.diagnostics
    print(f"Local schema proxy on 127.0.0.1:{args.port}; traffic logging is disabled.", flush=True)
    try:
        serve_proxy(args.upstream, args.port, timeout=args.timeout)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
