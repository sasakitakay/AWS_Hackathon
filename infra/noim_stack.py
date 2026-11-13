"""NOIM変換ツールを置くEC2環境のスタック(スタック1つ、EC2 1台)。"""
import os

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_cloudwatch as cloudwatch,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_s3 as s3,
    aws_s3_assets as s3_assets,
)
from constructs import Construct

# リポジトリのルート(このファイルの1つ上)。変換ツール本体(noim_converter.py と noim/)をここから配る。
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# 配布物に含めないもの(変換ツール本体だけを配るため)。名前が一致すれば、どの深さでも除外される。
ASSET_EXCLUDES = [
    "infra",
    "tests",
    "aidlc",
    ".kiro",
    ".git",
    ".github",
    ".venv",
    "cdk.out",
    "__pycache__",
    "*.pyc",
    "入力ファイル",
    "インタフェース仕様書",
    "*.xlsx",
    "*.md",
    ".gitignore",
    ".aidlc-version",
]

# EC2 起動時に作る実行コマンド。S3 の input/ を取得 → 変換 → output/ へ戻す。
# 値の差し込みは文字列の連結で行う(bash の変数展開と Python の書式指定が混ざらないようにする)。
NOIM_RUN_LINES = [
    "#!/bin/bash",
    "set -euo pipefail",
    'BUCKET="__BUCKET__"',
    'REGION="__REGION__"',
    'WORK="/var/noim"',
    'rm -rf "$WORK/input" "$WORK/output"',
    'mkdir -p "$WORK/input" "$WORK/output"',
    'aws s3 sync "s3://$BUCKET/input/" "$WORK/input/" --region "$REGION"',
    'python3 /opt/noim/noim_converter.py "$WORK/input" "$WORK/output" "$@" 2>&1 | tee -a /var/log/noim-run.log',
    'aws s3 sync "$WORK/output/" "s3://$BUCKET/output/" --region "$REGION"',
    'echo "完了: s3://$BUCKET/output/ に結果を置きました"',
]


class NoimConverterStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- ネットワーク: パブリックサブネット1つだけの専用VPC(NAT なし。インバウンドは開けない) ---
        vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=1,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                )
            ],
        )

        # アウトバウンドは HTTPS(443) のみ。インバウンドのルールは作らない。
        security_group = ec2.SecurityGroup(
            self,
            "InstanceSg",
            vpc=vpc,
            description="NOIM converter EC2 (no inbound, outbound 443 only)",
            allow_all_outbound=False,
        )
        security_group.add_egress_rule(
            ec2.Peer.any_ipv4(), ec2.Port.tcp(443), "HTTPS to AWS service endpoints"
        )

        # --- S3: 入力CSV(input/)と出力CSV(output/)の受け渡し ---
        data_bucket = s3.Bucket(
            self,
            "DataBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            # PoC: スタックを消すと中身ごと消える。
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # --- 変換ツール本体を S3 にアップロード(CDK アセット) ---
        tool_asset = s3_assets.Asset(
            self,
            "ToolAsset",
            path=REPO_ROOT,
            exclude=ASSET_EXCLUDES,
        )

        # --- EC2 の権限 ---
        role = iam.Role(
            self,
            "InstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonSSMManagedInstanceCore"
                )
            ],
        )
        data_bucket.grant_read(role, "input/*")
        data_bucket.grant_put(role, "output/*")
        tool_asset.grant_read(role)

        # --- 起動時の設定: ツールの配置と noim-run の作成 ---
        user_data = ec2.UserData.for_linux()
        user_data.add_commands(
            "set -euxo pipefail",
            "mkdir -p /opt/noim /var/noim/input /var/noim/output",
            "aws s3 cp " + tool_asset.s3_object_url + " /tmp/noim-tool.zip --region " + self.region,
            "python3 -m zipfile -e /tmp/noim-tool.zip /opt/noim",
            "rm -f /tmp/noim-tool.zip",
        )
        run_script = "\n".join(NOIM_RUN_LINES)
        run_script = run_script.replace("__BUCKET__", data_bucket.bucket_name)
        run_script = run_script.replace("__REGION__", self.region)
        user_data.add_commands(
            "cat > /usr/local/bin/noim-run <<'NOIM_EOF'\n" + run_script + "\nNOIM_EOF",
            "chmod +x /usr/local/bin/noim-run",
            "touch /var/log/noim-run.log",
        )

        # --- EC2 本体 ---
        instance = ec2.Instance(
            self,
            "Instance",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            instance_type=ec2.InstanceType("t3.micro"),
            machine_image=ec2.MachineImage.latest_amazon_linux2023(),
            role=role,
            security_group=security_group,
            user_data=user_data,
            # コードを変えて再デプロイしたとき、EC2 を作り直して新しいコードを確実に配る。
            user_data_causes_replacement=True,
            require_imdsv2=True,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/xvda",
                    volume=ec2.BlockDeviceVolume.ebs(
                        8,
                        volume_type=ec2.EbsDeviceVolumeType.GP3,
                        encrypted=True,
                    ),
                )
            ],
        )

        # --- 監視: EC2 のステータスチェック失敗(通知先は作らない) ---
        cloudwatch.Alarm(
            self,
            "StatusCheckFailedAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/EC2",
                metric_name="StatusCheckFailed",
                dimensions_map={"InstanceId": instance.instance_id},
                statistic="Maximum",
                period=Duration.minutes(1),
            ),
            threshold=0,
            evaluation_periods=5,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        # --- デプロイ後に表示する値 ---
        CfnOutput(self, "BucketName", value=data_bucket.bucket_name)
        CfnOutput(self, "InstanceId", value=instance.instance_id)
