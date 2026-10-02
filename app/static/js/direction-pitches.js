/** Explicit creative direction pitches. Opening or selecting a pitch never renders. */
window.DorkPitches = {
    videoSceneContext(video) {
        const sources = [state.videoSceneHistory || [], state.chatVideos || []];
        for (const scenes of sources) {
            const index = scenes.findIndex(scene => scene.filename === video?.filename);
            if (index >= 0) return {
                direction: video?.prompt || scenes[index].prompt || '',
                preceding: scenes.slice(0, index + 1).slice(-5).map(scene => scene.prompt).filter(Boolean),
            };
        }
        return { direction: video?.prompt || '', preceding: video?.prompt ? [video.prompt] : [] };
    },
    captureVideoContext(video, imageUrl, frameKind = 'last frame') {
        const scene = this.videoSceneContext(video);
        state.videoFromFreeze = true;
        state.videoContinuationSource = {
            raw: String(imageUrl).split(',')[1], filename: video?.filename || '',
            direction: scene.direction, preceding: scene.preceding, frameKind,
        };
    },
    async continueSelectedVideo(showSuggestions = false) {
        const video = state.videoSelected;
        if (!video?.filename) return toast('Select a finished video first.', 'info');
        if (this.continuationLoading) return;
        this.continuationLoading = true;
        const sourceBefore = state.videoSource;
        const buttons = document.querySelectorAll('[data-continuation-action]');
        buttons.forEach(button => { button.disabled = true; });
        try {
            const response = await fetch('/api/video/lastframe', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filename: video.filename }),
            });
            const data = await response.json();
            if (data.error) throw new Error(data.error);
            if (!response.ok || !data.url) throw new Error('Could not extract the last frame.');
            const image = await fetchAsDataUrl(data.url);
            if (state.videoSelected !== video || state.videoSource !== sourceBefore) {
                return toast('The selection changed. Choose Continue again when ready.', 'info');
            }
            await loadImageAsVideoSource(image, image);
            this.captureVideoContext(video, image);
            switchPanel('video');
            savePersistence();
            window.DorkMedia?.refreshEstimates();
            if (showSuggestions) this.open(image, 'video');
            else toast('Last frame attached. Your direction is unchanged; review it before Generate.', 'success');
        } catch (error) {
            toast(error.message || 'Could not prepare continuation.', 'error');
        } finally {
            this.continuationLoading = false;
            buttons.forEach(button => { button.disabled = false; });
        }
    },
    contextFor(imageUrl, mode) {
        const raw = String(imageUrl || '').startsWith('data:') ? imageUrl.split(',')[1] : null;
        const origin = mode === 'edit' ? state.imagineSourceOrigin : state.videoSourceOrigin;
        const continuation = mode === 'video' && raw && state.videoContinuationSource?.raw === raw ? state.videoContinuationSource : null;
        const selected = state.imagineImages.find(image => image.url === imageUrl || (raw && origin?.raw === raw && image.url === origin.url)) || {};
        const bounded = value => String(value || '').slice(0, 1600);
        const names = fn => typeof fn === 'function' ? fn().slice(0, 16).map(item => String(item.name || '').slice(0, 100)) : [];
        return {
            operation: mode === 'edit' ? 'edit image' : continuation ? 'continue selected video' : 'animate image',
            continuation_video: continuation ? { filename: continuation.filename, frame: continuation.frameKind, direction: bounded(continuation.direction) } : null,
            source_direction: bounded(selected.prompt),
            creative_brief: bounded(document.getElementById('director-vision')?.value),
            director_direction: bounded(mode === 'edit' ? state.directorDraft?.image_prompt : state.directorDraft?.video_prompt),
            active_cast: names(typeof assetLibActiveChars === 'function' ? assetLibActiveChars : null),
            active_looks: names(typeof assetLibActiveStyles === 'function' ? assetLibActiveStyles : null),
            current_direction: bounded(document.getElementById(mode === 'edit' ? 'imagine-prompt' : 'video-prompt')?.value),
            creative_taste: {
                push: bounded(document.getElementById('director-push')?.value),
                interests: bounded(document.getElementById('director-interests')?.value),
                selected_style: bounded(state.directorStylePreset?.prompt),
                selected_cues: typeof getDirectorChips === 'function' ? getDirectorChips().slice(0, 16).map(bounded) : [],
            },
            preceding_scenes: continuation ? continuation.preceding.slice(-5).map(bounded) : mode === 'video' && state.videoFromFreeze && !state.videoContinuationSource ? (state.videoNarrative || []).slice(-5).map(bounded) : [],
            source_role: continuation ? `${continuation.frameKind} from the selected completed video` : window.DorkMedia?.guides.get(raw) || 'Selected source image',
        };
    },
    async requestDirections(imageUrl, mode, provider, context) {
        if (!['grok', 'chatgpt'].includes(provider)) throw new Error('Choose Grok or OpenAI.');
        const image = imageUrl.startsWith('data:') ? imageUrl : await fetchAsDataUrl(imageUrl);
        const payload = {
            system: 'You are the creative directing accomplice in Dork Director. Read the exact selected image and bounded creative context. Pitch three distinct, usable directions that preserve the working subject, Cast, Looks and story continuity. For image edits offer one subtle, one bold and one unexpected approach. For video offer cinematic, dynamic and atmospheric directions, or next-scene directions when preceding scenes are present. Describe a visible action, a specific camera move and the scene continuity in each proposal. Advance the scene rather than repeating a generic dramatic slogan. Preserve the source frame as the opening composition. Include spoken words only when the user explicitly requests dialogue or supplies a line; do not invent stock narration. If earlier scene direction is unavailable, rely on the actual selected frame and visible draft rather than inventing history. Return ONLY a JSON array of exactly three short strings. These are editable proposals; do not execute tools or claim anything was rendered.',
            messages: [{ role: 'user', content: [
                { type: 'text', text: JSON.stringify(context) },
                { type: 'image_url', image_url: { url: image } },
            ] }],
        };
        if (provider === 'grok') payload.model = DEFAULT_CHAT_MODEL;
        const response = await fetch(provider === 'chatgpt' ? '/api/chat/sync-openai' : '/api/chat/sync', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (data.error) throw new Error(data.error);
        if (!response.ok) throw new Error('The provider could not return directions.');
        const cleaned = String(data.content || '').replace(/^```(?:json)?\s*/i, '').replace(/```\s*$/, '').trim();
        let suggestions;
        try { suggestions = JSON.parse(cleaned); } catch { throw new Error('The provider did not return a direction list. No retry was submitted.'); }
        if (!Array.isArray(suggestions) || suggestions.length !== 3 || suggestions.some(value => typeof value !== 'string' || !value.trim())) {
            throw new Error('The provider did not return three directions. No retry was submitted.');
        }
        return suggestions.map(value => value.trim().slice(0, 1000));
    },
    open(imageUrl, mode = 'video') {
        if (!imageUrl) return toast('Attach a source image first.', 'info');
        document.querySelector('.prompt-suggest-overlay')?.remove();
        const context = this.contextFor(imageUrl, mode);
        const continuationSnapshot = context.continuation_video ? {
            ...state.videoContinuationSource, preceding: [...state.videoContinuationSource.preceding],
        } : null;
        const overlay = document.createElement('div');
        overlay.className = 'prompt-suggest-overlay';
        overlay.innerHTML = `<div class="prompt-suggest-card">
            <img src="${escapeAttr(imageUrl)}" class="suggest-img" alt="Selected direction source">
            <h3>${mode === 'edit' ? 'Pitch an image edit' : context.continuation_video ? 'Suggest the next scene' : 'Pitch the next motion'}</h3>
            <p class="hint">AI suggestions send this image and the visible creative context to your selected provider and are billed separately. Opening this card makes no AI request.</p>
            <label>Provider <select class="pitch-provider"><option value="grok">Grok</option><option value="chatgpt">OpenAI</option></select></label>
            <div class="pitch-options"></div>
            <div class="prompt-suggest-actions">
                <button class="btn btn-ghost pitch-close" type="button">Cancel</button>
                <button class="btn btn-ghost pitch-custom" type="button">Use my direction</button>
                <button class="btn btn-primary pitch-request" type="button">Suggest 3 directions</button>
            </div></div>`;
        const stage = async direction => {
            try {
                if (mode === 'edit') await loadImageAsEditSource(imageUrl);
                else {
                    await loadImageAsVideoSource(imageUrl, imageUrl.startsWith('data:') ? imageUrl : undefined);
                    if (continuationSnapshot && state.videoSource === continuationSnapshot.raw) {
                        state.videoContinuationSource = continuationSnapshot;
                        state.videoFromFreeze = true;
                    }
                }
                const panel = mode === 'edit' ? 'imagine' : 'video';
                const input = document.getElementById(`${panel}-prompt`);
                if (direction) input.value = direction;
                overlay.remove(); switchPanel(panel); input.focus(); savePersistence();
                window.DorkMedia?.refreshEstimates();
                toast('Direction staged. Review it, then Generate when ready.', 'success');
            } catch (error) { toast(error.message || 'Could not stage direction.', 'error'); }
        };
        overlay.querySelector('.pitch-close').addEventListener('click', () => overlay.remove());
        overlay.querySelector('.pitch-provider').value = String(state.imagineModel || '').startsWith('gpt-') ? 'chatgpt' : 'grok';
        overlay.querySelector('.pitch-custom').addEventListener('click', () => stage(''));
        overlay.addEventListener('click', event => { if (event.target === overlay) overlay.remove(); });
        const button = overlay.querySelector('.pitch-request');
        const options = overlay.querySelector('.pitch-options');
        button.addEventListener('click', async () => {
            button.disabled = true; button.textContent = 'Pitching…';
            options.textContent = 'Requesting paid AI suggestions…';
            try {
                const suggestions = await this.requestDirections(imageUrl, mode, overlay.querySelector('.pitch-provider').value, context);
                options.textContent = '';
                for (const suggestion of suggestions) {
                    const item = document.createElement('button'); item.className = 'prompt-suggest-option'; item.type = 'button';
                    item.textContent = suggestion; item.addEventListener('click', () => stage(suggestion)); options.appendChild(item);
                }
            } catch (error) { options.textContent = error.message; }
            finally { button.disabled = false; button.textContent = 'Suggest 3 directions'; }
        });
        document.body.appendChild(overlay);
    },
};

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('imagine-suggest-directions')?.addEventListener('click', () => {
        if (!state.imagineSource) return toast('Attach a source image first.', 'info');
        DorkPitches.open(state.imagineSourceUrl, 'edit');
    });
    document.getElementById('video-suggest-directions')?.addEventListener('click', () => {
        if (!state.videoSource) return toast('Attach a source image first.', 'info');
        DorkPitches.open(document.querySelector('#video-source-preview img')?.src || assetLibDataUrlForSource(state.videoSource), 'video');
    });
});
