# 導入手順（Kurage 通報先ナビ / kecnavi）

## 1. 動かす（5分）

```
cd kecnavi
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 18381
```

`http://サーバー:18381/` で動きます。外部APIは国土地理院の地名検索（無料・キー不要）だけです。

## 2. 常駐させる（systemd user unit）

```
cp systemd/kecnavi.service ~/.config/systemd/user/
# WorkingDirectory / ExecStart のパスを自分の置き場所に直す
systemctl --user daemon-reload
systemctl --user enable --now kecnavi.service
```

## 3. 公開する（PHPが動くWebサーバーに透過プロキシを置く）

`php/kecnavi.php` を公開ディレクトリに置き、同じディレクトリに `kecnavi_config.php` を作ります。

```php
<?php define('KECNAVI_BACKEND', 'http://あなたのサーバー:18381');
```

`https://あなたのドメイン/kecnavi.php/` で公開されます（末尾のスラッシュ必須）。
ページ内のリンクとAPI呼び出しは、プロキシ越しでも直アクセスでも動くように接頭辞を自動で切り替えます。

## 4. 自分の自治体に差し替える（ここが本体）

編集するのは2ファイルだけです。

| ファイル | 中身 | 差し替え方 |
| --- | --- | --- |
| `data/wards.json` | 区（市町村）ごとの窓口：名称・電話・住所・受付時間・座標・出典URL | 自治体の公式ページから番号と住所を転記。座標は国土地理院地図などで取得 |
| `data/contacts.json` | 困りごと別の「連絡する順番」：番号・受付時間・公式URL・FAQ | 自治体の窓口構成に合わせて steps を並べ替える |

`asof` にデータの時点を必ず入れてください。画面と構造化データに表示されます。

住所→区の判定は、地名検索の結果ラベルに含まれる「◯◯市◯◯区」を最優先し、
無ければ `wards.json` の区役所座標に最も近い区で補います。政令市以外（区が無い自治体）では
`wards` を1件にすれば市全体の窓口として動きます。

## 5. 守ってほしいこと

- 自治体サイトの文章をそのまま転載しない（多くの自治体サイトは改変不可・引用のみ）。番号・住所・時間の事実とリンクだけを使い、説明文は自分で書く
- 緊急連絡先（110/119）はページ上部に出したまま残す
- 番号を変えたら `asof` も更新する
