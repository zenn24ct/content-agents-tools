# content-agents-tools

NVIDIA [Content Agents](https://github.com/NVIDIA-Omniverse/content-agents) を実運用するための補助ツール集。

Content Agents は 3D モデル(USD)に **VLM が材質を自動で割り当て**、さらに **AI がテクスチャを生成して貼る** パイプライン。
本体は多機能な反面、新しいアセットを1つ試すたびに「スケルタルメッシュの静的化 → config 作成 → 実行 → 出力探し」を手作業でやる必要がある。
このリポジトリはそこを **1コマンド化** し、加えて **材質ライブラリを自由に拡張** できるようにする。

> 本体（content-agents）は含まない。別途クローンして、その中に本ツールを配置して使う。

---

## 何ができるか

| ツール | できること |
|---|---|
| `newasset.sh` | 新しいアセットを **1コマンド** でパイプライン投入（下記4つを自動化） |
| `tools/asset_prep.py` | UsdSkel(スケルタルアニメ)の**自動検出＋静的メッシュ化**、config の自動生成 |
| `tools/add_materials.py` | 材質ライブラリの**拡張**（レシピYAMLから新材質を量産） |
| `tools/make_usdz.py` | パイプライン出力を**単体で開ける .usdz に梱包**（Quick Look / Blender 等で閲覧） |
| `recipes/` | 材質レシピと texture-agent 用の設定サンプル |

### 解決している主な問題

- **OVRTX が UsdSkel で落ちる** … スキニングを frame 0 で焼き込み、静的メッシュ化して回避（自動判定）
- **config 作成が毎回手作業** … 雛形をコピーしてパスを絶対パスで差し替える作業を自動化
- **標準の材質ライブラリが工業材質のみ**（金属/プラ/ガラス/塗装の74種）… 木材・布・革・陶器などを追加できる
- **出力 USD が単体で開けない** … `output.usd` は元アセットを参照する薄いレイヤなので、
  そのままでは他環境で開けない。フラット化＋依存同梱で 1 ファイルの `.usdz` にする

---

## セットアップ

```bash
# 1. 本体を用意（NVIDIA Content Agents）
git clone https://github.com/NVIDIA-Omniverse/content-agents.git
cd content-agents
# 本体の README に従って uv 等でセットアップし、.env に API キーを設定

# 2. 本ツールを clone して シンボリックリンクで配置
git clone https://github.com/<your-account>/content-agents-tools.git ~/content-agents-tools

ln -sf ~/content-agents-tools/newasset.sh .
mkdir -p tools materials_custom
ln -sf ~/content-agents-tools/tools/*.py tools/
ln -sf ~/content-agents-tools/recipes/recipe_starter.yaml materials_custom/
```

> **コピーではなくリンクにする理由**: ツールを直したときに「動かしている実体」と
> 「リポジトリの中身」がズレない。修正は `~/content-agents-tools` 側で行い、
> そのまま `git commit` / `git push` できる。

`newasset.sh` は本体の `run.sh`（バックエンド切替ラッパー）を呼ぶ。無い場合は下記を用意する:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"; source .venv/bin/activate
MODE="${1:-nim}"; CONFIG="${2:-apps/material_agent/configs/unified_example.yaml}"
case "$MODE" in
  claude|anthropic) export MA_VLM_BACKEND=anthropic MA_LLM_BACKEND=anthropic \
                           MA_VLM_MODEL=claude-sonnet-5 MA_LLM_MODEL=claude-sonnet-5 ;;
  nim|nvidia)       export MA_VLM_BACKEND=nim MA_LLM_BACKEND=nim \
                           MA_VLM_MODEL=google/gemma-4-31b-it MA_LLM_MODEL=google/gemma-4-31b-it ;;
esac
exec material-agent run "$CONFIG"
```

---

## 使い方

### 1. アセットに材質を割り当てる

```bash
./newasset.sh <名前> <USDパス> [参照画像...] [オプション]
```

```bash
# 参照画像は <USDのフォルダ>/thumbnails/ から自動検出される
./newasset.sh teapot assets_custom/teapot/teapot.usdz

# 参照画像を明示し、拡張ライブラリを使う
./newasset.sh chair assets_custom/chair/chair.usdc ref1.png ref2.png \
  --materials apps/material_agent/data/materials/material_libs_extended/materials.yaml
```

| オプション | 説明 |
|---|---|
| `--backend nim\|claude` | VLM バックエンド（既定 nim） |
| `--materials <path>` | 材質マニフェスト（既定は標準ライブラリ） |
| `--no-static` | スケルタル静的化をスキップ |
| `--no-run` | config を生成するだけ |
| `--force` | 同名 config を上書き |

内部の処理:
1. **UsdSkel を自動判定** → あれば frame 0 で焼き込み `<名前>_static.usd` を生成
2. **config を自動生成**（雛形の steps/プロンプトは維持したままパスだけ差し替え）
3. `run.sh` で実行
4. 出力パス（`apps/material_agent/configs/.<名前>/output/`）を表示

### 2. 材質ライブラリを拡張する

標準ライブラリは工業材質74種のみ。木材・布・革・陶器などを足す:

```bash
python tools/add_materials.py \
  --base-lib  apps/material_agent/data/materials/material_libs_default/materials_libs_v2.usd \
  --base-yaml apps/material_agent/data/materials/material_libs_default/materials.yaml \
  --recipe    materials_custom/recipe_starter.yaml \
  --out-dir   apps/material_agent/data/materials/material_libs_extended \
  --lib-name  materials_libs_extended
```

同梱の `recipes/recipe_starter.yaml` には24種（木材5 / 布・革6 / セラミック・石6 / マット塗装・紙ほか7）を収録。
これで **計98種** のライブラリが生成される（元のライブラリは変更しない）。

**仕組み**: 各 Material prim は OpenPBR の全パラメータを `inputs:*`（`base_color` / `base_metalness` /
`specular_roughness` / `transmission_weight` など）として公開している。
そこで **近い材質の prim をシェーダーネットワークごと複製 → inputs だけ差し替える**。
ネットワークを丸ごと引き継ぐので描画は保証される。

レシピの書き方:

```yaml
templates:
  metal: Stainless_Steel      # テンプレートに使う既存材質
  dielectric: Plastic_Red
  glass: Glass_Clear

materials:
  - name: "Wood Oak"
    description: "Warm medium-brown natural oak wood with a soft matte finish"  # VLMはこの説明文で選ぶ
    template: dielectric
    inputs:
      base_color: [0.26, 0.14, 0.06]   # 色はリニア空間
      base_metalness: 0.0              # 0=非金属 / 1=金属
      specular_roughness: 0.5          # 0=鏡面 〜 1=マット
      specular_weight: 0.5
```

> `description` は VLM が材質を選ぶ際の判断材料になるので、見た目を具体的に書くほど精度が上がる。

### 3. AI生成テクスチャを貼る（texture-agent）

材質割当だけでは単色PBR（正しい色・粗さ・金属感）で、木目や織り目の**模様は付かない**。
模様が欲しい場合は texture-agent で生成する:

```bash
# recipes/texture_example.yaml を編集して実行
texture-agent run recipes/texture_example.yaml -v
```

> **効きやすいアセット / 効きにくいアセット**
> パーツが多数のメッシュに分かれたアセット（例: ギター）は、パーツごとに UV が張られるため
> 生成テクスチャがよく乗る。一方、**全体が 1 メッシュのアセット**（例: 野球グローブ）は
> 箱投影 UV が 1 枚貼られるだけになり、模様がほぼ見えないことがある
> （`uv_scale_factor` を上げても改善しなかった）。元アセットの UV が整っているかが効き目を左右する。

### 4. 出力を単体で開ける .usdz にする

パイプラインの `output.usd` は元アセットを参照する薄いレイヤなので、そのファイル単体では他環境で開けない。
フラット化して依存を同梱した `.usdz` を作る:

```bash
python tools/make_usdz.py \
  apps/material_agent/configs/.<session>/output/output.usd \
  usdz_out/<name>.usdz \
  --source-usdz assets_custom/<name>/<original>.usdz \
  --arkit
```

- `--source-usdz` … 元アセットが `.usdz` だった場合は**必須**。
  中のテクスチャが `@0/foo.png@` というアーカイブ内パスで参照されており、
  展開しないと解決できず梱包に失敗する
- `--arkit` … macOS/iOS のクイックルックで開ける形式にする

---

## 既知のハマりどころ

実際に動かして判明した点（2026年7月時点）。

### VLM モデル
- `meta/llama-4-maverick-17b-128e-instruct` は **EOL（提供終了）** → 410 Gone
- material-agent は **1リクエストに複数画像**を送るため、マルチ画像対応モデルが必須
- 動作確認できたモデル: **`google/gemma-4-31b-it`**, `nvidia/nemotron-nano-12b-v2-vl`,
  `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`
- 使えない: `meta/llama-3.2-90b-vision-instruct`（1画像制限）

### 画像生成（texture-agent）
- 画像生成の NIM は **`https://ai.api.nvidia.com/v1/genai/{org}/{name}`** という別エンドポイント
  （`integrate.api.nvidia.com/v1/models` の一覧には出ないので「使えない」と誤認しやすい）
- 画像サイズは **768〜1344** のみ（512 は 422 エラー）

### レンダリングが暗すぎる

既定のままだと出力が全体に暗く、特に濃色の材質（革・ウォールナット等）はほぼ黒く潰れる。
原因はドームライト（ovrtx 同梱の StinsonBeach HDRI）の強度で、**OVRTX レンダーサービスを
起動する側の環境変数**で調整する:

```bash
export WU_OVRTX_DEFAULT_HDRI_INTENSITY=3000   # 既定 600
```

同梱の `scripts/start_ovrtx.sh` はこの値を設定済みのレンダーサービス起動スクリプト
（Xvfb の用意も含む）。

```bash
./scripts/start_ovrtx.sh          # 既定 port 8011 / DISPLAY :100
```

手元の計測では、野球グローブの被写体平均輝度が **23 → 63（約2.7倍）** になり、
後処理での明るさ補正が不要になった。config 側のパラメータではないので、
**レンダーサービスの再起動が必要**な点に注意。

> なお起動スクリプトを `sh`（dash）+ `set -u` で書くと、`.venv/bin/activate` が
> `OSTYPE` 未定義で落ちる。bash で実行し、activate の前後だけ `set +u` / `set -u` する。

### 上流の要修正点（2件）

本ツールでは対応できない、content-agents 本体側の問題。手元では以下のパッチをあてて動かした。

**1. Anthropic バックエンドが必ず失敗する**

`world_understanding/functions/models/vision_language_models.py` の `AnthropicVLM` が、
langchain のレスポンス `content`（テキストブロックの**リスト**）を文字列化せずに返すため、
呼び出し側の `.strip()` が `'list' object has no attribute 'strip'` で落ち、
predict が「zero successful predictions」で全滅する。

同ファイル内の `AnthropicVLM` の `return response.content` 3箇所を、リスト対応の変換に置き換える:

```python
def _content_to_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [p.get("text", "") for p in content
                 if isinstance(p, dict) and p.get("type") == "text"]
        return "\n".join(parts) if parts else str(content)
    return str(content)
```

**2. FLUX(klein/schnell) で画像が空になる**

`world_understanding/functions/models/image_generation_models.py` の `NIMImageGenerationModel.generate()`。
少ステップ蒸留モデル（`flux_2-klein-4b` など）は **`steps` を明示しないと空の artifact** が返り、
`Empty base64 in NIM image generation response` で失敗する。リクエストボディに既定値を追加する:

```python
if any(t in self._model_name.lower() for t in ("klein", "schnell")):
    body.setdefault("steps", 4)
```

### その他
- texture-agent で `UV_BAD_INTERPOLATION` が出るアセットは `uv_policy: force_projection` にする
- texture-agent の NIM 画像生成は **text-only**（img2img 非対応、参照画像は無視される）
- 材質ライブラリのサムネ生成（`material-agent generate-manifest`）は **NVCF クラウド前提** で、
  ローカル OVRTX を使わない。ただしサムネはパイプライン実行に不要

---

## 動作環境

- NVIDIA GPU 必須（OVRTX レンダリングのため。検証環境: RTX 6000 Ada / Ubuntu 24.04）
- レンダリングは OVRTX Rendering API をローカル起動し `RENDER_ENDPOINT` で指定
- API キー: `NVIDIA_API_KEY`（NIM）、`ANTHROPIC_API_KEY`（Claude を使う場合）

## ライセンス

本リポジトリのツール（`newasset.sh`, `tools/*.py`, `recipes/*`）は MIT License。
NVIDIA Content Agents 本体、および同梱の材質ライブラリ・アセットは含まれておらず、
それぞれ元の配布元のライセンスに従うこと。
