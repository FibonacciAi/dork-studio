const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../app/static/js/app.js'), 'utf8');
const template = fs.readFileSync(require.resolve('../app/templates/index.html'), 'utf8');
function fixture() {
    const palette = source.slice(source.indexOf('const IMAGE_STYLE_PRESETS = ['), source.indexOf('const IMAGE_INTENSITY_PROMPTS'));
    const functions = source.slice(source.indexOf('function getAvailableImageStylePresets()'), source.indexOf('function refreshStyleControls()'));
    const context = { state: {} };
    vm.createContext(context);
    vm.runInContext(palette + functions, context);
    return context;
}
test('removed saved styles cannot return through Chat, Imagine or Director', () => {
    const f = fixture();
    assert.equal(f.findImageStylePreset('adult-latex-catsuit'), null);
    const film = f.findImageStylePreset('film-still');
    assert.equal(film.name, 'Film Still');
    f.state.chatStylePreset = {id:'adult-latex-catsuit'};
    f.state.imagineStylePreset = film;
    f.state.directorStylePreset = {id:'unknown-style'};
    f.syncStylePresetAvailability();
    assert.equal(f.state.chatStylePreset, null);
    assert.equal(f.state.directorStylePreset, null);
    assert.equal(f.state.imagineStylePreset, film);
    assert.ok(f.getAvailableImageStylePresets().length > 10);
});
test('style UI has no removed switch or gated controls', () => {
    assert.doesNotMatch(template, /adult-styles-toggle|adult-chip|director-adult-status/);
    assert.doesNotMatch(source, /ADULT_IMAGE_STYLE_PRESETS|adultStylesEnabled|Adult Styles/);
    assert.match(template, /director-style-select/);
    assert.match(source, /renderChatStyleSelect/);
    assert.match(source, /renderImageStylePresets/);
});
