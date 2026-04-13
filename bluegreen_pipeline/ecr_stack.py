from aws_cdk import Stack, RemovalPolicy
from aws_cdk import aws_ecr as ecr
from constructs import Construct

class EcrStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs):
        super().__init__(scope, id, **kwargs)

        self.repository = ecr.Repository(self, "AppRepo",
            repository_name="bluegreen-app",
            removal_policy=RemovalPolicy.DESTROY,
            lifecycle_rules=[
                ecr.LifecycleRule(
                    max_image_count=10,
                    description="Keep last 10 images"
                )
            ]
        )