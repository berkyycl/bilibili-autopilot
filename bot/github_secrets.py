"""GitHub REST API ile depo secret'ı yazma (BILIBILI_COOKIES_B64 için).

GitHub, secret değerlerinin depo açık anahtarıyla libsodium "sealed box"
kullanılarak şifrelenmesini ister. Şifreleme PyNaCl (libsodium) ile burada
yapılır; düz değer GitHub'a hiç gönderilmez.

GH_PAT için en dar yetki yeterlidir: fine-grained token, sadece bu depo,
"Secrets: Read and write" izni (README'ye bakın).
"""

from __future__ import annotations

import base64

import httpx
from nacl import encoding, public

API_BASE = "https://api.github.com"
COOKIES_SECRET_NAME = "BILIBILI_COOKIES_B64"


class SecretUpdateError(Exception):
    """Mesajı kullanıcıya gösterilebilir; token içermez."""


def _headers(pat: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "bilibili-autopilot",
    }


def _explain(status_code: int) -> str:
    if status_code == 401:
        return "GH_PAT geçersiz ya da süresi dolmuş (yenisini oluşturup secret'ı güncelle)"
    if status_code in (403, 404):
        return "GH_PAT'ın bu depoda 'Secrets: Read and write' izni yok"
    return f"GitHub API hatası (HTTP {status_code})"


def seal(public_key_b64: str, value: str) -> str:
    """Değeri depo açık anahtarıyla sealed box kullanarak şifreler (base64 döner)."""
    key = public.PublicKey(public_key_b64.encode(), encoding.Base64Encoder())
    encrypted = public.SealedBox(key).encrypt(value.encode())
    return base64.b64encode(encrypted).decode()


async def get_public_key(client: httpx.AsyncClient, pat: str, repo: str) -> tuple[str, str]:
    """(key_id, key) döndürür. Ayrıca GH_PAT'ın çalıştığını doğrulamak için de kullanılır."""
    try:
        response = await client.get(f"{API_BASE}/repos/{repo}/actions/secrets/public-key", headers=_headers(pat))
    except httpx.HTTPError:
        raise SecretUpdateError("GitHub API'ye ulaşılamadı") from None
    if response.status_code != 200:
        raise SecretUpdateError(_explain(response.status_code))
    data = response.json()
    return data["key_id"], data["key"]


async def put_secret(client: httpx.AsyncClient, pat: str, repo: str, name: str, value: str) -> None:
    key_id, key = await get_public_key(client, pat, repo)
    body = {"encrypted_value": seal(key, value), "key_id": key_id}
    try:
        response = await client.put(f"{API_BASE}/repos/{repo}/actions/secrets/{name}", json=body, headers=_headers(pat))
    except httpx.HTTPError:
        raise SecretUpdateError("GitHub API'ye ulaşılamadı") from None
    if response.status_code not in (201, 204):
        raise SecretUpdateError(_explain(response.status_code))
