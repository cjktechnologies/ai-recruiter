"""Skill taxonomy used for deterministic, evidence-based skill extraction and normalization.

Organizations can extend this via the ``skills`` table; this curated seed covers common
technical, business and soft skills with aliases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

SKILLS: dict[str, tuple[str, list[str]]] = {
    # name: (category, aliases)
    "Python": ("programming", ["python3", "py"]),
    "Java": ("programming", []),
    "JavaScript": ("programming", ["js", "ecmascript"]),
    "TypeScript": ("programming", ["ts"]),
    "Go": ("programming", ["golang"]),
    "Rust": ("programming", []),
    "C++": ("programming", ["cpp"]),
    "C#": ("programming", ["csharp", ".net c#"]),
    "Ruby": ("programming", []),
    "PHP": ("programming", []),
    "Kotlin": ("programming", []),
    "Swift": ("programming", []),
    "Scala": ("programming", []),
    "R": ("programming", ["r language", "rstats"]),
    "SQL": ("data", ["t-sql", "pl/sql", "tsql"]),
    "PostgreSQL": ("data", ["postgres", "psql"]),
    "MySQL": ("data", []),
    "MongoDB": ("data", ["mongo"]),
    "Redis": ("data", []),
    "Elasticsearch": ("data", ["elastic search", "opensearch"]),
    "Kafka": ("data", ["apache kafka"]),
    "Spark": ("data", ["apache spark", "pyspark"]),
    "Airflow": ("data", ["apache airflow"]),
    "dbt": ("data", []),
    "Snowflake": ("data", []),
    "Pandas": ("data", []),
    "NumPy": ("data", ["numpy"]),
    "Machine Learning": ("ai", ["ml", "machine-learning"]),
    "Deep Learning": ("ai", ["neural networks"]),
    "NLP": ("ai", ["natural language processing"]),
    "LLM": ("ai", ["large language models", "llms", "generative ai", "genai"]),
    "PyTorch": ("ai", ["torch"]),
    "TensorFlow": ("ai", []),
    "scikit-learn": ("ai", ["sklearn", "scikit learn"]),
    "Computer Vision": ("ai", []),
    "React": ("frontend", ["react.js", "reactjs"]),
    "Next.js": ("frontend", ["nextjs"]),
    "Vue.js": ("frontend", ["vue", "vuejs"]),
    "Angular": ("frontend", ["angularjs"]),
    "HTML": ("frontend", ["html5"]),
    "CSS": ("frontend", ["css3"]),
    "Tailwind CSS": ("frontend", ["tailwind"]),
    "Node.js": ("backend", ["node", "nodejs"]),
    "FastAPI": ("backend", []),
    "Django": ("backend", []),
    "Flask": ("backend", []),
    "Spring Boot": ("backend", ["spring"]),
    "Express": ("backend", ["express.js"]),
    "GraphQL": ("backend", []),
    "REST APIs": ("backend", ["rest", "restful", "rest api", "restful apis"]),
    "gRPC": ("backend", []),
    "Microservices": ("architecture", ["micro-services"]),
    "System Design": ("architecture", ["distributed systems"]),
    "AWS": ("cloud", ["amazon web services"]),
    "Azure": ("cloud", ["microsoft azure"]),
    "GCP": ("cloud", ["google cloud", "google cloud platform"]),
    "Docker": ("devops", ["containers"]),
    "Kubernetes": ("devops", ["k8s"]),
    "Terraform": ("devops", []),
    "CI/CD": ("devops", ["continuous integration", "continuous delivery", "github actions", "jenkins"]),
    "Linux": ("devops", ["unix"]),
    "Ansible": ("devops", []),
    "Prometheus": ("devops", []),
    "Git": ("tools", ["github", "gitlab"]),
    "Security": ("security", ["cybersecurity", "application security", "appsec", "infosec"]),
    "OWASP": ("security", []),
    "Penetration Testing": ("security", ["pentesting", "pen testing"]),
    "Testing": ("quality", ["unit testing", "test automation", "tdd", "pytest", "jest"]),
    "Selenium": ("quality", []),
    "Playwright": ("quality", []),
    "Agile": ("process", ["scrum", "kanban"]),
    "Project Management": ("business", ["pmp", "program management"]),
    "Product Management": ("business", ["product manager", "product owner"]),
    "Stakeholder Management": ("business", ["stakeholder engagement"]),
    "Data Analysis": ("business", ["data analytics", "analytics"]),
    "Excel": ("business", ["microsoft excel", "spreadsheets"]),
    "Power BI": ("business", ["powerbi"]),
    "Tableau": ("business", []),
    "Financial Modeling": ("finance", ["financial modelling"]),
    "Accounting": ("finance", ["bookkeeping", "gaap", "ifrs"]),
    "Budgeting": ("finance", ["forecasting"]),
    "Payroll": ("hr", []),
    "Recruitment": ("hr", ["recruiting", "talent acquisition", "sourcing"]),
    "Employee Relations": ("hr", []),
    "HRIS": ("hr", ["workday", "successfactors", "bamboohr"]),
    "Onboarding": ("hr", []),
    "Sales": ("commercial", ["business development", "b2b sales"]),
    "Account Management": ("commercial", ["key account management"]),
    "CRM": ("commercial", ["salesforce", "hubspot"]),
    "Marketing": ("commercial", ["digital marketing"]),
    "SEO": ("commercial", ["search engine optimization"]),
    "Content Writing": ("commercial", ["copywriting"]),
    "Customer Service": ("operations", ["customer support", "customer success"]),
    "Supply Chain": ("operations", ["logistics", "procurement"]),
    "Operations Management": ("operations", []),
    "UX Design": ("design", ["user experience", "ux"]),
    "UI Design": ("design", ["user interface design"]),
    "Figma": ("design", []),
    "Leadership": ("soft", ["team leadership", "people management", "team lead"]),
    "Communication": ("soft", ["communication skills"]),
    "Mentoring": ("soft", ["coaching"]),
    "Problem Solving": ("soft", ["problem-solving"]),
    "Negotiation": ("soft", []),
}

LANGUAGES = [
    "English",
    "Spanish",
    "French",
    "German",
    "Portuguese",
    "Italian",
    "Dutch",
    "Mandarin",
    "Cantonese",
    "Japanese",
    "Korean",
    "Arabic",
    "Hindi",
    "Swahili",
    "Russian",
    "Polish",
    "Turkish",
    "Afrikaans",
    "Zulu",
]


@dataclass(frozen=True)
class SkillMatcher:
    canonical: str
    category: str
    pattern: re.Pattern[str]


def _term_pattern(term: str) -> str:
    escaped = re.escape(term.lower())
    # Word-ish boundaries that tolerate symbols such as C++, C#, .NET, Node.js
    return rf"(?<![a-z0-9]){escaped}(?![a-z0-9+#])"


@lru_cache
def matchers() -> tuple[SkillMatcher, ...]:
    out: list[SkillMatcher] = []
    for name, (category, aliases) in SKILLS.items():
        terms = sorted({name, *aliases}, key=len, reverse=True)
        # Single-letter / very short ambiguous names only match in their canonical casing context.
        if name in ("R", "Go"):
            pattern = re.compile(
                rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9+#])"
                r"(?=\s*(?:,|/|\(|\)|;|\band\b|\n|$|lang|\s(?:microservices|services|developer|engineer|"
                r"programming|code|backend)))"
            )
            alias_terms = [t for t in terms if t != name]
            if alias_terms:
                pattern = re.compile(pattern.pattern + "|" + "|".join(_term_pattern(t) for t in alias_terms), re.I)
        else:
            pattern = re.compile("|".join(_term_pattern(t) for t in terms), re.I)
        out.append(SkillMatcher(name, category, pattern))
    return tuple(out)


def normalize_skill(raw: str) -> str:
    """Map a free-text skill to its canonical taxonomy name when known."""
    value = raw.strip()
    lowered = value.lower()
    for name, (_cat, aliases) in SKILLS.items():
        if lowered == name.lower() or lowered in (a.lower() for a in aliases):
            return name
    return value


def category_of(skill: str) -> str | None:
    entry = SKILLS.get(normalize_skill(skill))
    return entry[0] if entry else None
