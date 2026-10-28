#!/usr/bin/env bash
# biliup CLI'yi GitHub release'den indirir, SHA-256 ile doğrular ve PATH'e ekler.
#
# biliup-rs deposu arşivlendi; geliştirme github.com/biliup/biliup deposunda
# sürüyor ve aynı CLI orada "biliupR-<sürüm>-x86_64-linux.tar.xz" olarak yayınlanıyor.
#
# Ortam değişkenleri:
#   BILIUP_VERSION  Kurulacak sürüm etiketi (ör. v1.3.4)
#   BILIUP_SHA256   (isteğe bağlı) Beklenen SHA-256. Verilmezse GitHub'ın release
#                   asset'i için yayınladığı özet kullanılır.
#   GH_TOKEN        GitHub API için token (workflow'da github.token)
set -euo pipefail

VERSION="${BILIUP_VERSION:?BILIUP_VERSION tanımlı değil}"
REPO="biliup/biliup"
ASSET="biliupR-${VERSION}-x86_64-linux.tar.xz"
INSTALL_DIR="${RUNNER_TEMP:-/tmp}/biliup-bin"

if [[ ! "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Geçersiz BILIUP_VERSION: v1.2.3 biçiminde olmalı" >&2
  exit 1
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo "biliup ${VERSION} indiriliyor…"
curl -fsSL --retry 3 --retry-delay 5 -o "$tmp/$ASSET" \
  "https://github.com/${REPO}/releases/download/${VERSION}/${ASSET}"

expected="${BILIUP_SHA256:-}"
if [[ -z "$expected" ]]; then
  expected="$(gh api "repos/${REPO}/releases/tags/${VERSION}" \
    --jq ".assets[] | select(.name == \"${ASSET}\") | .digest" | sed 's/^sha256://')"
fi
if [[ -z "$expected" ]]; then
  echo "SHA-256 özeti bulunamadı; güvenlik için kurulum durduruldu (BILIUP_SHA256 değişkenini tanımlayabilirsiniz)." >&2
  exit 1
fi
echo "${expected}  $tmp/$ASSET" | sha256sum --check --status \
  || { echo "SHA-256 doğrulaması başarısız; indirilen dosya beklenenle aynı değil." >&2; exit 1; }

tar -xJf "$tmp/$ASSET" -C "$tmp"
binary="$(find "$tmp" -type f -name biliup | head -n 1)"
if [[ -z "$binary" ]]; then
  echo "Arşivde biliup programı bulunamadı." >&2
  exit 1
fi
mkdir -p "$INSTALL_DIR"
install -m 0755 "$binary" "$INSTALL_DIR/biliup"
if [[ -n "${GITHUB_PATH:-}" ]]; then
  echo "$INSTALL_DIR" >> "$GITHUB_PATH"
fi
"$INSTALL_DIR/biliup" --version
