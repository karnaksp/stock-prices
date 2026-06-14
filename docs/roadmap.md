# Roadmap

This roadmap tracks production hardening and portfolio-facing improvements. It is intentionally separate from the changelog: the changelog records shipped changes, while this page describes the next engineering priorities.

## Production Hardening

- Add required checks on protected branches after CI is stable.
- Keep Docker and CLI flows covered by smoke tests.
- Track test coverage for core request parsing, market data loading, and render planning.
- Continue keeping real secrets out of commits; `.env.example` is the only committed environment template.

## Product And Demo

- Add short MP4 demo artifacts for the most common use cases.
- Keep the MkDocs site as the primary user-facing documentation.
- Document a small set of repeatable Telegram prompts for quick demos.
- Add a social preview image for GitHub and shared links.

## Engineering Backlog

- Add optional lint/type checks that do not slow down normal contribution flow.
- Add a Docker build smoke check to CI.
- Expand troubleshooting for Telegram delivery and local video rendering failures.
- Keep generated videos as runtime artifacts unless they are deliberate documentation assets.

