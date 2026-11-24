# Deployed build identity

The API `GET /api/v1/build` (or `<configured API prefix>/build`) and the built
frontend `/build-info.json` publish exactly these diagnostic fields:

```json
{"schema_version":1,"service":"docuforge","version":"0.1.0","revision":null}
```

The frontend service is `docuforge-frontend`; its version comes from
`frontend/package.json`. Both component versions remain `0.1.0`. A known revision
is a full forty-character ASCII hexadecimal Git SHA, normalized to lowercase.
Missing local build inputs produce JSON `null`. Supplied blank, short, malformed,
control-containing or conflicting sources fail the build, as does Git's all-zero
null-object placeholder. Neither component reads
Git to infer a stamp. No environment dump, path, branch, author, message or secret
is published.

## Build inputs

| Artifact | Explicit input | Provider input |
| --- | --- | --- |
| API wheel / Docker | `DOCUFORGE_BUILD_REVISION` | `RAILWAY_GIT_COMMIT_SHA` |
| Vite frontend | `DOCUFORGE_BUILD_REVISION` | `VERCEL_GIT_COMMIT_SHA` |

If both inputs exist they must identify the same revision, ignoring hexadecimal
case. Inputs are not trimmed: an empty variable is invalid, not absent. An absent
input is allowed for local development, Vitest and ordinary builds.

Setuptools generates `_build_identity.json` inside each wheel before installation,
including when pip builds a wheel in Docker. It always overwrites previous build
output, even for a later unknown build. The source tree and sdist contain the
generator, not a generated revision stamp. Building a wheel from an sdist requires
the desired inputs again. Installed wheels work without `.git`; runtime override
or provider variables cannot relabel them. An absent local resource means unknown;
a present corrupt or version-inconsistent resource fails explicitly. Health and
readiness do not require a known revision.

For a local stamped build, choose the full source commit deliberately. For example
in PowerShell, from a clean checkout of that source:

```powershell
$env:DOCUFORGE_BUILD_REVISION = (git rev-parse HEAD)
python -m build
docker build --build-arg "DOCUFORGE_BUILD_REVISION=$env:DOCUFORGE_BUILD_REVISION" -t docuforge-local .
Push-Location frontend
npm run build
Pop-Location
Remove-Item Env:DOCUFORGE_BUILD_REVISION
```

Only stamp the revision of the source actually being built. A dirty checkout's
HEAD does not describe its edits. These inputs are diagnostic assertions supplied
by the builder, not a check that the working tree matches a commit.

For Railway GitHub-triggered deploys, the Dockerfile declares both revision `ARG`
values in the consuming stage. Railway requires these declarations to expose
build variables; its Git SHA is available for GitHub-triggered deployments.
For image/CLI deployments without it, provide the explicit build argument. Do not
set a runtime variable expecting it to change an existing artifact. A bare local
Docker build can be unstamped; production strict verification rejects it. See the
[Railway Dockerfile requirements](https://docs.railway.com/builds/dockerfiles) and
[Git variable reference](https://docs.railway.com/variables/reference).

In Vercel's project settings, enable **Automatically expose System Environment
Variables** so `VERCEL_GIT_COMMIT_SHA` is available during the Vite build, or supply
`DOCUFORGE_BUILD_REVISION` at build time. Avoid a persistent explicit override that
becomes stale and conflicts with the next provider SHA. Vite reads only the
needed proxy/revision variables and never exposes an entire build environment to
browser code. See [Vercel system variables](https://vercel.com/docs/environment-variables/system-environment-variables).

Vite emits the JSON asset and `docuforge-version` / `docuforge-revision` meta tags
in `dist/index.html` from one identity object. Unknown HTML uses the explicit
`unknown` revision sentinel paired with JSON `null`. There is no hand-maintained
`public/build-info.json`. API build responses and Vercel's identity JSON use
`Cache-Control: no-store`. The JSON route is excluded from the SPA rewrite, so
missing metadata cannot become a successful HTML fallback. SPA routes and Vite's
hashed asset names/caching remain available. Verification requests fresh JSON and
HTML with `Cache-Control: no-cache, no-store` and `Pragma: no-cache`.

## Strict verification and rollback

Obtain the expected API revision from the selected Railway deployment's source
commit/build records and the expected frontend revision from the selected Vercel
deployment's source commit/build records. Resolve each to a full SHA in the
repository. Do not derive expectations from the identity endpoints: those are
observations to compare against the independently chosen deployment records.
The observations are available at API `/api/v1/build`, frontend `/build-info.json`
and the frontend HTML source's two meta tags.

From an installed checkout of the verifier, with those four values set:

```powershell
python -m docuforge.ops.release_identity `
  --api-url "$env:DOCUFORGE_API_URL" `
  --frontend-url "$env:DOCUFORGE_FRONTEND_URL" `
  --expected-api-revision "$env:DOCUFORGE_EXPECTED_API_REVISION" `
  --expected-frontend-revision "$env:DOCUFORGE_EXPECTED_FRONTEND_REVISION" `
  --expected-version 0.1.0 `
  --report-json release-identity.json
```

Both origins must be HTTPS origins without credentials, paths, query strings or
fragments. Both expected revisions and the frontend origin are required together.
Strict mode checks API readiness/service/version, both versioned build contracts,
independent revision matches and exactly one matching frontend HTML meta tag per
field. Missing, corrupt, null, unavailable, stale or inconsistent identity fails
nonzero even when every artifact reports `0.1.0`. Reports retain only validated
origins, versions and revisions with component-specific outcomes; they omit raw
response bodies and malformed metadata. Identity JSON is capped at 4 KiB and HTML
at 1 MiB after the shared bounded HTTP transport (10 MiB maximum read).

The old semantic-version-only Python function and CLI invocation still work:

```text
python -m docuforge.ops.release_identity --api-url https://api.example.com --expected-version 0.1.0
```

Their success explicitly says revisions were **not verified** and cannot satisfy
the strict Production Smoke gate. Rebuild/redeploy older unstamped artifacts before
using strict verification. For a rollback, choose each intended historical revision
independently and verify those exact values; mixed API/frontend revisions can be
legitimate. An old unstamped image must be rebuilt with its actual source revision.

The manual **Production Smoke** workflow requires both expected revision inputs
and both origins. Identity is a separate prerequisite to the twenty-one
semantic checks. Its always-run summary includes expected/observed revisions and
rejects failed/skipped verification or missing/malformed reports. It never assumes
the verifier checkout's SHA is a production revision.

Ordinary CI checks local artifacts only. CI's `github.sha` identifies the default
checkout under test, which on a pull request is typically a synthetic merge/test
revision. The eventual squash-merged `main` commit is a different revision and is
the appropriate source expectation only when that commit was actually deployed.
API/frontend deployments and rollbacks may differ from each other and from the
verifier checkout. The production Docker CI job supplies its test checkout SHA
explicitly and verifies the installed stamp inside the non-root image before
retaining all eighteen runtime/durable markers. A separate four-route Office/OCR API
integration exercises real engines in that image. Neither integration nor identity
adds or renumbers a durable marker.

This verifies reported build metadata and HTML consistency. It does not inspect
every loaded JavaScript chunk, sign artifacts, prove reproducible source-to-binary
provenance or provide cryptographic attestation. Local/CI success is separate from
public Production Smoke, manual browser hard-refresh, dogfood and release decisions;
those remain pending until their own evidence is recorded.
