# Database ERD

Generated from the SQLAlchemy models by `python -m scripts.export_erd`. 46 tables. Constraints, indexes and the append-only audit trigger are defined in `backend/alembic/versions/`.

```mermaid
erDiagram
    ai_agent_executions {
        enum agent
        enum status
        string entity_type
        uuid entity_id
        uuid workflow_run_id FK
        string provider
        string model
        string prompt_version
        jsonb input_summary
        jsonb output
        jsonb guardrail_flags
        integer tokens_in
        integer tokens_out
        integer latency_ms
        text error
        uuid triggered_by_id FK
        datetime started_at
        datetime finished_at
        uuid id PK
        uuid organization_id FK
    }
    ai_recommendations {
        uuid execution_id FK
        enum agent
        string entity_type
        uuid entity_id
        string kind
        string recommendation
        float confidence
        jsonb facts
        jsonb interpretations
        text explanation
        enum review_status
        uuid reviewed_by_id FK
        datetime reviewed_at
        text review_comment
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    application_stage_history {
        uuid application_id FK
        enum from_stage
        enum to_stage
        uuid changed_by_id FK
        string actor_type
        text reason
        datetime changed_at
        uuid id PK
    }
    applications {
        uuid job_id FK
        uuid candidate_id FK
        enum stage
        enum status
        string source
        datetime applied_at
        datetime stage_changed_at
        float match_score
        jsonb screening_answers
        text cover_letter
        string rejection_reason
        uuid recruiter_id FK
        datetime hired_at
        float sourcing_cost
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    approval_steps {
        uuid workflow_id FK
        integer step_order
        string approver_role
        uuid approver_user_id FK
        enum status
        uuid decided_by_id FK
        datetime decided_at
        text comment
        uuid id PK
        datetime created_at
        datetime updated_at
    }
    approval_workflows {
        string entity_type
        uuid entity_id
        enum status
        integer current_step
        uuid created_by_id FK
        datetime completed_at
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    assessment_questions {
        uuid assessment_id FK
        enum kind
        text prompt
        jsonb options
        jsonb correct_answer
        text rubric
        string competency
        string difficulty
        float points
        integer position
        jsonb tags
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    assessment_results {
        uuid assessment_id FK
        uuid application_id FK
        enum status
        string access_token_hash
        datetime invited_at
        datetime expires_at
        datetime started_at
        datetime submitted_at
        jsonb answers
        jsonb question_scores
        float score
        float max_score
        float percentage
        boolean passed
        jsonb competency_scores
        text candidate_feedback
        uuid scored_by_id FK
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    assessments {
        uuid job_id FK
        string title
        enum kind
        text instructions
        integer duration_minutes
        float passing_score
        boolean is_active
        uuid created_by_id FK
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    audit_logs {
        uuid organization_id FK
        enum actor_type
        string actor_id
        string action
        string entity_type
        string entity_id
        jsonb changes
        string ip_address
        string user_agent
        string request_id
        datetime created_at
        uuid id PK
    }
    background_checks {
        uuid application_id FK
        string provider
        jsonb check_types
        enum status
        string external_id
        datetime consent_obtained_at
        string result
        jsonb result_detail
        uuid requested_by_id FK
        datetime requested_at
        datetime completed_at
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    candidate_documents {
        uuid candidate_id FK
        enum kind
        string filename
        string content_type
        biginteger size_bytes
        string sha256
        string storage_key
        enum scan_status
        string scan_detail
        enum parse_status
        encryptedstring parsed_text
        jsonb parsed_data
        jsonb security_flags
        uuid uploaded_by_id FK
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    candidate_evaluations {
        uuid application_id FK
        jsonb evidence
        jsonb competency_matrix
        float overall_score
        enum ai_recommendation
        text ai_rationale
        jsonb risks
        enum decision
        uuid decided_by_id FK
        datetime decided_at
        text decision_rationale
        uuid agent_execution_id FK
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    candidate_notes {
        uuid candidate_id FK
        uuid application_id FK
        uuid author_id FK
        text body
        string visibility
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    candidate_references {
        uuid application_id FK
        string referee_name
        string referee_email
        string referee_phone
        string relationship_to_candidate
        string company
        enum status
        jsonb questionnaire
        jsonb responses
        string access_token_hash
        datetime requested_at
        datetime completed_at
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    candidate_skills {
        uuid candidate_id FK
        uuid skill_id FK
        float years
        string level
        string source
        text evidence
        uuid id PK
    }
    candidates {
        string first_name
        string last_name
        string email
        encryptedstring phone
        string phone_hash
        string location
        string headline
        text summary
        string linkedin_url
        string portfolio_url
        float years_experience
        string current_title
        string current_company
        jsonb education
        jsonb experience
        jsonb languages
        string source
        string source_detail
        array tags
        uuid owner_id FK
        array embedding
        uuid duplicate_of_id FK
        datetime consent_given_at
        datetime retention_until
        datetime anonymized_at
        boolean do_not_contact
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    communications {
        uuid candidate_id FK
        uuid application_id FK
        enum channel
        enum direction
        string subject
        text body
        string template_key
        enum status
        string external_id
        text error
        boolean ai_generated
        uuid sent_by_id FK
        datetime sent_at
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    compensation_bands {
        string name
        string job_level
        uuid department_id FK
        string location
        string currency
        numeric min_salary
        numeric max_salary
        float max_bonus_pct
        jsonb benefits
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    consent_records {
        uuid candidate_id FK
        enum purpose
        boolean granted
        datetime recorded_at
        datetime expires_at
        string source
        string policy_version
        string ip_address
        uuid id PK
        uuid organization_id FK
    }
    departments {
        string name
        string code
        uuid parent_id FK
        uuid head_user_id FK
        string cost_center
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    eeo_responses {
        uuid candidate_id FK
        string gender
        string ethnicity
        string age_band
        string disability
        string veteran
        datetime recorded_at
        uuid id PK
        uuid organization_id FK
    }
    hiring_requisitions {
        string reference
        string title
        uuid department_id FK
        integer headcount
        enum employment_type
        string location
        enum remote_policy
        string job_level
        text justification
        jsonb responsibilities
        jsonb required_skills
        jsonb preferred_skills
        integer min_years_experience
        numeric budget_min
        numeric budget_max
        string currency
        date target_start_date
        enum status
        uuid requested_by_id FK
        uuid hiring_manager_id FK
        uuid recruiter_id FK
        datetime approved_at
        datetime filled_at
        jsonb ai_validation
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    idempotency_keys {
        string scope
        string key
        string request_hash
        integer status_code
        jsonb response_body
        datetime created_at
        uuid id PK
    }
    integrations {
        enum kind
        string name
        jsonb config
        encryptedstring secret
        boolean is_enabled
        datetime last_sync_at
        text last_error
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    interview_scorecards {
        uuid interview_id FK
        uuid interviewer_id FK
        jsonb ratings
        float overall_rating
        enum recommendation
        text strengths
        text concerns
        text notes
        datetime submitted_at
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    interview_templates {
        string name
        enum kind
        integer duration_minutes
        jsonb competencies
        jsonb questions
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    interviewers {
        uuid interview_id FK
        uuid user_id FK
        string role
        string response_status
        uuid id PK
    }
    interviews {
        uuid application_id FK
        uuid template_id FK
        enum kind
        integer round
        enum status
        datetime scheduled_start
        datetime scheduled_end
        string timezone
        string location
        string meeting_url
        string calendar_provider
        string calendar_event_id
        datetime reminder_sent_at
        encryptedstring transcript
        jsonb ai_summary
        text notes
        string cancelled_reason
        uuid created_by_id FK
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    job_requirements {
        uuid job_id FK
        enum kind
        string name
        float min_years
        string level
        boolean is_mandatory
        float weight
        integer position
        uuid id PK
    }
    jobs {
        uuid requisition_id FK
        uuid department_id FK
        string title
        string slug
        text description
        text advertisement
        string location
        enum remote_policy
        enum employment_type
        string job_level
        numeric salary_min
        numeric salary_max
        string currency
        boolean show_salary
        enum status
        datetime published_at
        datetime closes_at
        uuid hiring_manager_id FK
        uuid recruiter_id FK
        jsonb publish_channels
        jsonb screening_config
        array embedding
        numeric cost_budget
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    notifications {
        uuid user_id FK
        string kind
        string title
        text body
        string link
        jsonb data
        datetime read_at
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    offer_approvals {
        uuid offer_id FK
        integer step_order
        string approver_role
        uuid approver_user_id FK
        enum status
        uuid decided_by_id FK
        datetime decided_at
        text comment
        uuid id PK
        datetime created_at
        datetime updated_at
    }
    offers {
        uuid application_id FK
        integer version
        enum status
        string job_title
        numeric base_salary
        string currency
        string pay_frequency
        float bonus_pct
        string equity
        jsonb benefits
        date start_date
        datetime expires_at
        uuid compensation_band_id FK
        boolean within_band
        text letter_body
        uuid created_by_id FK
        datetime sent_at
        datetime responded_at
        text decline_reason
        string response_token_hash
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    onboarding_handoffs {
        uuid application_id FK
        uuid offer_id FK
        string status
        string hris_employee_id
        jsonb payload
        text last_error
        datetime sent_at
        uuid initiated_by_id FK
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    onboarding_tasks {
        uuid application_id FK
        string title
        text description
        enum category
        enum status
        uuid assignee_id FK
        date due_date
        datetime completed_at
        string external_ref
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    organizations {
        string name
        string slug
        string plan
        boolean is_active
        string timezone
        string default_currency
        integer data_retention_days
        jsonb settings
        uuid id PK
        datetime created_at
        datetime updated_at
    }
    refresh_tokens {
        uuid user_id FK
        string token_hash
        uuid family_id
        datetime issued_at
        datetime expires_at
        datetime revoked_at
        string user_agent
        uuid id PK
    }
    roles {
        uuid organization_id FK
        string key
        string name
        string description
        array permissions
        boolean is_system
        uuid id PK
        datetime created_at
        datetime updated_at
    }
    screening_results {
        uuid application_id FK
        jsonb rule_results
        boolean eligible
        float score
        jsonb facts
        jsonb interpretations
        text summary
        enum recommendation
        enum review_status
        uuid reviewed_by_id FK
        datetime reviewed_at
        string reviewer_decision
        text override_reason
        uuid agent_execution_id FK
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    skills {
        string name
        string category
        array aliases
        uuid id PK
    }
    talent_pool_members {
        uuid pool_id PK,FK
        uuid candidate_id PK,FK
    }
    talent_pools {
        string name
        text description
        uuid owner_id FK
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    user_roles {
        uuid user_id PK,FK
        uuid role_id PK,FK
    }
    users {
        uuid organization_id FK
        string email
        string full_name
        string title
        uuid department_id FK
        string password_hash
        string auth_provider
        string external_subject
        boolean is_active
        string timezone
        datetime last_login_at
        integer failed_login_count
        datetime locked_until
        uuid candidate_id FK
        uuid id PK
        datetime created_at
        datetime updated_at
    }
    workflow_runs {
        uuid application_id FK
        string workflow
        enum status
        string current_node
        string waiting_on
        jsonb state
        jsonb history
        text error
        uuid id PK
        uuid organization_id FK
        datetime created_at
        datetime updated_at
    }
    organizations |o--o{ audit_logs : "organization_id"
    users |o--o{ departments : "head_user_id"
    departments |o--o{ departments : "parent_id"
    organizations ||--o{ departments : "organization_id"
    organizations ||--o{ integrations : "organization_id"
    organizations ||--o{ interview_templates : "organization_id"
    organizations |o--o{ roles : "organization_id"
    departments |o--o{ compensation_bands : "department_id"
    organizations ||--o{ compensation_bands : "organization_id"
    candidates |o--o{ users : "candidate_id"
    departments |o--o{ users : "department_id"
    organizations |o--o{ users : "organization_id"
    organizations ||--o{ approval_workflows : "organization_id"
    users |o--o{ approval_workflows : "created_by_id"
    users |o--o{ candidates : "owner_id"
    organizations ||--o{ candidates : "organization_id"
    candidates |o--o{ candidates : "duplicate_of_id"
    organizations ||--o{ hiring_requisitions : "organization_id"
    users |o--o{ hiring_requisitions : "hiring_manager_id"
    users |o--o{ hiring_requisitions : "recruiter_id"
    users ||--o{ hiring_requisitions : "requested_by_id"
    departments |o--o{ hiring_requisitions : "department_id"
    users ||--o{ notifications : "user_id"
    organizations ||--o{ notifications : "organization_id"
    users ||--o{ refresh_tokens : "user_id"
    organizations ||--o{ talent_pools : "organization_id"
    users |o--o{ talent_pools : "owner_id"
    users ||--o{ user_roles : "user_id"
    roles ||--o{ user_roles : "role_id"
    users |o--o{ approval_steps : "decided_by_id"
    users |o--o{ approval_steps : "approver_user_id"
    approval_workflows ||--o{ approval_steps : "workflow_id"
    organizations ||--o{ candidate_documents : "organization_id"
    candidates ||--o{ candidate_documents : "candidate_id"
    users |o--o{ candidate_documents : "uploaded_by_id"
    skills ||--o{ candidate_skills : "skill_id"
    candidates ||--o{ candidate_skills : "candidate_id"
    organizations ||--o{ consent_records : "organization_id"
    candidates ||--o{ consent_records : "candidate_id"
    candidates ||--o{ eeo_responses : "candidate_id"
    organizations ||--o{ eeo_responses : "organization_id"
    departments |o--o{ jobs : "department_id"
    users |o--o{ jobs : "hiring_manager_id"
    users |o--o{ jobs : "recruiter_id"
    hiring_requisitions |o--o{ jobs : "requisition_id"
    organizations ||--o{ jobs : "organization_id"
    talent_pools ||--o{ talent_pool_members : "pool_id"
    candidates ||--o{ talent_pool_members : "candidate_id"
    users |o--o{ applications : "recruiter_id"
    candidates ||--o{ applications : "candidate_id"
    jobs ||--o{ applications : "job_id"
    organizations ||--o{ applications : "organization_id"
    jobs |o--o{ assessments : "job_id"
    organizations ||--o{ assessments : "organization_id"
    users |o--o{ assessments : "created_by_id"
    jobs ||--o{ job_requirements : "job_id"
    users |o--o{ application_stage_history : "changed_by_id"
    applications ||--o{ application_stage_history : "application_id"
    organizations ||--o{ assessment_questions : "organization_id"
    assessments |o--o{ assessment_questions : "assessment_id"
    organizations ||--o{ assessment_results : "organization_id"
    assessments ||--o{ assessment_results : "assessment_id"
    users |o--o{ assessment_results : "scored_by_id"
    applications ||--o{ assessment_results : "application_id"
    organizations ||--o{ background_checks : "organization_id"
    users |o--o{ background_checks : "requested_by_id"
    applications ||--o{ background_checks : "application_id"
    users |o--o{ candidate_notes : "author_id"
    organizations ||--o{ candidate_notes : "organization_id"
    applications |o--o{ candidate_notes : "application_id"
    candidates ||--o{ candidate_notes : "candidate_id"
    applications ||--o{ candidate_references : "application_id"
    organizations ||--o{ candidate_references : "organization_id"
    candidates ||--o{ communications : "candidate_id"
    users |o--o{ communications : "sent_by_id"
    organizations ||--o{ communications : "organization_id"
    applications |o--o{ communications : "application_id"
    users |o--o{ interviews : "created_by_id"
    applications ||--o{ interviews : "application_id"
    organizations ||--o{ interviews : "organization_id"
    interview_templates |o--o{ interviews : "template_id"
    applications ||--o{ offers : "application_id"
    organizations ||--o{ offers : "organization_id"
    users |o--o{ offers : "created_by_id"
    compensation_bands |o--o{ offers : "compensation_band_id"
    users |o--o{ onboarding_tasks : "assignee_id"
    applications ||--o{ onboarding_tasks : "application_id"
    organizations ||--o{ onboarding_tasks : "organization_id"
    organizations ||--o{ workflow_runs : "organization_id"
    applications ||--o{ workflow_runs : "application_id"
    organizations ||--o{ ai_agent_executions : "organization_id"
    workflow_runs |o--o{ ai_agent_executions : "workflow_run_id"
    users |o--o{ ai_agent_executions : "triggered_by_id"
    organizations ||--o{ interview_scorecards : "organization_id"
    users ||--o{ interview_scorecards : "interviewer_id"
    interviews ||--o{ interview_scorecards : "interview_id"
    users ||--o{ interviewers : "user_id"
    interviews ||--o{ interviewers : "interview_id"
    users |o--o{ offer_approvals : "approver_user_id"
    users |o--o{ offer_approvals : "decided_by_id"
    offers ||--o{ offer_approvals : "offer_id"
    users |o--o{ onboarding_handoffs : "initiated_by_id"
    applications ||--o{ onboarding_handoffs : "application_id"
    offers ||--o{ onboarding_handoffs : "offer_id"
    organizations ||--o{ onboarding_handoffs : "organization_id"
    organizations ||--o{ ai_recommendations : "organization_id"
    users |o--o{ ai_recommendations : "reviewed_by_id"
    ai_agent_executions |o--o{ ai_recommendations : "execution_id"
    users |o--o{ candidate_evaluations : "decided_by_id"
    organizations ||--o{ candidate_evaluations : "organization_id"
    ai_agent_executions |o--o{ candidate_evaluations : "agent_execution_id"
    applications ||--o{ candidate_evaluations : "application_id"
    ai_agent_executions |o--o{ screening_results : "agent_execution_id"
    applications ||--o{ screening_results : "application_id"
    users |o--o{ screening_results : "reviewed_by_id"
    organizations ||--o{ screening_results : "organization_id"
```
