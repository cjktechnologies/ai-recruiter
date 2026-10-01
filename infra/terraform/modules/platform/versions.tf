terraform {
  required_version = ">= 1.8"
  required_providers {
    google = { source = "hashicorp/google", version = "~> 8.0" }
    # google_project_service_identity (service agents for CMEK grants) is only in google-beta.
    google-beta = { source = "hashicorp/google-beta", version = "~> 8.0" }
    random      = { source = "hashicorp/random", version = "~> 3.6" }
  }
}
