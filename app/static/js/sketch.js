/* Local sketch-to-direction controls adapted from the owned native drawing pad.
   This module never calls a provider. Applying only hands an image to the host. */
(function (root) {
    'use strict';

    const INSTRUCTION = 'HIGH-PRIORITY BLOCKING SKETCH: treat this drawing as a strong composition guide alongside the user’s direction and active Cast and Looks. Closely follow its framing, subject placement, relative scale, silhouette, spatial relationships, negative space, camera angle, and motion direction. Preserve Cast identity and wardrobe and use Looks for appearance, palette, texture, and lighting. Translate the sketch into the requested finished visual; do not reproduce the paper, grid, borders, or drawn line style unless the user asks for them. A sketch is a composition hint, not an exact opening frame.';
    const PALETTE = [
        ['Black ink', '#000000'], ['Dork teal', '#2dd4bf'], ['Cyan', '#7dd3fc'],
        ['Pink', '#fb7185'], ['Coral', '#ff6c61'], ['Violet', '#8f6bfa'], ['White', '#ffffff']
    ];
    const clone = value => JSON.parse(JSON.stringify(value));

    function pointDistance(point, start, end) {
        const dx = end.x - start.x, dy = end.y - start.y;
        const length = dx * dx + dy * dy;
        const t = length ? Math.max(0, Math.min(1,
            ((point.x - start.x) * dx + (point.y - start.y) * dy) / length)) : 0;
        return Math.hypot(point.x - start.x - t * dx, point.y - start.y - t * dy);
    }

    function segmentDistance(a, b, c, d) {
        const orient = (p, q, r) => (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x);
        const a1 = orient(a, b, c), a2 = orient(a, b, d);
        const b1 = orient(c, d, a), b2 = orient(c, d, b);
        if (((a1 > 0 && a2 < 0) || (a1 < 0 && a2 > 0))
            && ((b1 > 0 && b2 < 0) || (b1 < 0 && b2 > 0))) return 0;
        return Math.min(pointDistance(a, c, d), pointDistance(b, c, d),
            pointDistance(c, a, b), pointDistance(d, a, b));
    }

    class SketchDocument {
        constructor() {
            this.strokes = [];
            this.history = [[]];
            this.historyIndex = 0;
        }
        get empty() { return this.strokes.length === 0; }
        get canUndo() { return this.historyIndex > 0; }
        get canRedo() { return this.historyIndex < this.history.length - 1; }
        commit() {
            if (JSON.stringify(this.strokes) === JSON.stringify(this.history[this.historyIndex])) return;
            this.history = this.history.slice(0, this.historyIndex + 1);
            this.history.push(clone(this.strokes));
            if (this.history.length > 101) this.history.shift();
            this.historyIndex = this.history.length - 1;
        }
        undo() {
            if (!this.canUndo) return;
            this.strokes = clone(this.history[--this.historyIndex]);
        }
        redo() {
            if (!this.canRedo) return;
            this.strokes = clone(this.history[++this.historyIndex]);
        }
        clear() { this.strokes = []; this.commit(); }
        eraseAlong(start, end, radius) {
            this.strokes = this.strokes.filter(stroke => {
                const points = stroke.points;
                const reach = radius + stroke.width / 2;
                if (points.length === 1) return pointDistance(points[0], start, end) > reach;
                for (let i = 1; i < points.length; i++) {
                    if (segmentDistance(points[i - 1], points[i], start, end) <= reach) return false;
                }
                return true;
            });
        }
    }

    function paint(context, document, width, height, includeGrid) {
        context.save();
        context.globalAlpha = 1;
        context.fillStyle = '#f6f6f6';
        context.fillRect(0, 0, width, height);
        if (includeGrid) {
            for (let x = 0; x <= width; x += 24) {
                context.beginPath();
                context.strokeStyle = x % 96 === 0 ? 'rgba(0,0,0,.13)' : 'rgba(0,0,0,.055)';
                context.lineWidth = x % 96 === 0 ? .8 : .5;
                context.moveTo(x, 0); context.lineTo(x, height); context.stroke();
            }
            for (let y = 0; y <= height; y += 24) {
                context.beginPath();
                context.strokeStyle = y % 96 === 0 ? 'rgba(0,0,0,.13)' : 'rgba(0,0,0,.055)';
                context.lineWidth = y % 96 === 0 ? .8 : .5;
                context.moveTo(0, y); context.lineTo(width, y); context.stroke();
            }
        }
        context.lineCap = 'round'; context.lineJoin = 'round';
        for (const stroke of document.strokes) {
            context.globalAlpha = stroke.opacity;
            context.strokeStyle = stroke.color; context.fillStyle = stroke.color;
            context.lineWidth = stroke.width;
            context.beginPath();
            const first = stroke.points[0];
            if (!first) continue;
            if (stroke.points.length === 1) {
                context.arc(first.x, first.y, stroke.width / 2, 0, Math.PI * 2);
                context.fill();
            } else {
                context.moveTo(first.x, first.y);
                stroke.points.slice(1).forEach(point => context.lineTo(point.x, point.y));
                context.stroke();
            }
        }
        context.restore();
    }

    let nextID = 0;
    class SketchPad {
        constructor(options) {
            if (!options || typeof options.onApply !== 'function') {
                throw new TypeError('DorkSketch requires an onApply attachment callback.');
            }
            this.options = options;
            this.document = new SketchDocument();
            this.width = Math.min(2048, Math.max(64, Math.round(options.width || 960)));
            this.height = Math.min(2048, Math.max(64, Math.round(options.height || 540)));
            this.tool = 'pen'; this.color = PALETTE[0][1]; this.strokeWidth = 5;
            this.grid = true; this.gesture = null; this.applying = false;
            this.id = `dork-sketch-${++nextID}`;
            this.build();
        }

        build() {
            const dialog = document.createElement('dialog');
            dialog.className = 'dork-sketch';
            dialog.setAttribute('aria-labelledby', `${this.id}-title`);
            dialog.setAttribute('aria-describedby', `${this.id}-description`);
            dialog.innerHTML = `
                <header class="dork-sketch-header">
                    <div><h2 id="${this.id}-title">Draw to direct</h2>
                    <p id="${this.id}-description">Block the shot: pose, framing, camera, movement.</p></div>
                    <button type="button" data-action="cancel" aria-label="Close sketch pad">Close</button>
                </header>
                <div class="dork-sketch-tools" role="toolbar" aria-label="Sketch tools">
                    <div class="dork-sketch-tool-group">
                        <button type="button" data-tool="pen" aria-pressed="true">Pen</button>
                        <button type="button" data-tool="marker" aria-pressed="false">Marker</button>
                        <button type="button" data-tool="eraser" aria-pressed="false" title="Erase a whole stroke">Eraser</button>
                    </div>
                    <div class="dork-sketch-tool-group">
                        <button type="button" data-action="undo" aria-label="Undo stroke" title="Undo (⌘/Ctrl Z)">Undo</button>
                        <button type="button" data-action="redo" aria-label="Redo stroke" title="Redo (⌘/Ctrl Shift Z)">Redo</button>
                        <button type="button" data-action="clear">Clear</button>
                    </div>
                    <div class="dork-sketch-colors" role="group" aria-label="Ink color"></div>
                    <label class="dork-sketch-width">Width
                        <input type="range" min="1" max="18" step="1" value="5" aria-label="Stroke width">
                        <output>5</output>
                    </label>
                    <button type="button" data-action="grid" aria-pressed="true">Grid</button>
                </div>
                <div class="dork-sketch-paper"><canvas aria-label="Sketch canvas. Draw with a mouse, finger, or pen."></canvas></div>
                <p class="dork-sketch-status" role="status" aria-live="polite"></p>
                <footer class="dork-sketch-footer"><p>Use sketch attaches a guide alongside your direction and Cast/Looks. Generation starts only when you choose Render.</p>
                    <button type="button" data-action="apply" class="dork-sketch-apply" disabled>Use sketch</button>
                </footer>`;
            this.dialog = dialog;
            this.canvas = dialog.querySelector('canvas');
            this.canvas.width = this.width; this.canvas.height = this.height;
            this.canvas.style.aspectRatio = `${this.width} / ${this.height}`;
            dialog.querySelector('.dork-sketch-paper').style.setProperty('--sketch-ratio', this.width / this.height);
            this.context = this.canvas.getContext('2d');
            this.status = dialog.querySelector('.dork-sketch-status');
            const colors = dialog.querySelector('.dork-sketch-colors');
            PALETTE.forEach(([name, color]) => {
                const button = document.createElement('button');
                button.type = 'button'; button.dataset.color = color;
                button.style.setProperty('--sketch-color', color);
                button.setAttribute('aria-label', name); button.title = name;
                button.setAttribute('aria-pressed', String(color === this.color));
                colors.append(button);
            });
            dialog.addEventListener('click', event => this.click(event));
            dialog.querySelector('input').addEventListener('input', event => {
                this.strokeWidth = Number(event.target.value);
                dialog.querySelector('output').value = String(this.strokeWidth);
            });
            dialog.addEventListener('keydown', event => {
                if (!(event.metaKey || event.ctrlKey) || this.applying) return;
                if (event.key.toLowerCase() === 'z') {
                    event.preventDefault(); this.finishGesture();
                    if (event.shiftKey) this.document.redo(); else this.document.undo();
                    this.render();
                } else if (event.key.toLowerCase() === 'y') {
                    event.preventDefault(); this.finishGesture(); this.document.redo(); this.render();
                }
            });
            dialog.addEventListener('close', () => {
                this.finishGesture(); this.returnFocus?.focus();
            });
            this.canvas.addEventListener('pointerdown', event => this.startGesture(event));
            this.canvas.addEventListener('pointermove', event => this.moveGesture(event));
            ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(type => {
                this.canvas.addEventListener(type, event => {
                    if (this.gesture?.pointerID === event.pointerId) {
                        if (type === 'pointerup') this.moveGesture(event);
                        this.finishGesture();
                    }
                });
            });
            document.body.append(dialog);
            this.render();
        }

        click(event) {
            const button = event.target.closest('button');
            if (!button || this.applying) return;
            this.finishGesture();
            if (button.dataset.tool) this.tool = button.dataset.tool;
            else if (button.dataset.color) {
                this.color = button.dataset.color;
                if (this.tool === 'eraser') this.tool = 'pen';
            } else {
                switch (button.dataset.action) {
                    case 'cancel': this.dialog.close(); break;
                    case 'undo': this.document.undo(); break;
                    case 'redo': this.document.redo(); break;
                    case 'clear': this.document.clear(); break;
                    case 'grid': this.grid = !this.grid; break;
                    case 'apply': this.apply(); break;
                }
            }
            this.render();
        }

        position(event) {
            const box = this.canvas.getBoundingClientRect();
            return {x: Math.max(0, Math.min(this.width, (event.clientX - box.left) * this.width / box.width)),
                y: Math.max(0, Math.min(this.height, (event.clientY - box.top) * this.height / box.height))};
        }

        startGesture(event) {
            if (this.applying || this.gesture || event.button !== 0) return;
            event.preventDefault();
            this.canvas.setPointerCapture(event.pointerId);
            const point = this.position(event);
            this.gesture = {pointerID: event.pointerId, tool: this.tool, last: point};
            if (this.tool === 'eraser') this.document.eraseAlong(point, point, this.strokeWidth);
            else {
                this.gesture.stroke = {color: this.color, opacity: this.tool === 'marker' ? .55 : 1,
                    width: this.strokeWidth * (this.tool === 'marker' ? 2.2 : 1), points: [point]};
                this.document.strokes.push(this.gesture.stroke);
            }
            this.render();
        }

        moveGesture(event) {
            if (!this.gesture || this.gesture.pointerID !== event.pointerId) return;
            event.preventDefault();
            const samples = event.getCoalescedEvents ? event.getCoalescedEvents() : [];
            for (const sample of samples.length ? samples : [event]) {
                const point = this.position(sample);
                if (this.gesture.tool === 'eraser') {
                    this.document.eraseAlong(this.gesture.last, point, this.strokeWidth);
                } else this.gesture.stroke.points.push(point);
                this.gesture.last = point;
            }
            this.render();
        }

        finishGesture() {
            if (!this.gesture) return;
            const pointerID = this.gesture.pointerID;
            this.gesture = null; this.document.commit();
            if (this.canvas.hasPointerCapture(pointerID)) this.canvas.releasePointerCapture(pointerID);
            this.render();
        }

        render() {
            paint(this.context, this.document, this.width, this.height, this.grid);
            const query = selector => this.dialog.querySelector(selector);
            query('[data-action="undo"]').disabled = !this.document.canUndo || this.applying;
            query('[data-action="redo"]').disabled = !this.document.canRedo || this.applying;
            query('[data-action="clear"]').disabled = this.document.empty || this.applying;
            query('[data-action="apply"]').disabled = this.document.empty || this.applying;
            query('[data-action="apply"]').textContent = this.applying ? 'Attaching…' : 'Use sketch';
            query('[data-action="grid"]').setAttribute('aria-pressed', String(this.grid));
            this.dialog.querySelectorAll('[data-tool]').forEach(button =>
                button.setAttribute('aria-pressed', String(button.dataset.tool === this.tool)));
            this.dialog.querySelectorAll('[data-color]').forEach(button =>
                button.setAttribute('aria-pressed', String(button.dataset.color === this.color)));
            this.canvas.dataset.tool = this.tool;
        }

        open() {
            if (this.dialog.open) return;
            this.returnFocus = document.activeElement;
            this.status.textContent = '';
            this.dialog.showModal();
            this.render();
        }

        async apply() {
            this.finishGesture();
            if (this.document.empty || this.applying) return;
            this.applying = true; this.status.textContent = ''; this.render();
            try {
                // Render separately so display-only grid lines can never enter the attachment.
                const output = document.createElement('canvas');
                output.width = this.width; output.height = this.height;
                paint(output.getContext('2d'), this.document, this.width, this.height, false);
                const dataURL = output.toDataURL('image/png');
                await this.options.onApply({dataURL, mimeType: 'image/png', instruction: INSTRUCTION,
                    width: this.width, height: this.height, role: 'sketch'});
                this.dialog.close();
            } catch (error) {
                this.status.textContent = `Could not attach sketch: ${error.message || 'Try again.'}`;
            } finally { this.applying = false; this.render(); }
        }

        destroy() { this.finishGesture(); if (this.dialog.open) this.dialog.close(); this.dialog.remove(); }
    }

    const api = {create: options => new SketchPad(options), SketchDocument, paint,
        pointDistance, segmentDistance, INSTRUCTION, PALETTE};
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    else root.DorkSketch = api;
})(typeof window !== 'undefined' ? window : globalThis);
