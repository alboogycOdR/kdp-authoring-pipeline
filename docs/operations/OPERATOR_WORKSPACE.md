# Operator workspace

Generate the local, static operator dashboard with:

```powershell
kdp workspace dashboard
```

By default it writes `reports/operator-workspace.html`. Use `--output` to choose another local
path. Open the HTML file in a browser after generation.

The dashboard combines existing read-only inspection services. It summarizes project and title
state, provider readiness, budget and usage, concept/planning state, chapter progress, editorial
findings and canon proposals, verification blockers, manuscript builds, release candidates, and
human review queues. It has no server, JavaScript, provider calls, or state-changing controls.

The report does not include API-key environment variable names or values, raw prompts, provider
response bodies, or provider headers. It is a status summary, not an approval surface; use the
audited CLI workflows for any state changes.
