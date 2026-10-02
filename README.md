# dork

dork is a free, open-source creative directing app for your desktop. Start with a brief or a sketch, bring your Cast and Looks, explore directions, then make the shot.

**The app is free. AI uses your own paid provider account.** Drawing, editing drafts and browsing saved media work locally. AI requests send selected prompts and references to xAI, or optionally OpenAI, and require an internet connection.

## Start

Python 3.10 or newer is required. This release includes source and desktop launchers.

1. Download and unzip the latest source release.
2. Run **Setup dork.command** once to install the pinned dependencies.
3. Run **Launch dork.command** to open the studio.
4. Enter your own API key in **Settings** to use AI features.

If needed, run the launchers from Terminal in the extracted folder:

```sh
zsh 'Setup dork.command'
zsh 'Launch dork.command'
```

Keep the launcher terminal open while using dork. Press Ctrl-C there to quit.

On Windows or Linux, create a Python environment, install `requirements.txt`, and run `python app/dashboard.py --open --port 5357`. These platforms have not been tested.

## Create

- **Director:** turn a brief, source and taste into editable still or motion direction.
- **Draw to direct:** sketch a composition with pen, marker, eraser and undo/redo, then attach it as a guide.
- **Cast and Looks:** attach reusable character and style references.
- **Suggest directions:** request three AI pitches and choose one to edit before generating.
- **Imagine:** generate or edit images with Grok Imagine Image 2.0, quality and resolution controls.
- **Video:** animate a finished still with Fast or Quality video models.
- **Chat, Voice and artifacts:** continue your creative workflow in the same studio.

Media estimates appear before Generate. Chat, suggestions, inference, voice and cloud Collections can incur separate provider charges. Provider rates and account terms determine your bill; see [xAI pricing](https://docs.x.ai/developers/pricing).

For sketch-directed video, render a finished still first, then use its **Video** button. Both renders are billed. Active Cast/Looks in Video also prepare a billed still before animation; the estimate includes that step.

Saved media lives under `~/.dork-studio`. Keys entered in Settings are stored locally in a permissions-restricted file. Keep the app on your computer's local connection. See [selected media import](IMPORT_LOCAL_DATA.md) to bring existing work into the studio.

Optional `ffmpeg` and `ffprobe` on PATH enable last-frame extraction and stitching.

## Development

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
node --test tests/*.cjs
python3 scripts/package_release.py
```

## License

[MIT](LICENSE). See [third-party notices](THIRD_PARTY_NOTICES.md) and `LICENSES/` for dependency licenses. Provider services and models have their own terms.
