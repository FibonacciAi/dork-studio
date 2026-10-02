/** Current media controls and a local drawing handoff for the recovered studio. */
function sandboxArtifactDocument(html) {
    const policy = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; media-src data: blob:; connect-src 'none'; form-action 'none'; base-uri 'none'";
    return '<meta http-equiv="Content-Security-Policy" content="' + policy + '">' + String(html || '');
}

window.DorkMedia = {
    sketchInstruction: '',
    sketchDestination: '',
    sketchData: '',
    guides: new Map(),
    estimateRevision: 0,
    isSketchSource(source) {
        const raw = String(source || '').startsWith('data:') ? String(source).split(',')[1] : source;
        return Boolean(raw && this.guides.has(raw));
    },
    instructionFor(kind) {
        const source = kind === 'director' ? state.directorSourceImage?.dataUrl : kind === 'video' ? state.videoSource : state.imagineSource;
        const raw = String(source || '').startsWith('data:') ? String(source).split(',')[1] : source;
        return this.guides.get(raw) || '';
    },
    async refreshEstimates() {
        const classic = state.videoModel === 'grok-imagine-video';
        for (const id of ['video-resolution', 'chat-video-resolution']) {
            const select = document.getElementById(id);
            if (!select) continue;
            for (const option of select.options) option.disabled = classic && option.value === '1080p';
            if (classic && select.value === '1080p') { select.value = '720p'; state.videoResolution = '720p'; }
        }
        const revision = ++this.estimateRevision;
        const refs = typeof assetLibActiveChars === 'function' && assetLib.autoAttach ? assetLibActiveChars().length + assetLibActiveStyles().length : 0;
        const imageInputs = state.imagineSource || refs ? 1 : 0;
        const videoInputs = state.videoSource || refs ? 1 : 0;
        const requests = [
            ['imagine-estimate', { kind: 'image', model: state.imagineModel, resolution: state.imagineResolution, quality: document.getElementById('imagine-quality')?.value || 'low', n: Number(state.imagineCount || 1), input_images: imageInputs, operation: imageInputs ? 'edit' : 'generate' }],
            ['video-estimate', { kind: 'video', model: state.videoModel, duration: Number(state.videoDuration || 6), resolution: state.videoResolution, input_images: videoInputs }],
        ];
        await Promise.all(requests.map(async ([id, payload]) => {
            const element = document.getElementById(id);
            if (!element) return;
            try {
                const response = await fetch('/api/media/estimate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
                const estimate = await response.json();
                if (revision !== this.estimateRevision) return;
                let total = estimate.estimate_usd;
                let preparation = '';
                if (id === 'video-estimate' && refs > 0) {
                    const stillResponse = await fetch('/api/media/estimate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind: 'image', model: state.imagineModel, resolution: state.imagineResolution, quality: document.getElementById('imagine-quality')?.value || 'low', n: 1, input_images: 1, operation: 'edit' }) });
                    const still = await stillResponse.json();
                    if (revision !== this.estimateRevision) return;
                    if (Number.isFinite(still.estimate_usd)) {
                        total += still.estimate_usd;
                        preparation = ` Includes $${still.estimate_usd.toFixed(2)} for a Cast/Looks still, then $${estimate.estimate_usd.toFixed(2)} for video.`;
                    } else preparation = ' Plus a separate paid Cast/Looks still.';
                }
                element.textContent = Number.isFinite(total)
                    ? `xAI · estimated $${total.toFixed(2)} USD.${preparation} Generate sends your prompt and selected images to xAI.`
                    : 'Provider generation is billed separately. Review your provider pricing.';
            } catch {
                if (revision === this.estimateRevision) element.textContent = 'Provider generation is billed separately.';
            }
        }));
    },
};

document.addEventListener('DOMContentLoaded', () => {
    let destination = 'imagine';
    const pad = DorkSketch.create({ onApply: async ({ dataURL, instruction }) => {
        const previous = destination === 'director' ? state.directorSourceImage?.dataUrl : destination === 'video' && state.videoSource ? assetLibDataUrlForSource(state.videoSource) : state.imagineSourceUrl;
        if (previous && !DorkMedia.isSketchSource(previous)) {
            dataURL = await compositeRefs([previous, dataURL], { labels: ['SOURCE APPEARANCE', 'COMPOSITION GUIDE'] });
            instruction += ' The SOURCE APPEARANCE tile controls subject appearance. The COMPOSITION GUIDE tile controls layout only; never reproduce the board, labels, or drawn marks.';
        }
        const raw = dataURL.split(',')[1];
        DorkMedia.sketchInstruction = instruction;
        DorkMedia.sketchDestination = destination;
        DorkMedia.sketchData = raw;
        DorkMedia.guides.set(raw, instruction);
        if (DorkMedia.guides.size > 8) DorkMedia.guides.delete(DorkMedia.guides.keys().next().value);
        if (destination === 'director') {
            state.directorSourceImage = { name: 'Composition sketch', type: 'image/png', dataUrl: dataURL };
            renderDirectorSourceImage();

        } else {
            state.imagineSource = raw;
            state.imagineSourceUrl = dataURL;
            document.getElementById('imagine-source-preview').innerHTML = `<div class="source-preview"><img src="${dataURL}" alt="Composition sketch"><button class="clear-btn" onclick="clearImagineSource()">&times;</button></div>`;
        }
        savePersistence();
        DorkMedia.refreshEstimates();
        if (destination === 'video') {
            DorkMedia.sketchDestination = 'imagine';
            const prompt = document.getElementById('video-prompt').value.trim();
            if (prompt) document.getElementById('imagine-prompt').value = prompt;
            switchPanel('imagine');
            const note = document.getElementById('sketch-video-note');
            if (note) note.hidden = false;
            toast('Sketch attached in Imagine. Render a finished still, then use its Video button. Both renders are billed separately.', 'info');
        } else {
            const note = document.getElementById('sketch-video-note');
            if (note) note.hidden = true;
            toast('Drawing attached. Review your direction, then generate when ready.', 'success');
        }
    }});
    for (const kind of ['director', 'imagine', 'video']) {
        document.getElementById(`${kind}-draw`)?.addEventListener('click', () => { destination = kind; pad.open(); });
    }
    document.getElementById('imagine-quality')?.addEventListener('change', () => DorkMedia.refreshEstimates());
    document.getElementById('provider-key-form')?.addEventListener('submit', async event => {
        event.preventDefault();
        const xai = document.getElementById('xai-key-entry');
        const openai = document.getElementById('openai-key-entry');
        const payload = {};
        if (xai.value.trim()) payload.xai_key = xai.value.trim();
        if (openai.value.trim()) payload.openai_key = openai.value.trim();
        if (!Object.keys(payload).length) return toast('Enter a key to save.', 'info');
        try {
            const response = await fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
            if (!response.ok) throw new Error('Could not save keys locally');
            xai.value = ''; openai.value = '';
            await loadKeyStatus();
            toast('Keys saved locally. Model availability can be refreshed in Settings.', 'success');
        } catch (error) { toast(error.message, 'error'); }
    });
    DorkMedia.refreshEstimates();
});
