#!/usr/bin/env python3
"""NOIM変換ツールを置くEC2環境のCDKアプリ(入口)。"""
import os

import aws_cdk as cdk

from noim_stack import NoimConverterStack

app = cdk.App()

NoimConverterStack(
    app,
    "NoimConverterStack",
    # リージョンは東京に固定する。アカウントは、実行した人の認証情報から CDK が決める。
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region="ap-northeast-1",
    ),
)

cdk.Tags.of(app).add("Project", "noim-converter")
cdk.Tags.of(app).add("Environment", "dev")

app.synth()
