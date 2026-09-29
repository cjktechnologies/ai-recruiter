terraform {
  required_version = ">= 1.8"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
      # aws.dr: second region for cross-region backup replication (disaster recovery).
      configuration_aliases = [aws.dr]
    }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
}
