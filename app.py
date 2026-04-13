#!/usr/bin/env python3
import aws_cdk as cdk
from bluegreen_pipeline.vpc_stack      import VpcStack
from bluegreen_pipeline.ecr_stack      import EcrStack
from bluegreen_pipeline.ecs_stack      import EcsStack
from bluegreen_pipeline.pipeline_stack import PipelineStack

app = cdk.App()

env = cdk.Environment(
    account="544949538590",    # ← your real AWS account ID
    region="ap-south-1"        # ← Mumbai region
)

vpc_stack = VpcStack(app, "VpcStack", env=env)
ecr_stack = EcrStack(app, "EcrStack", env=env)
ecs_stack = EcsStack(app, "EcsStack",
                     vpc=vpc_stack.vpc,
                     repository=ecr_stack.repository,
                     env=env)
PipelineStack(app, "PipelineStack",
              ecr_repo=ecr_stack.repository,
              ecs_service=ecs_stack.service,
              ecs_cluster=ecs_stack.cluster,
              blue_tg=ecs_stack.blue_tg,
              green_tg=ecs_stack.green_tg,
              listener=ecs_stack.listener,
              env=env)

app.synth()