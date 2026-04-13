# 🚀 AWS CDK Blue/Green Deployment Pipeline

A production-ready **Blue/Green deployment pipeline** on AWS ECS Fargate using AWS CDK (Python), CodePipeline, CodeBuild, and CodeDeploy — with zero-downtime deployments on every `git push`.

---

## 📐 Architecture

```
GitHub → CodePipeline → CodeBuild → ECR → CodeDeploy (Blue/Green) → ECS Fargate → ALB
```

| Component | AWS Service | Purpose |
|-----------|-------------|---------|
| Source | CodePipeline + GitHub | Triggers on every push to `main` |
| Build | CodeBuild | Builds Docker image, pushes to ECR |
| Registry | ECR | Stores Docker images |
| Deploy | CodeDeploy | Blue/Green traffic swap |
| Compute | ECS Fargate | Runs containerized Flask app |
| Load Balancer | ALB | Routes production (port 80) and test (port 8080) traffic |
| Networking | VPC | Public + private subnets across 2 AZs |

### Blue/Green Flow

```
Current live traffic → Blue tasks (port 80)
New deployment      → Green tasks start (port 8080 test listener)
Health check passes → ALB shifts 100% traffic to Green
Old Blue tasks      → Terminated (zero downtime)
```

---

## 📁 Project Structure

```
bluegreen-pipeline/
├── app.py                          # CDK entry point — wires all stacks
├── requirements.txt                # CDK Python dependencies
├── cdk.json                        # CDK configuration
├── cdk.context.json                # CDK context cache
├── buildspec.yml                   # CodeBuild — Docker build + push instructions
├── appspec.yml                     # CodeDeploy — Blue/Green swap config
├── taskdef.json                    # ECS task definition template
│
├── bluegreen_pipeline/
│   ├── __init__.py
│   ├── vpc_stack.py                # VPC, subnets, NAT gateway
│   ├── ecr_stack.py                # ECR private repository
│   ├── ecs_stack.py                # ECS cluster, ALB, Blue/Green target groups, Fargate service
│   └── pipeline_stack.py          # CodePipeline + CodeBuild + CodeDeploy
│
└── app/
    ├── app.py                      # Flask application
    ├── requirements.txt            # Flask + Gunicorn
    └── Dockerfile                  # Container image definition
```

---

## ✅ Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.9+ | https://python.org |
| Node.js | 22.x or 24.x | https://nodejs.org |
| AWS CDK | 2.x | `npm install -g aws-cdk` |
| AWS CLI | 2.x | https://aws.amazon.com/cli |
| Docker Desktop | 28.x+ | https://docs.docker.com/get-docker |
| Git | any | https://git-scm.com |

---

## 🛠️ Setup & Deployment

### Step 1 — Clone and configure

```bash
git clone https://github.com/ManojKumar-Devops/bluegreen-pipeline.git
cd bluegreen-pipeline
```

Create and activate Python virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate        # Mac/Linux
# .venv\Scripts\activate         # Windows
```

Install dependencies:

```bash
pip install -r requirements.txt
```

### Step 2 — Configure AWS CLI

Create an IAM user with `AdministratorAccess` in AWS Console, generate access keys, then:

```bash
aws configure
# AWS Access Key ID:     AKIA...
# AWS Secret Access Key: xxxxxx
# Default region:        ap-south-1
# Output format:         json
```

Verify you are using an IAM user (not root):

```bash
aws sts get-caller-identity
# "Arn" must show :user/... NOT :root
```

### Step 3 — Bootstrap CDK

Run once per AWS account/region:

```bash
cdk bootstrap aws://YOUR_ACCOUNT_ID/ap-south-1
```

### Step 4 — Create GitHub repository

1. Go to `github.com/new`
2. Name it `bluegreen-pipeline`
3. Do NOT initialize with README or .gitignore
4. Generate a **Classic Personal Access Token** with `repo` and `admin:repo_hook` scopes at `github.com/settings/tokens`

Store the token in AWS Secrets Manager:

```bash
aws secretsmanager create-secret \
  --name github-token \
  --secret-string "ghp_YOUR_TOKEN_HERE" \
  --region ap-south-1
```

Add remote and push:

```bash
git remote add origin https://github.com/ManojKumar-Devops/bluegreen-pipeline.git
git branch -M main
git push -u origin main
```

### Step 5 — Build and push initial Docker image

**Important:** The Docker image must exist in ECR before deploying EcsStack. Build for `linux/amd64` (required for ECS Fargate, especially on Apple Silicon Macs):

```bash
# ECR login
aws ecr get-login-password --region ap-south-1 | \
  docker login --username AWS --password-stdin \
  YOUR_ACCOUNT_ID.dkr.ecr.ap-south-1.amazonaws.com

# Build and push (hardcoded URI — no variables to avoid zsh issues)
docker buildx build \
  --platform linux/amd64 \
  --provenance=false \
  --push \
  -t YOUR_ACCOUNT_ID.dkr.ecr.ap-south-1.amazonaws.com/bluegreen-app:latest \
  ./app

# Verify image is in ECR
aws ecr describe-images \
  --repository-name bluegreen-app \
  --region ap-south-1 \
  --query 'imageDetails[0].{tags:imageTags,pushedAt:imagePushedAt}'
```

> **Apple Silicon Mac note:** Always use `--platform linux/amd64 --provenance=false` when building for ECS Fargate. Without these flags, Docker builds an `arm64` image that ECS cannot run.

### Step 6 — Deploy CDK stacks in order

```bash
# 1. Deploy VPC
cdk deploy VpcStack --require-approval never

# 2. Deploy ECR repository
cdk deploy EcrStack --require-approval never

# 3. Push Docker image (see Step 5 above)

# 4. Deploy ECS cluster + ALB + Blue/Green service
cdk deploy EcsStack --require-approval never

# 5. Copy ExecRoleArn from EcsStack outputs — update taskdef.json
# Outputs will print:
#   EcsStack.ALBDnsName  = bluegreen-alb-xxx.ap-south-1.elb.amazonaws.com
#   EcsStack.ExecRoleArn = arn:aws:iam::ACCOUNT:role/EcsStack-TaskExecRole...

# 6. Update taskdef.json with real role ARN
python3 -c "
import json
with open('taskdef.json') as f: d = json.load(f)
d['executionRoleArn'] = 'arn:aws:iam::YOUR_ACCOUNT_ID:role/EcsStack-TaskExecRole...'
d['containerDefinitions'][0]['image'] = '<IMAGE_URI>'
with open('taskdef.json', 'w') as f: json.dump(d, f, indent=2)
print('updated')
"

# 7. Commit and push taskdef.json
git add taskdef.json
git commit -m "fix: updated executionRoleArn"
git push origin main

# 8. Deploy CodePipeline + CodeBuild + CodeDeploy
cdk deploy PipelineStack --require-approval never
```

> **Deployment order is mandatory:**
> `VpcStack` → `EcrStack` → *(push image)* → `EcsStack` → `PipelineStack`

---

## 🔄 How the CI/CD Pipeline Works

After all stacks are deployed, every `git push` to `main` automatically:

1. **Source stage** — CodePipeline detects the GitHub push via webhook
2. **Build stage** — CodeBuild builds a new Docker image tagged with the commit SHA and pushes it to ECR
3. **Deploy stage** — CodeDeploy starts a Blue/Green deployment:
   - Launches new Green tasks with the updated image
   - Routes test traffic to Green via port 8080
   - Runs health checks on `/health` endpoint
   - Shifts 100% production traffic from Blue to Green
   - Terminates old Blue tasks

### Test the pipeline end-to-end

```bash
# Make a change
sed -i '' 's/1.0.0/2.0.0/' app/app.py

# Push to trigger pipeline
git add app/app.py
git commit -m "feat: bump to version 2.0.0"
git push origin main
```

Watch pipeline status:

```bash
aws codepipeline get-pipeline-state \
  --name bluegreen-pipeline \
  --region ap-south-1 \
  --query 'stageStates[*].{stage:stageName,status:latestExecution.status}'
```

Test live app after deployment:

```bash
curl http://YOUR_ALB_DNS/health
# {"status": "healthy"}

curl http://YOUR_ALB_DNS/
# {"message": "Blue/Green Deployment Demo", "version": "2.0.0", ...}
```

---

## 🧪 Testing

### Health check endpoint
```bash
curl http://YOUR_ALB_DNS/health
# Expected: {"status": "healthy"}
```

### Main endpoint
```bash
curl http://YOUR_ALB_DNS/
# Expected: {"message": "Blue/Green Deployment Demo", "version": "1.0.0", "host": "...", "env": "production"}
```

### Test listener (Green environment before cutover)
```bash
curl http://YOUR_ALB_DNS:8080/health
# Checks Green tasks before traffic is shifted
```

---

## ⚙️ Configuration

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_ENV` | `production` | Application environment |
| `APP_VERSION` | `1.0.0` | Application version |

### CDK stack configuration (`app.py`)

```python
env = cdk.Environment(
    account="YOUR_ACCOUNT_ID",
    region="ap-south-1"        # Mumbai — change if needed
)
```

### Deployment config options (`pipeline_stack.py`)

```python
# Change deployment strategy:
deployment_config=cd.EcsDeploymentConfig.ALL_AT_ONCE          # instant cutover
deployment_config=cd.EcsDeploymentConfig.CANARY_10_PERCENT_5_MINUTES  # gradual
deployment_config=cd.EcsDeploymentConfig.LINEAR_10_PERCENT_EVERY_1_MINUTES  # linear
```

---

## 🐛 Common Issues & Fixes

### CannotPullContainerError — platform mismatch
**Cause:** Built `arm64` image on Apple Silicon Mac, ECS needs `linux/amd64`

**Fix:**
```bash
docker buildx build --platform linux/amd64 --provenance=false --push \
  -t YOUR_ACCOUNT_ID.dkr.ecr.ap-south-1.amazonaws.com/bluegreen-app:latest ./app
```

### ECS tasks failing on fresh EcsStack deploy
**Cause:** ECR repository is empty when ECS tries to pull the image

**Fix:** Always push Docker image to ECR before deploying EcsStack

### CDK bootstrap error — cannot assume role
**Cause:** Using AWS root account credentials

**Fix:** Create an IAM user with `AdministratorAccess`, generate access keys, run `aws configure` with IAM user keys (not root keys)

### CodePipeline webhook 404
**Cause:** Wrong GitHub owner name or missing `admin:repo_hook` token scope

**Fix:** Verify exact GitHub username with `curl -H "Authorization: token TOKEN" https://api.github.com/user` and regenerate Classic token with `repo` + `admin:repo_hook` scopes

### taskdef.json executionRoleArn stale after redeploy
**Cause:** EcsStack creates a new IAM role with a new ARN on every fresh deploy

**Fix:** Always update `taskdef.json` after redeploying EcsStack:
```bash
ROLE_ARN=$(aws cloudformation describe-stacks --stack-name EcsStack \
  --region ap-south-1 \
  --query "Stacks[0].Outputs[?OutputKey=='ExecRoleArn'].OutputValue" \
  --output text)
```

---

## 💰 Cost Estimate

| Resource | Approx cost |
|----------|-------------|
| ALB | ~$0.008/hour (~₹20/day) |
| NAT Gateway | ~$0.045/hour (~₹90/day) |
| ECS Fargate (2 tasks, 0.25 vCPU, 512MB) | ~$0.01/hour (~₹20/day) |
| ECR storage | ~$0.10/GB/month |
| CodeBuild | First 100 min/month free |

> **Always run `cdk destroy --all` after practice to avoid charges.**

---

## 🗑️ Cleanup

```bash
# Delete ECR images first
aws ecr batch-delete-image \
  --repository-name bluegreen-app \
  --region ap-south-1 \
  --image-ids imageTag=latest

# Destroy all stacks
cdk destroy --all --force
```

---

## 📚 Tech Stack

- **Infrastructure:** AWS CDK v2 (Python)
- **CI/CD:** AWS CodePipeline, CodeBuild, CodeDeploy
- **Container Registry:** Amazon ECR
- **Compute:** Amazon ECS Fargate
- **Load Balancer:** Application Load Balancer
- **Networking:** Amazon VPC
- **Application:** Python Flask + Gunicorn
- **Container:** Docker (linux/amd64)

---

## 🎓 Lessons Learned

1. **Platform matters** — Always build Docker images with `--platform linux/amd64` on Apple Silicon Macs. ECS Fargate runs on Intel/AMD hardware.
2. **Deploy order is critical** — ECR image must exist before EcsStack creates the ECS service. `VpcStack → EcrStack → docker push → EcsStack → PipelineStack`.
3. **IAM role ARN changes on redeploy** — `taskdef.json` must be updated every time EcsStack is redeployed.
4. **Classic GitHub token required** — CodePipeline webhooks require Classic PAT with `admin:repo_hook` scope. Fine-grained tokens do not work.
5. **No shell variables with comments in zsh** — Inline `#` comments after variable assignments in zsh corrupt the variable value. Always run commands one line at a time.
6. **CODE_DEPLOY controller is exclusive** — ECS services with `CODE_DEPLOY` controller cannot be force-restarted via `aws ecs update-service`. Use `aws deploy create-deployment` instead.

---

## 👨‍💻 Author

**Manojkumar** — [@ManojKumar-Devops](https://github.com/ManojKumar-Devops)
