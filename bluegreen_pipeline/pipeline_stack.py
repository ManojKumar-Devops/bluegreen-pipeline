from aws_cdk import Stack, SecretValue
from aws_cdk import aws_codepipeline as cp
from aws_cdk import aws_codepipeline_actions as cpa
from aws_cdk import aws_codebuild as cb
from aws_cdk import aws_codedeploy as cd
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_iam as iam
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from constructs import Construct


class PipelineStack(Stack):
    def __init__(self, scope: Construct, id: str,
                 ecr_repo: ecr.Repository,
                 ecs_service: ecs.FargateService,
                 ecs_cluster: ecs.Cluster,
                 blue_tg: elbv2.ApplicationTargetGroup,
                 green_tg: elbv2.ApplicationTargetGroup,
                 listener: elbv2.ApplicationListener, **kwargs):
        super().__init__(scope, id, **kwargs)

        build_role = iam.Role(self, "BuildRole",
            assumed_by=iam.ServicePrincipal("codebuild.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonEC2ContainerRegistryPowerUser"
                )
            ],
            inline_policies={
                "EcrPublicPolicy": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "ecr-public:GetAuthorizationToken",
                                "sts:GetServiceBearerToken"
                            ],
                            resources=["*"]
                        )
                    ]
                )
            }
        )

        build_project = cb.PipelineProject(self, "BuildProject",
            project_name="bluegreen-build",
            role=build_role,
            build_spec=cb.BuildSpec.from_source_filename("buildspec.yml"),
            environment=cb.BuildEnvironment(
                build_image=cb.LinuxBuildImage.STANDARD_7_0,
                privileged=True
            ),
            environment_variables={
                "AWS_ACCOUNT_ID": cb.BuildEnvironmentVariable(
                    value=self.account
                ),
                "AWS_DEFAULT_REGION": cb.BuildEnvironmentVariable(
                    value=self.region
                )
            }
        )
        ecr_repo.grant_pull_push(build_project)

        codedeploy_app = cd.EcsApplication(self, "CdApp",
            application_name="bluegreen-codedeploy-app"
        )

        deploy_group = cd.EcsDeploymentGroup(self, "DeployGroup",
            application=codedeploy_app,
            deployment_group_name="bluegreen-deployment-group",
            service=ecs_service,
            blue_green_deployment_config=cd.EcsBlueGreenDeploymentConfig(
                blue_target_group=blue_tg,
                green_target_group=green_tg,
                listener=listener
            ),
            deployment_config=cd.EcsDeploymentConfig.ALL_AT_ONCE
        )

        src_out = cp.Artifact("SourceOutput")
        bld_out = cp.Artifact("BuildOutput")

        cp.Pipeline(self, "Pipeline",
            pipeline_name="bluegreen-pipeline",
            cross_account_keys=False,
            stages=[
                cp.StageProps(
                    stage_name="Source",
                    actions=[
                        cpa.GitHubSourceAction(
                            action_name="GitHub_Source",
                            owner="ManojKumar-Devops",
                            repo="bluegreen-pipeline",
                            branch="main",
                            oauth_token=SecretValue.secrets_manager(
                                "github-token"
                            ),
                            output=src_out
                        )
                    ]
                ),
                cp.StageProps(
                    stage_name="Build",
                    actions=[
                        cpa.CodeBuildAction(
                            action_name="Docker_Build",
                            project=build_project,
                            input=src_out,
                            outputs=[bld_out]
                        )
                    ]
                ),
                cp.StageProps(
                    stage_name="Deploy",
                    actions=[
                        cpa.CodeDeployEcsDeployAction(
                            action_name="BlueGreen_Deploy",
                            deployment_group=deploy_group,
                            task_definition_template_file=bld_out.at_path(
                                "taskdef.json"
                            ),
                            app_spec_template_file=bld_out.at_path(
                                "appspec.yml"
                            ),
                            container_image_inputs=[
                                cpa.CodeDeployEcsContainerImageInput(
                                    input=bld_out,
                                    task_definition_placeholder="IMAGE_URI"
                                )
                            ]
                        )
                    ]
                )
            ]
        )