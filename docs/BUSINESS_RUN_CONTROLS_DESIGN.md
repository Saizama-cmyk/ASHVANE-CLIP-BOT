# Visible business controls — 13 October 2026

SUBJECT: Let the owner run or stop each of Ashvane's four businesses from any workspace.
GROUND: A workstation with independent capture, story, music and social workers; opening a
workspace and enabling its workers are separate operations.
PALETTE: Retain the blue-black ground #070A10, hull #111925, ink #E4EBF3,
secondary ink #98A9BA, and amber #DAA66B. Use mint #8DD9B9 for a confirmed enabled
switch. The neutrals lean blue to match the existing observatory shell.
TYPE: Existing Bahnschrift business names and Segoe UI status text preserve the parent
dashboard identity. Tabular status values keep control geometry stable during refresh.
SPACE: Inside each control use 4/8/12px; the header has a separate 16/24px rhythm.
SHAPE: 8px surface corners, tonal separation, no floating card shadows.
MOTION: One 140ms switch receipt; reduced motion uses immediate state changes.
SIGNATURE: Four compact, always-present independent switches under the page title, outside
both the workspace navigation and the business picker. Keep them in the sticky desktop header.

Critique: A generic workspace selector would hide the switches again. This strip is specifically
worker control, with a separate clickable business name for navigation. A workspace change never
starts a business. No new business or background worker is added.

States: Initial unknown state disables switching until the authenticated API responds. Pending
changes disable the controls, announce the action and preserve the last confirmed state. API
responses alone change the switches. A stale GET cannot overwrite a newer change. Network errors
retain the last confirmed values and explain the error; polling resumes when the page is visible.
