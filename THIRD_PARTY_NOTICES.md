# Third-party notices

The dork application code is released under the MIT License in `LICENSE`, by the owner who authorized publication of this recovered app. The drawing controls are a JavaScript implementation of the owner's native drawing workflow; no native app binaries, service credentials or private assets are included.

Runtime dependencies are downloaded from PyPI when the user explicitly runs Setup. Their licenses do not change the dork source license. Full installed license notices are retained in `LICENSES/`; no dependency binaries or wheels are bundled.

| Dependency | Tested version | License | Upstream |
|---|---:|---|---|
| Flask | 3.1.3 | BSD-3-Clause | https://github.com/pallets/flask |
| Werkzeug | 3.1.8 | BSD-3-Clause | https://github.com/pallets/werkzeug |
| Jinja2 | 3.1.6 | BSD-3-Clause | https://github.com/pallets/jinja |
| MarkupSafe | 3.0.3 | BSD-3-Clause | https://github.com/pallets/markupsafe |
| itsdangerous | 2.2.0 | BSD-3-Clause | https://github.com/pallets/itsdangerous |
| click | 8.1.8 | BSD-3-Clause | https://github.com/pallets/click |
| blinker | 1.9.0 | MIT | https://github.com/pallets-eco/blinker |
| python-dotenv | 1.2.1 | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| Pillow | 11.3.0 | MIT-CMU | https://github.com/python-pillow/Pillow |

Pillow's installed distribution may incorporate additional libraries; its upstream distribution notices remain applicable. The release imports Pillow and does not redistribute its binaries. Python and Node are external runtimes, not included in the release. Node is needed only for drawing tests.

FFmpeg/ffprobe are optional external tools. Their particular build can be LGPL or GPL depending on enabled components; obtain them from a source that supplies its corresponding licenses. No FFmpeg executable is included here. See https://ffmpeg.org/legal.html.

xAI and OpenAI APIs, names and model services remain owned by their respective providers. dork is an independent client. Model weights, provider services and generated content are not licensed by the application's MIT file. Relevant service documentation: https://docs.x.ai/ and https://platform.openai.com/docs/.
