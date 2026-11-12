#!/usr/bin/env bash
# One command: contract tests + wasm build + guard tests + demo. Exits non-zero on any failure.
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.cargo/bin:$PATH"
echo "== Rugwall (formerly IntentGuard) =="; echo "== 1/4 contract unit tests =="; (cd contract && cargo test)
echo "== 2/4 contract wasm build =="; (cd contract && cargo near build non-reproducible-wasm && ls -l target/near/intentguard.wasm)
echo "== 3/4 guard unit tests ==";   (cd guard && python3 -m unittest discover -s tests -v)
echo "== 4/4 demo ==";               python3 guard/demo.py
