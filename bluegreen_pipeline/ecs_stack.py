from aws_cdk import Stack, Duration, CfnOutput, RemovalPolicy
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_iam as iam
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_logs as logs
from constructs import Construct


class EcsStack(Stack):
    def __init__(self, scope: Construct, id: str,
                 vpc: ec2.Vpc,
                 repository: ecr.Repository, **kwargs):
        super().__init__(scope, id, **kwargs)

        # ── ECS Cluster ─────────────────────────────────────────────
        self.cluster = ecs.Cluster(self, "Cluster",
            cluster_name="bluegreen-cluster",
            vpc=vpc,
            container_insights_v2=ecs.ContainerInsights.ENABLED
        )

        # ── CloudWatch Log Group ─────────────────────────────────────
        log_group = logs.LogGroup(self, "AppLogGroup",
            log_group_name="/ecs/bluegreen-app",
            removal_policy=RemovalPolicy.DESTROY
        )

        # ── Task execution IAM role ──────────────────────────────────
        self.exec_role = iam.Role(self, "TaskExecRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonECSTaskExecutionRolePolicy"
                )
            ]
        )

        # ── Task definition ──────────────────────────────────────────
        task_def = ecs.FargateTaskDefinition(self, "TaskDef",
            memory_limit_mib=512,
            cpu=256,
            execution_role=self.exec_role,
            family="bluegreen-taskdef"
        )

        task_def.add_container("AppContainer",
            container_name="bluegreen-app",
            image=ecs.ContainerImage.from_ecr_repository(
                repository, tag="latest"
            ),
            port_mappings=[ecs.PortMapping(container_port=5000)],
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="bluegreen",
                log_group=log_group
            ),
            environment={"APP_ENV": "production"}
        )

        # ── Security Groups ──────────────────────────────────────────
        self.alb_sg = ec2.SecurityGroup(self, "AlbSg",
            vpc=vpc,
            description="ALB security group",
            allow_all_outbound=True
        )
        self.alb_sg.add_ingress_rule(
            ec2.Peer.any_ipv4(), ec2.Port.tcp(80),   "HTTP prod")
        self.alb_sg.add_ingress_rule(
            ec2.Peer.any_ipv4(), ec2.Port.tcp(8080), "HTTP test")

        self.svc_sg = ec2.SecurityGroup(self, "SvcSg",
            vpc=vpc,
            description="ECS service security group",
            allow_all_outbound=True
        )
        self.svc_sg.add_ingress_rule(
            self.alb_sg, ec2.Port.tcp(5000), "From ALB only")

        # ── Application Load Balancer ────────────────────────────────
        self.alb = elbv2.ApplicationLoadBalancer(self, "ALB",
            vpc=vpc,
            internet_facing=True,
            security_group=self.alb_sg,
            load_balancer_name="bluegreen-alb",
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PUBLIC
            )
        )

        # ── Blue Target Group (production port 80) ───────────────────
        self.blue_tg = elbv2.ApplicationTargetGroup(self, "BlueTG",
            target_group_name="bluegreen-blue-tg",
            target_type=elbv2.TargetType.IP,
            port=5000,
            protocol=elbv2.ApplicationProtocol.HTTP,
            vpc=vpc,
            health_check=elbv2.HealthCheck(
                path="/health",
                interval=Duration.seconds(30),
                healthy_threshold_count=2,
                unhealthy_threshold_count=3,
                timeout=Duration.seconds(5)
            ),
            deregistration_delay=Duration.seconds(30)
        )

        # ── Green Target Group (test port 8080) ──────────────────────
        self.green_tg = elbv2.ApplicationTargetGroup(self, "GreenTG",
            target_group_name="bluegreen-green-tg",
            target_type=elbv2.TargetType.IP,
            port=5000,
            protocol=elbv2.ApplicationProtocol.HTTP,
            vpc=vpc,
            health_check=elbv2.HealthCheck(
                path="/health",
                interval=Duration.seconds(30),
                healthy_threshold_count=2,
                unhealthy_threshold_count=3,
                timeout=Duration.seconds(5)
            ),
            deregistration_delay=Duration.seconds(30)
        )

        # ── Listeners — MUST be created before ECS Service ──────────
        self.listener = self.alb.add_listener("ProdListener",
            port=80,
            default_target_groups=[self.blue_tg]
        )

        self.test_listener = self.alb.add_listener("TestListener",
            port=8080,
            default_target_groups=[self.green_tg]
        )

        # ── Fargate Service with CODE_DEPLOY controller ──────────────
        self.service = ecs.FargateService(self, "Service",
            cluster=self.cluster,
            task_definition=task_def,
            service_name="bluegreen-service",
            desired_count=2,
            min_healthy_percent=100,
            max_healthy_percent=200,
            security_groups=[self.svc_sg],
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            deployment_controller=ecs.DeploymentController(
                type=ecs.DeploymentControllerType.CODE_DEPLOY
            )
        )

        # ── KEY FIX: Wire ALB to service via CfnService ──────────────
        # Must happen AFTER listeners are created so TGs are attached
        cfn_svc = self.service.node.default_child

        cfn_svc.load_balancers = [
            ecs.CfnService.LoadBalancerProperty(
                container_name="bluegreen-app",
                container_port=5000,
                target_group_arn=self.blue_tg.target_group_arn
            )
        ]

        # ── KEY FIX: Explicit dependency — service waits for both ────
        # listeners to finish before CloudFormation creates ECS Service
        self.service.node.add_dependency(self.listener)
        self.service.node.add_dependency(self.test_listener)
        self.service.node.add_dependency(self.alb)

        # ── Stack Outputs ────────────────────────────────────────────
        CfnOutput(self, "ALBDnsName",
            value=self.alb.load_balancer_dns_name,
            description="Open this URL to test the app"
        )
        CfnOutput(self, "ExecRoleArn",
            value=self.exec_role.role_arn,
            description="Copy this into taskdef.json executionRoleArn"
        )