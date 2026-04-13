# AWS CDK Blue/Green Deployment Pipeline

A production-grade CI/CD pipeline built on AWS that delivers **zero-downtime deployments** using a Blue/Green strategy. Every code push to GitHub automatically builds, tests, and deploys a containerized application to Amazon ECS Fargate — with instant rollback capability and no service interruption.

---

## Overview

This project demonstrates a fully automated deployment pipeline where infrastructure is defined as code using AWS CDK (Python). The pipeline handles everything from source code changes to live traffic shifting — without any manual intervention.

The application runs as a containerized Flask service on Amazon ECS Fargate, fronted by an Application Load Balancer that manages traffic between Blue (current) and Green (new) environments during every deployment.

---

## Architecture

```
GitHub → CodePipeline → CodeBuild → ECR → CodeDeploy → ECS Fargate → ALB → Users
```

When a developer pushes code to the `main` branch, CodePipeline detects the change and orchestrates the full deployment flow. CodeBuild compiles the Docker image and stores it in ECR. CodeDeploy then launches a new Green environment alongside the existing Blue environment, validates it through health checks, and atomically shifts all traffic to Green — retiring the old Blue environment only after the new one is confirmed healthy.

---

## How Blue/Green Deployment Works

The ALB maintains two listeners — production traffic on port 80 and test traffic on port 8080. During a deployment:

1. New Green tasks start and register with the test listener on port 8080
2. CodeDeploy runs health checks against the Green environment
3. Once all health checks pass, the ALB shifts 100% of production traffic to Green
4. The old Blue tasks are gracefully terminated

If health checks fail at any point, CodeDeploy automatically rolls back to the Blue environment. Users experience zero downtime throughout the entire process.

---

## Infrastructure Components

| Layer | Service | Role |
|-------|---------|------|
| Networking | Amazon VPC | Isolated network with public and private subnets across 2 availability zones |
| Registry | Amazon ECR | Private Docker image repository with lifecycle policies |
| Compute | ECS Fargate | Serverless container execution — no EC2 instances to manage |
| Load Balancing | Application Load Balancer | Routes production and test traffic, manages Blue/Green cutover |
| Source Control | GitHub | Triggers pipeline on every push to main branch |
| Build | AWS CodeBuild | Compiles Docker image, runs build steps, pushes to ECR |
| Deployment | AWS CodeDeploy | Orchestrates Blue/Green traffic shifting and rollback |
| Pipeline | AWS CodePipeline | Coordinates the end-to-end Source → Build → Deploy flow |
| IaC | AWS CDK (Python) | All infrastructure defined and deployed as Python code |

---

## CDK Stack Breakdown

The infrastructure is split into four independent CDK stacks, each with a single responsibility.

**VpcStack** provisions the network foundation — a VPC with public subnets for the load balancer and private subnets for the application containers, with a NAT Gateway for outbound internet access.

**EcrStack** creates the private container registry where Docker images are stored and versioned. A lifecycle policy retains only the last 10 images to manage storage costs.

**EcsStack** is the core of the deployment — it provisions the ECS cluster, defines the Fargate task, creates the Application Load Balancer with two target groups (Blue and Green), and configures the ECS service with a CodeDeploy deployment controller.

**PipelineStack** wires the CI/CD pipeline together — CodePipeline monitors GitHub for changes, CodeBuild handles the Docker build and ECR push, and a CodeDeploy deployment group handles the Blue/Green traffic management.

---

## Application

The deployed application is a Python Flask REST API running under Gunicorn, containerised using a minimal Alpine Linux base image. It exposes two endpoints:

- **/** returns deployment metadata including version, hostname, and environment
- **/health** returns a health status used by the ALB and CodeDeploy for readiness checks

The container image is built targeting `linux/amd64` to ensure compatibility with ECS Fargate's Intel-based infrastructure.

---

## Prerequisites

- AWS account with an IAM user (AdministratorAccess)
- AWS CLI configured with IAM credentials
- Node.js 22.x or 24.x
- Python 3.9+
- AWS CDK v2
- Docker Desktop
- GitHub account with a Classic Personal Access Token (repo + admin:repo_hook scopes)

---

## Deployment Order

The stacks have hard dependencies and must be deployed in this exact sequence:

**VpcStack → EcrStack → Push Docker image → EcsStack → PipelineStack**

The Docker image must exist in ECR before EcsStack deploys because ECS attempts to start tasks immediately upon service creation. Deploying EcsStack before pushing an image causes all tasks to fail at the image pull step.

After EcsStack deploys, the IAM execution role ARN printed in the stack outputs must be updated in `taskdef.json` before deploying PipelineStack. This role ARN is unique per deployment and cannot be predicted in advance.

---

## CI/CD Flow

Once all stacks are deployed, the pipeline is fully automated. A developer only needs to push code — the rest happens automatically.

The typical end-to-end time from `git push` to traffic shifted to the new version is approximately 4 to 6 minutes, broken down as:

- Source detection and pipeline trigger — under 30 seconds
- Docker image build and ECR push — 2 to 3 minutes
- Green task launch and health checks — 1 to 2 minutes
- Traffic cutover — under 10 seconds

---

## Key Design Decisions

**Fargate over EC2** — Fargate removes the operational overhead of managing EC2 instances, patching, and capacity planning. The trade-off is slightly higher per-unit cost, which is acceptable for this workload size.

**CodeDeploy ALL_AT_ONCE** — The deployment config performs an immediate full cutover rather than a gradual canary or linear shift. This is appropriate for development and staging workloads. A production environment would benefit from `CANARY_10_PERCENT_5_MINUTES` to detect regressions before full cutover.

**Separate CDK stacks** — Splitting infrastructure into four stacks allows independent updates. Changing the pipeline configuration does not require redeploying the VPC or ECS service, which reduces deployment risk and time.

**Private subnets for ECS tasks** — Application containers run in private subnets with no direct internet exposure. All inbound traffic flows through the ALB in the public subnet, and outbound traffic routes through the NAT Gateway.

---

## Cost Estimate

Running this infrastructure continuously costs approximately:

| Resource | Daily Cost (approx) |
|----------|-------------------|
| Application Load Balancer | ₹16 |
| NAT Gateway | ₹90 |
| ECS Fargate (2 tasks) | ₹20 |
| ECR storage | Negligible |
| CodeBuild (first 100 min/month free) | ₹0 |

**Recommended:** Destroy the stack after practice sessions to avoid ongoing charges. All infrastructure can be recreated in under 15 minutes from code.

---

## Lessons Learned

Working through this project surfaced several non-obvious AWS and tooling behaviours worth documenting.

**Apple Silicon compatibility** — Docker builds on M-series Macs default to `arm64`. ECS Fargate runs on Intel hardware and requires `linux/amd64`. The `--provenance=false` flag is additionally required when pushing to ECR with Docker buildx, as ECR cannot resolve the OCI index manifest that buildx produces by default.

**CDK stack dependency ordering** — CDK passes live AWS resource objects between stacks at synthesis time. PipelineStack receives the ECS service, target groups, and ALB listener as constructor arguments from EcsStack. If EcsStack has not been deployed, those ARNs do not exist and the deployment fails immediately.

**IAM role ARN drift** — CDK generates unique suffixes for IAM role names on every fresh stack deployment. The `taskdef.json` file references this ARN directly, so it must be updated after any EcsStack redeploy. Automating this update in the build process prevents future drift.

**CODE_DEPLOY controller exclusivity** — ECS services configured with a CodeDeploy deployment controller cannot be restarted using the standard ECS force-new-deployment command. All deployments must go through CodeDeploy, which owns the deployment lifecycle for Blue/Green services.

**Classic PAT requirement** — AWS CodePipeline's GitHub webhook integration requires a Classic Personal Access Token with `admin:repo_hook` scope. Fine-grained tokens do not support the webhook registration API that CodePipeline uses.

---

## Tech Stack

AWS CDK (Python) · Amazon ECS Fargate · Amazon ECR · AWS CodePipeline · AWS CodeBuild · AWS CodeDeploy · Application Load Balancer · Amazon VPC · Python Flask · Gunicorn · Docker · GitHub

---

## Author

**Manojkumar** · [github.com/ManojKumar-Devops](https://github.com/ManojKumar-Devops)
