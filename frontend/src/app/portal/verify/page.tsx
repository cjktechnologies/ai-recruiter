"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

function Verify() {
  const token = useSearchParams().get("token");
  const router = useRouter();
  const [msg, setMsg] = useState("Signing you in…");
  useEffect(() => {
    if (!token) return;
    fetch("/api/session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ magic_token: token }) })
      .then((r) => (r.ok ? router.replace("/portal") : setMsg("This link is invalid or has expired.")));
  }, [token, router]);
  return <p>{token ? msg : "Missing token."}</p>;
}

export default function VerifyPage() {
  return <main className="p-10 text-center"><Suspense><Verify /></Suspense></main>;
}
