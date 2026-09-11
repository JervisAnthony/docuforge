# MVP1 dogfood log

Use this document to capture real-world findings from the deployed MVP1 before the formal `v0.1.0` release and to separate launch blockers from post-MVP1 product ideas.

## Dogfood window

- Start date: 2026-09-11
- Target duration: approximately one week
- Frontend: `https://docuforge-five.vercel.app`

## How to record findings

For each finding, capture:

- date;
- workflow/tool;
- device/browser when relevant;
- what happened;
- expected behavior;
- reproducibility;
- severity;
- disposition.

Use these severity levels:

- **P0 — launch blocker:** crash, data corruption, broken download, repeated server failure, or a core workflow that cannot be used.
- **P1 — serious defect:** important functionality is unreliable or materially confusing, but a reasonable workaround exists.
- **P2 — usability issue:** friction, unclear wording, awkward layout, weak feedback, or minor responsive behavior.
- **P3 — enhancement:** useful idea that is not required for MVP1 launch.

## Findings

| Date | Tool / area | Finding | Reproducible | Severity | Disposition |
| --- | --- | --- | --- | --- | --- |
| 2026-09-11 | PDF workflow | Initial public production test completed successfully. | Yes | — | Baseline pass |
| 2026-09-11 | Image workflow | Initial public production test completed successfully. | Yes | — | Baseline pass |

## External tester feedback

Capture feedback from friends and other testers here before deciding whether it is a launch fix or an MVP2 backlog item.

| Date | Tester context | Feedback | Severity | Decision |
| --- | --- | --- | --- | --- |

## MVP2 candidates discovered during dogfooding

Do not expand MVP1 scope for these unless they expose a launch blocker. Candidate themes already outside the MVP1 launch requirement include Office-document conversion, OCR, batch workflows, background job handling, authentication, persistence, and additional visual polish.

## Exit criteria

The dogfood window is complete when:

1. the planned observation period has elapsed;
2. all P0 findings are resolved and re-verified;
3. P1 findings have an explicit release decision;
4. P2/P3 findings are either accepted for MVP1 or moved into the MVP2 backlog;
5. Production Smoke has passed against the public deployment;
6. the release owner is comfortable creating the `v0.1.0` tag and GitHub release.
