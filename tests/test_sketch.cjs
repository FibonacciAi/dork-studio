const {test} = require('node:test');
const assert = require('node:assert/strict');
const {SketchDocument, paint, INSTRUCTION} = require('../app/static/js/sketch.js');

const stroke = (points, extra = {}) => ({points, width: 5, color: '#000000', opacity: 1, ...extra});
const add = (doc, value) => { doc.strokes.push(value); doc.commit(); };

test('completed strokes, clear, and erasure undo as whole gestures; branching drops redo', () => {
    const doc = new SketchDocument();
    add(doc, stroke([{x: 0, y: 0}, {x: 100, y: 0}]));
    add(doc, stroke([{x: 0, y: 80}, {x: 100, y: 80}]));
    doc.eraseAlong({x: 50, y: -10}, {x: 50, y: 10}, 4); doc.commit();
    assert.equal(doc.strokes.length, 1);
    doc.undo(); assert.equal(doc.strokes.length, 2);
    doc.redo(); assert.equal(doc.strokes.length, 1);
    doc.clear(); assert.equal(doc.empty, true);
    doc.undo(); assert.equal(doc.strokes.length, 1);
    add(doc, stroke([{x: 70, y: 10}]));
    assert.equal(doc.canRedo, false);
    assert.equal(doc.strokes.length, 2);
});

test('vector eraser catches crossings between sampled points, but leaves nearby strokes', () => {
    const doc = new SketchDocument();
    add(doc, stroke([{x: 0, y: 0}, {x: 100, y: 100}]));
    add(doc, stroke([{x: 0, y: 160}, {x: 100, y: 160}]));
    add(doc, stroke([{x: 75, y: 10}]));
    doc.eraseAlong({x: 0, y: 100}, {x: 100, y: 0}, 2); doc.commit();
    assert.equal(doc.strokes.length, 2);
    doc.eraseAlong({x: 75, y: 10}, {x: 75, y: 10}, 2); doc.commit();
    assert.equal(doc.strokes.length, 1);
    assert.equal(doc.strokes[0].points[0].y, 160);
});

test('undo snapshots do not share mutable point arrays', () => {
    const doc = new SketchDocument();
    add(doc, stroke([{x: 4, y: 5}]));
    add(doc, stroke([{x: 20, y: 25}]));
    doc.undo(); doc.strokes[0].points[0].x = 400;
    doc.redo(); doc.undo();
    assert.equal(doc.strokes[0].points[0].x, 4);
});

function recorder() {
    const calls = [];
    const context = {calls};
    for (const name of ['save', 'restore', 'fillRect', 'beginPath', 'moveTo', 'lineTo', 'stroke', 'arc', 'fill']) {
        context[name] = (...args) => calls.push([name, ...args]);
    }
    return context;
}

test('flattened output paints an opaque background and excludes the display grid', () => {
    const doc = new SketchDocument();
    add(doc, stroke([{x: 10, y: 20}, {x: 30, y: 40}], {opacity: .55, width: 11}));
    const exported = recorder(), displayed = recorder();
    paint(exported, doc, 960, 540, false);
    paint(displayed, doc, 960, 540, true);
    assert.deepEqual(exported.calls[1], ['fillRect', 0, 0, 960, 540]);
    assert.equal(exported.calls.filter(([name]) => name === 'stroke').length, 1);
    assert.ok(displayed.calls.filter(([name]) => name === 'stroke').length > 1);
    assert.equal(exported.globalAlpha, .55);
    assert.equal(exported.lineWidth, 11);
    assert.equal(exported.strokeStyle, '#000000');
});

test('guidance preserves identity and looks while emphasizing composition over appearance', () => {
    assert.match(INSTRUCTION, /subject placement/);
    assert.match(INSTRUCTION, /camera angle, and motion direction/);
    assert.match(INSTRUCTION, /Preserve Cast identity and wardrobe/);
    assert.match(INSTRUCTION, /do not reproduce the paper, grid/);
    assert.match(INSTRUCTION, /not an exact opening frame/);
});
