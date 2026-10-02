# Optional: bring selected work into dork

dork uses a separate local folder and browser origin. Starting it never scans or imports an older app's media, conversations, memories or credentials. Nothing in the older app is deleted. You can choose individual items to bring across yourself.

## Source images, Cast and Looks

1. In your older app or Finder, choose only the images you want to reuse. Keep the originals.
2. Attach an image through **Director**, **Imagine** or **Video**. Attaching it is local. Director's **Infer From Image**, **Suggest directions** and **Generate** are separate, provider-billed actions.
3. For reusable references, open **+ Char** or **+ Style**, upload the selected image, and give it a name and optional tags. Activate only the references you want for the current work.
4. Copy selected brief or direction text into the editable Director fields. Review the active Cast/Looks before making an AI request.

Selected source attachment and pitches are not a project migration. The Flask edition does not import native worlds, take lineage, storyboard sequences or portable production bundles.

## Existing saved media

To add selected files to the local galleries, quit dork and copy individual image, video or audio files into the corresponding folder below, then relaunch. Create the folder if needed. Keep the originals and use a different filename if a destination file already exists.

| Selected media | Default local destination | Supported gallery extensions |
|---|---|---|
| Images | `~/.dork-studio/media/Images/` | PNG, JPG, JPEG, WebP |
| Video | `~/.dork-studio/media/Videos/` | MP4, WebM, MOV |
| Audio | `~/.dork-studio/media/Audio/` | MP3, WAV, OGG |

If you use `DORK_STATE_HOME`, use that folder's `media/` directories instead. This copies only the chosen files; it does not reconstruct their original directing context. Add any selected prompts to the editable fields yourself. An old provider job ID cannot be resumed through this import.

## Credentials and history

Re-enter your own provider key in **Settings** when you want paid features. Do not copy an older `.env`, settings directory, asset-library index, browser storage dump, account token or entire app state folder into this release. Rebuilding selected Cast/Looks through the UI keeps the new index separate.

Chat history and voice memory are not automatically imported. Copy only particular text you intentionally want to reuse. Local imported work stays out of the GitHub source release; any later provider action sends the selected prompt and inputs to that provider.
