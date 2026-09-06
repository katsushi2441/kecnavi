# Kurage 通報先ナビ (kecnavi) — Kurage Emergency Contact Navigator

困りごとから「どこに言えばいいか」を一発で答えるナビ。名古屋市が初期対象。

- 公開: https://kurage.exbridge.jp/kecnavi.php/
- 困りごと別ページ `/c/<slug>`（道路・街路灯・不法投棄・ごみ・漏水・警察・火事救急・災害・消費者・児童虐待・総合案内）
- 区別ページ `/ku/<slug>`（16区の土木事務所・環境事業所・区役所）
- 住所→区判定 `/api/resolve?q=住所`（国土地理院 地名検索API）

## 設計の芯

1. 電話番号・受付時間・URLは公式一次情報から取り、出典を必ず添える（`data/` に時点を記録）
2. 名古屋市サイトの文章は転載しない（同サイトの再利用規約は改変不可・引用のみ）。事実とリンクだけを使う
3. 緊急時は 110/119 を最初に出す。案内であって通報の代行ではない
4. 議員事務所・政党支部が「自らの情報発信ページ」として運用できる形（誰でも見られる一般的な案内）

## 動かす

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 18381
```

`systemd/kecnavi.service` を `~/.config/systemd/user/` に置いて `systemctl --user enable --now kecnavi`。
公開は `php/kecnavi.php`（透過プロキシ）を Web サーバーに置き、同ディレクトリの `kecnavi_config.php` で
`define('KECNAVI_BACKEND', 'http://あなたのサーバー:18381');` を定義する。

## データ

- `data/wards.json` — 16区の土木事務所（電話）・環境事業所（電話・住所・受付時間）・区役所（所在地・座標）
- `data/contacts.json` — 困りごと別の連絡順（番号・受付時間・出典URL）

他の自治体に展開するときは、この2ファイルを差し替える。

## 出典

土木事務所=名古屋市 緑政土木局「連絡先一覧」／環境事業所=名古屋市「各区の環境事業所」／
区役所の所在地・座標=名古屋市オープンデータ「施設カルテ」(CC BY 4.0)／全国共通番号=各省庁の公式ページ。

## License

MIT
