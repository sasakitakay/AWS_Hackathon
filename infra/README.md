# NOIM変換ツール: AWS環境の構築手順(CDK)

EC2を1台作り、その上でNOIM変換ツールを実行できる環境を作ります。**CDKを実行するのは人間(あなた)です。** AWS CLI は使いません(ブラウザ操作と、CloudShell のコマンドだけで完了します)。

## 作られるもの

| リソース | 内容 |
|---|---|
| EC2 | Amazon Linux 2023、t3.micro、東京(ap-northeast-1)。インバウンドなし、アウトバウンドは443のみ |
| VPC | 専用のVPC(パブリックサブネット1つ、NATなし) |
| S3バケット | `input/` と `output/` の置き場。スタックを削除すると中身ごと消えます |
| IAMロール | SSM接続、S3の `input/` の読み取り、`output/` への書き込み、ツールのコードの取得だけ |
| CloudWatchアラーム | EC2のステータスチェック失敗(通知先は作りません) |

概算コストは、24時間動かして月約15ドルです。使わないときは「6. 後片付け」で消せます。

## 前提

- AWSアカウントと、CDK を実行できる権限(CloudFormation、IAM、EC2、S3、SSM の作成)
- リージョンは **東京(ap-northeast-1)**。ブラウザ右上のリージョン表示を「アジアパシフィック(東京)」にしてから CloudShell を開く
- このリポジトリ一式を CloudShell に持ち込めること(`git clone`、または zip をアップロード)

## 1. CloudShell を開く

AWSマネジメントコンソール右上のターミナルアイコン(CloudShell)を押します。1

## 2. コードを CloudShell に置く

どちらか一方です。

```bash
# Git が使える場合(<URL> はこのリポジトリのURL)
git clone <URL> noim && cd noim
```

zip の場合は、CloudShell 右上の「アクション」→「ファイルのアップロード」で zip をアップロードし、`unzip <zip名> -d noim && cd noim` で展開します。

## 3. CDK の準備(初回のみ)

```bash
cd infra
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

以降、CDK のコマンドは `npx aws-cdk@2 ...` で実行します(グローバルインストール不要)。

CloudShell では、**CDK のコマンドを実行する前に、毎回(CloudShell を開き直したときも)次を実行してください。** CloudShell のホームディレクトリの権限が広いため、これが無いと `Cannot use the jsii package cache` というエラーになります。

```bash
export JSII_RUNTIME_PACKAGE_CACHE=disabled
```

(`Node 20 is end-of-life` という `!!` で囲まれた警告が出ますが、警告だけで、動作には影響しません。)

アカウントとリージョンごとに1回、CDK の準備(ブートストラップ)をします。

```bash
npx aws-cdk@2 bootstrap
```

## 4. 確認してデプロイ

```bash
npx aws-cdk@2 synth
npx aws-cdk@2 diff
npx aws-cdk@2 deploy
```

- `synth` でエラーが出なければ、構成は正しく組み立てられています。
- `deploy` の途中で変更内容の確認(y/n)が出たら、内容を見て `y` を入力します。
- 終わると `BucketName` と `InstanceId` が表示されます。控えてください。

デプロイ後、EC2 が起動してツールを配置し終えるまで **数分** かかります。

## 5. 動作確認(ブラウザ操作)

1. **入力をアップロード:** S3 コンソールで `BucketName` のバケットを開き、`input/` フォルダを作って、3種のCSV(`t_mst_vxm_node_info_*.csv`、`t_mst_vxm_entity_info_*.csv`、`t_mst_vxm_service_*.csv`)をアップロードします。
2. **EC2 に接続:** EC2 コンソールで `InstanceId` のインスタンスを選び、「接続」→「セッションマネージャー」→「接続」。
   - 接続できない場合は、起動から数分待って再度試します。
3. **変換を実行:** 開いた画面で次を入力します。

   ```bash
   sudo noim-run
   ```

   エラーなく「完了」と出れば成功です。エラーがあればメッセージ(ファイル名つき)が表示されます。
4. **出力を確認:** S3 の `output/` に `resourceInfo_*.csv` の8ファイルができています。ダウンロードして使います。

実行の記録は EC2 の `/var/log/noim-run.log` に残ります。起動時の配置に失敗したと思われる場合は、`sudo cat /var/log/cloud-init-output.log` で確認できます。

## 6. 後片付け(使い終わったら)

必要な出力を先にダウンロードしてから、CloudShell で実行します。

```bash
cd ~/noim/infra
. .venv/bin/activate
npx aws-cdk@2 destroy
```

S3 の中身も含めて、作ったものがすべて消えます。

## コードを変えたとき(元に戻したいとき)

- 変換ツールのコードを変えて `npx aws-cdk@2 deploy` をやり直すと、EC2 が新しく作られ、新しいコードで置き換わります(S3 のデータは残ります)。
- 前の版に戻したい場合は、Git で前の版に戻してから `deploy` します。
- デプロイが途中で失敗した場合は、CloudFormation が自動でもとの状態に戻します。原因を確認して、もう一度 `deploy` します。

## 困ったとき

| 症状 | 確認すること |
|---|---|
| `synth` で `ModuleNotFoundError` | `. .venv/bin/activate` を実行したか。`pip install -r requirements.txt` は成功したか |
| `Cannot use the jsii package cache` | `export JSII_RUNTIME_PACKAGE_CACHE=disabled` を実行してから、もう一度 |
| `bootstrap` や `deploy` が権限エラー | コンソールにログインしているユーザーの権限(CloudFormation、IAM、EC2、S3、SSM) |
| セッションマネージャーで接続できない | 起動後、数分待つ。インスタンスの状態が「実行中」か、ステータスチェックが合格か |
| `sudo noim-run` で `input/` が空 | S3 の `input/` に3種のCSVを置いたか(フォルダ名の大文字小文字も確認) |
| 入力ディレクトリのエラー | `input/` 直下に3種のCSV以外のファイルを置いていないか |
