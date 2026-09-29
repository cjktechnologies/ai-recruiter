# AI Recruiter: web

Next.js 16 (App Router) + TypeScript + Tailwind 4.

- `src/app/(app)/*`: staff workspaces (auth required; see `src/proxy.ts`)
- `src/app/careers|assessment|offer|reference|portal`: candidate-facing pages
- `src/app/api/session`: login/logout → httpOnly cookies; `src/app/api/backend/[...path]`: BFF proxy to the API
- `e2e/`: Playwright tests against a running stack (seeded `demo` tenant)

```bash
npm ci
BACKEND_URL=http://localhost:8000 npm run dev
npm run lint && npm run typecheck && npm run build
npx playwright test
```
