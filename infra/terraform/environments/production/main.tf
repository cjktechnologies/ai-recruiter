terraform {
  required_version = ">= 1.8"
  backend "s3" {
    # Created by infra/terraform/bootstrap. Configure with -backend-config or edit per account.
    bucket         = "ai-recruiter-tfstate"
    key            = "production/terraform.tfstate"
    region         = "eu-west-1"
    dynamodb_table = "ai-recruiter-tflock"
    encrypt        = true
  }
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.70" }
  }
}

variable "region" {
  type    = string
  default = "eu-west-1"
}
variable "dr_region" {
  type    = string
  default = "eu-central-1"
}
variable "github_repository" {
  type    = string
  default = "cjktechnologies/ai-recruiter"
}

provider "aws" {
  region = var.region
  default_tags { tags = { Project = "ai-recruiter", Environment = "production" } }
}
provider "aws" {
  alias  = "dr"
  region = var.dr_region
}

module "platform" {
  source    = "../../modules/platform"
  providers = { aws = aws, aws.dr = aws.dr }

  name              = "ai-recruiter-production"
  environment       = "production"
  region            = var.region
  github_repository = var.github_repository
  vpc_cidr          = "10.40.0.0/16"
}

output "platform" {
  value     = module.platform
  sensitive = true
}
