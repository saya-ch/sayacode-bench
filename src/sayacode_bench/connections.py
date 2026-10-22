"""私有连接输入与无密钥的实验模型身份。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

CANONICAL_MODEL = "DeepSeek-V4.1-Flash"


def messages_endpoint(base_url: str) -> str:
    """保留显式 API 前缀，避免 /v1 被重复拼接。"""
    value = base_url.rstrip("/")
    return value + ("/messages" if value.endswith("/v1") else "/v1/messages")


@dataclass(frozen=True)
class Connection:
    """接口只是连接元数据，不作为模型差异或调优因素。"""

    name: str
    profile_path: Path
    protocol: str
    base_url: str
    model_id: str

    @property
    def endpoint_host(self) -> str:
        host = urlsplit(self.base_url).hostname
        if not host:
            raise ValueError("连接地址缺少主机")
        return host

    def public_dict(self) -> dict[str, str]:
        return {
            "id": self.name,
            "canonical_model": CANONICAL_MODEL,
            "protocol": self.protocol,
            "model_id": self.model_id,
            "endpoint_host": self.endpoint_host,
        }


def read_connection(name: str, path: Path) -> Connection:
    """读取显式私有文件；不读取环境中的 provider 凭据。"""
    profile: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(profile.get("api_key"), str) or not profile["api_key"]:
        raise ValueError("私有连接缺少密钥")
    parsed = urlsplit(str(profile.get("base_url", "")))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("私有连接地址无效")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("连接地址不能夹带凭据或查询参数")
    return Connection(
        name=name,
        profile_path=path.resolve(strict=True),
        protocol=str(profile["protocol"]),
        base_url=str(profile["base_url"]),
        model_id=str(profile["model_id"]),
    )
