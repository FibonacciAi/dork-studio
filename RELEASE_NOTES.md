# v0.1.2 — current screenshots and contributor attribution

Refreshed the screenshots from the current actual app: Director with a locally written example, an original drawing, explicit pitch entry before any AI request, and current video controls. Empty keys and separate temporary state were used; no provider call, simulated AI result or private media/history is shown.

The app-owned MIT copyright now uses **dork contributors**. Required upstream license attributions are retained. Repository owner/account links and older public commits/releases remain visible; this forward update does not anonymize the account or erase historical attribution. App behavior and the v0.1.1 validation remain unchanged. Verification documentation now correctly identifies the existing test runtime as Python 3.9.6; the setup guide targets Python 3.10+, and a fresh setup was not exercised.

# v0.1.1 — explicit creative pitches and desktop launch

This follow-up restores a visible three-direction pitch entry in the existing Flask Director workflow. **Suggest directions** carries the selected source, brief, taste, Cast/Looks and recent scenes; its AI request is explicitly provider-billed. Opening the card, attaching a source or choosing an editable direction starts no render.

- Stable per-user local port, Chrome/Edge app-mode launch and one fallback only after a confirmed port collision. Permission errors stop; existing processes stay running.
- Correct source loading and cost refresh during Director handoff.
- Optional instructions for importing selected local media/references/direction text. No credential, history or automatic state migration.
- Self-contained artifact JavaScript/CSS and data/blob media verified in a network-blocked, opaque preview.
- 37 Python and 20 Node tests passed. Actual local socket checks passed; synthetic-provider browser pitch walkthrough and 19 artifact browser checks passed.

Paid rendering quality, account-specific model access, live voice/Collections and other platforms remain unverified. This is the older Flask edition, with free source and desktop launchers; native persistent projects, take lineage, Compare/Storyboard and production bundles remain outside its scope. The v0.1.0 archive is unchanged.

# v0.1.0 — dork desktop preview

The existing Flask studio returns as lowercase **dork**, with macOS Setup and Launch commands and a clean MIT source release.

- Grok Imagine Image 2.0 and Grok Imagine Video 1.5 Lite (Fast) / 1.5 (Quality).
- Local Draw to direct with explicit Apply and a finished-still step for video.
- Cast/Looks reference preparation with the additional still cost included in the video estimate.
- Isolated local state, loopback-only serving, key-status privacy and network-blocked artifact previews.
- Twenty Python tests and eight Node tests passed. Live local browser interaction was checked with empty keys and synthetic content.

Download is free; provider generation is paid. Python 3.10+ and one-time dependency setup are required. This is a source/launcher release, not a signed native binary. No provider render, live voice or live Collections request was made during validation.

## Director scope clarification

v0.1.0 is an update of the older Flask Director workspace, not a full port of the newer native production studio. It retains structured directing drafts, variations/shot-list prompts, contextual Chat/Live Voice, action-tag media workflows, Cast/Looks and transient video continuation. Persistent projects/worlds, take lineage, Stage/Compare/Storyboard, continuity evaluation and portable production bundles are not included. Those production workflows have not been validated in this release. Source-to-Video/Edit automatic AI pitches were changed to direct attachment with an explicit Video Suggest action. Existing app state is not automatically migrated.
