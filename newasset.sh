#!/usr/bin/env bash
# 新規カスタムアセットを1コマンドでパイプライン投入する。
#
#   ./newasset.sh <名前> <USDパス|ディレクトリ> [参照画像...] [オプション]
#
# 例:
#   ./newasset.sh chair ~/content-agents/assets_custom/chair/chair.usdc
#   ./newasset.sh chair assets_custom/chair ref1.png ref2.png --backend claude
#
# やること: ①UsdSkel自動判定→静的化 ②config自動生成 ③run.shで実行 ④出力パス表示
#
# オプション:
#   --backend nim|claude   バックエンド(既定 nim)
#   --materials <path>     マテリアルmanifest(既定=material_libs_default)
#   --no-static            スケルタル静的化をスキップ
#   --no-run               configを生成するだけで実行しない
#   --force                同名configを上書き
set -euo pipefail
cd "$(dirname "$0")"

if [ $# -lt 2 ]; then
  sed -n '2,20p' "$0"; exit 1
fi

NAME="$1"; USD="$2"; shift 2

BACKEND=nim
PREP_ARGS=()
RUN=1
while [ $# -gt 0 ]; do
  case "$1" in
    --backend)   BACKEND="$2"; shift 2;;
    --materials) PREP_ARGS+=(--materials "$2"); shift 2;;
    --no-static) PREP_ARGS+=(--no-static); shift 1;;
    --force)     PREP_ARGS+=(--force); shift 1;;
    --no-run)    RUN=0; shift 1;;
    -*)          echo "不明なオプション: $1" >&2; exit 1;;
    *)           PREP_ARGS+=(--ref "$1"); shift 1;;  # 位置引数=参照画像
  esac
done

source .venv/bin/activate

echo ">> アセット準備中 (name=$NAME)..."
PREP_OUT="$(python tools/asset_prep.py --name "$NAME" --usd "$USD" "${PREP_ARGS[@]}")"
echo "$PREP_OUT"

CONFIG="$(printf '%s\n' "$PREP_OUT" | sed -n 's/^CONFIG=//p')"
SESSION="$(printf '%s\n' "$PREP_OUT" | sed -n 's/^SESSION=//p')"
OUTDIR="apps/material_agent/configs/.${SESSION}/output"

if [ "$RUN" -eq 0 ]; then
  echo ">> --no-run 指定: 実行はスキップ。config=$CONFIG"
  echo ">> 実行するには: ./run.sh $BACKEND $CONFIG"
  exit 0
fi

echo ">> パイプライン実行 (backend=$BACKEND)..."
./run.sh "$BACKEND" "$CONFIG"

echo
echo ">> 完了。出力: $OUTDIR"
ls -la "$OUTDIR" 2>/dev/null || echo "   (出力ディレクトリが見つかりません。ログを確認してください)"
