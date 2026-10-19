#!/usr/bin/env bash
# MAXScript 문법 검사기 번들 생성 (Java 필요 — GitHub Actions 'build mxs checker' 에서 실행)
set -euo pipefail
REV=bfdd62e2e91f3402a198b42d6a53842111c8c84a   # HAG87/vscode-maxscript-lsp 고정 커밋 (MIT)
HERE=$(cd "$(dirname "$0")" && pwd)
WORK=$(mktemp -d)
git clone -q https://github.com/HAG87/vscode-maxscript-lsp "$WORK/lsp"
cd "$WORK/lsp" && git checkout -q "$REV"
npm ci --ignore-scripts --no-audit --no-fund
npm run generate
cp "$HERE/check.ts" src/mxs_check.ts
npx esbuild src/mxs_check.ts --bundle --platform=node --format=cjs --minify --outfile="$HERE/mxs_check.cjs"
cp LICENSE "$HERE/LICENSE-vscode-maxscript-lsp"
printf 'x = 1\nfn f a = (a + 1)\n' | node "$HERE/mxs_check.cjs"
