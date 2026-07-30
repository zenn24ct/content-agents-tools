#!/usr/bin/env bash
# OVRTX レンダーサービスをローカル起動する。
#
#   ./scripts/start_ovrtx.sh
#
# content-agents のチェックアウト直下から実行するか、CA_ROOT で場所を指定する。
# 起動後、content-agents 側の .env に RENDER_ENDPOINT=http://localhost:<PORT> を設定する。
#
# SSH 越しに起動するときは、セッション終了で落ちないよう次のように叩く:
#   ssh -f <host> "nohup setsid ~/content-agents-tools/scripts/start_ovrtx.sh > /tmp/ovrtx.log 2>&1 < /dev/null &"
set -eu

CA_ROOT="${CA_ROOT:-$HOME/content-agents}"
PORT="${OVRTX_PORT:-8011}"
DISP="${OVRTX_DISPLAY_NUM:-100}"

cd "$CA_ROOT"

# venv の activate は OSTYPE 等の未定義変数を読むので、この間だけ -u を外す
set +u
. .venv/bin/activate
set -u

export WU_OVRTX_VENV_DIR="${WU_OVRTX_VENV_DIR:-$CA_ROOT/.ovrtx_venv}"
export WU_OVRTX_AUTO_PROVISION=0
export OVRTX_RENDER_MODE=pt
export OVRTX_LOG_LEVEL=warn
export OVRTX_DAEMON_START_TIMEOUT=600
export OVRTX_DAEMON_RENDER_TIMEOUT=1800

# ドームライト(既定HDRI=StinsonBeach)の強度。既定 600 だと出力が暗すぎる。
export WU_OVRTX_DEFAULT_HDRI_INTENSITY="${WU_OVRTX_DEFAULT_HDRI_INTENSITY:-3000}"

# ヘッドレス環境用に仮想ディスプレイを用意する
rm -f "/tmp/.X${DISP}-lock" "/tmp/.X11-unix/X${DISP}" 2>/dev/null || true
Xvfb ":${DISP}" -screen 0 1024x768x24 +extension GLX -nolisten tcp &
echo $! > "/tmp/ovrtx_xvfb_${DISP}.pid"
export DISPLAY=":${DISP}"
sleep 2

cd apps/ovrtx_rendering_api
exec python -m uvicorn service.main:app --host 127.0.0.1 --port "$PORT"
