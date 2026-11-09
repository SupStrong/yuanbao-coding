# -*- coding: utf-8 -*-
"""
元宝搜索 SearchPro API 客户端（零依赖，纯 Python 标准库实现 TC3-HMAC-SHA256 签名）
用法:
    from wsa_client import WsaClient
    c = WsaClient()                 # 自动读取同目录 .env
    res = c.search("腾讯股价", mode=1)
"""
import hmac
import hashlib
import json
import os
import time
import urllib.request
from pathlib import Path

HOST = "wsa.tencentcloudapi.com"
SERVICE = "wsa"
VERSION = "2025-05-08"
ACTION = "SearchPro"


def _load_env(env_path: Path) -> dict:
    out = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


class WsaClient:
    def __init__(self, secret_id: str = "", secret_key: str = "", env_file: str | None = None):
        env = _load_env(Path(env_file or Path(__file__).parent / ".env"))
        self.secret_id = secret_id or env.get("TENCENTCLOUD_SECRET_ID") or os.environ.get("TENCENTCLOUD_SECRET_ID", "")
        self.secret_key = secret_key or env.get("TENCENTCLOUD_SECRET_KEY") or os.environ.get("TENCENTCLOUD_SECRET_KEY", "")
        if not self.secret_id or not self.secret_key:
            raise ValueError("缺少 TENCENTCLOUD_SECRET_ID / TENCENTCLOUD_SECRET_KEY")

    # ---------- TC3-HMAC-SHA256 签名 ----------
    def _sign(self, timestamp: int, payload: bytes) -> str:
        date = time.strftime("%Y-%m-%d", time.gmtime(timestamp))

        canonical_request = "\n".join([
            "POST",
            "/",
            "",
            f"content-type:application/json; charset=utf-8\nhost:{HOST}\nx-tc-action:{ACTION.lower()}\n",
            "content-type;host;x-tc-action",
            hashlib.sha256(payload).hexdigest(),
        ])

        string_to_sign = "\n".join([
            "TC3-HMAC-SHA256",
            str(timestamp),
            f"{date}/{SERVICE}/tc3_request",
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ])

        k_date = hmac.new(("TC3" + self.secret_key).encode("utf-8"), date.encode("utf-8"), hashlib.sha256).digest()
        k_service = hmac.new(k_date, SERVICE.encode("utf-8"), hashlib.sha256).digest()
        k_signing = hmac.new(k_service, b"tc3_request", hashlib.sha256).digest()
        signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        return signature

    # ---------- 调用接口 ----------
    def search(self, query: str, mode: int | None = None, cnt: int | None = None,
               freshness: str | None = None, industry: str | None = None,
               site: str | None = None, timeout: int = 20) -> dict:
        params: dict = {"Query": query}
        if mode is not None:
            params["Mode"] = mode
        if cnt is not None:
            params["Cnt"] = cnt
        if freshness is not None:
            params["Freshness"] = freshness
        if industry is not None:
            params["Industry"] = industry
        if site is not None:
            params["Site"] = site

        payload = json.dumps(params).encode("utf-8")
        timestamp = int(time.time())
        signature = self._sign(timestamp, payload)

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Host": HOST,
            "X-TC-Action": ACTION,
            "X-TC-Version": VERSION,
            "X-TC-Timestamp": str(timestamp),
            "Authorization": f"TC3-HMAC-SHA256 Credential={self.secret_id}/{time.strftime('%Y-%m-%d', time.gmtime(timestamp))}/{SERVICE}/tc3_request, SignedHeaders=content-type;host;x-tc-action, Signature={signature}",
        }

        req = urllib.request.Request(f"https://{HOST}", data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return {"HTTPError": e.code, "body": e.read().decode("utf-8", "ignore")}

    def pages(self, query: str, **kw) -> list[dict]:
        """返回解析后的结果列表（每条为 dict），VR 结果含 vr/vr_category/vrid 字段"""
        raw = self.search(query, **kw)
        resp = raw.get("Response")
        if not resp:
            raise RuntimeError(f"接口返回异常: {json.dumps(raw, ensure_ascii=False)[:300]}")
        if "Error" in resp:
            raise RuntimeError(f"API 错误: {resp['Error'].get('Code')} - {resp['Error'].get('Message')} (query={query})")
        out = []
        for p in resp.get("Pages", []):
            if isinstance(p, str):
                try:
                    out.append(json.loads(p))
                except json.JSONDecodeError:
                    out.append({"_raw": p})
            else:
                out.append(p)
        return out


if __name__ == "__main__":
    c = WsaClient()
    r = c.search("腾讯股价", mode=1)
    print(json.dumps(r, ensure_ascii=False, indent=2)[:1500])
