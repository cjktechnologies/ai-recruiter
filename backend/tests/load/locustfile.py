"""Load / performance test (Locust).

    pip install locust
    locust -f tests/load/locustfile.py --host http://localhost:8000 \
        --users 200 --spawn-rate 20 --run-time 10m --headless \
        -e RECRUITER_EMAIL=recruiter@demo.example.com -e PASSWORD='Demo!Passw0rd123' -e ORG_SLUG=demo

Targets (staging, 2 API replicas): p95 < 300 ms for reads, < 800 ms for screening-bearing writes,
error rate < 0.5 %.
"""

from __future__ import annotations

import os
import random
import uuid

from locust import HttpUser, between, task

API = "/api/v1"


class RecruiterUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self) -> None:
        r = self.client.post(
            f"{API}/auth/login", json={"email": os.environ["RECRUITER_EMAIL"], "password": os.environ["PASSWORD"]}
        )
        self.client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        jobs = self.client.get(f"{API}/jobs", params={"status": "published"}).json()["items"]
        self.job_ids = [j["id"] for j in jobs]

    @task(5)
    def pipeline(self) -> None:
        if self.job_ids:
            self.client.get(f"{API}/jobs/{random.choice(self.job_ids)}/pipeline", name="/jobs/:id/pipeline")

    @task(4)
    def search(self) -> None:
        self.client.get(
            f"{API}/candidates", params={"q": random.choice(["a", "e", "python", "eng"])}, name="/candidates?q"
        )

    @task(2)
    def screening_queue(self) -> None:
        self.client.get(f"{API}/screening/queue")

    @task(1)
    def analytics(self) -> None:
        self.client.get(f"{API}/analytics/overview")


class Applicant(HttpUser):
    """Public careers-site traffic: browsing plus CV submissions (exercises parsing + AI screening)."""

    wait_time = between(2, 6)

    def on_start(self) -> None:
        self.slug = os.environ.get("ORG_SLUG", "demo")
        self.jobs = self.client.get(f"{API}/public/{self.slug}/jobs").json()

    @task(8)
    def browse(self) -> None:
        self.client.get(f"{API}/public/{self.slug}/jobs")

    @task(1)
    def apply(self) -> None:
        if not self.jobs:
            return
        job = random.choice(self.jobs)
        uid = uuid.uuid4().hex[:10]
        cv = f"Load Tester\nEngineer\nExperience\nEngineer at X  Jan 2018 - Present\nPython PostgreSQL AWS {uid}\n"
        self.client.post(
            f"{API}/public/{self.slug}/jobs/{job['slug']}/apply",
            name="/public/apply",
            data={
                "first_name": "Load",
                "last_name": uid,
                "email": f"load+{uid}@example.com",
                "consent_recruitment": "true",
                "answers": '{"work_permit": true}',
            },
            files={"cv": ("cv.txt", cv.encode(), "text/plain")},
            headers={"Idempotency-Key": f"load-{uid}"},
        )
