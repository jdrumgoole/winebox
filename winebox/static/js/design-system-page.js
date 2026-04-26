/* Design-system showcase page wiring (CSP-compliant — no inline scripts).

   Powers two things on /design-system:
   - the auto/dark/light theme toggle in the showcase header
   - the toast trigger buttons (data-toast="<json>") in the toasts section
*/
(function () {
    'use strict';

    function wireThemeToggle() {
        if (!window.WineBox || !window.WineBox.theme) return;
        var btn = document.getElementById('ds-theme-toggle');
        var label = document.getElementById('ds-theme-toggle-label');
        if (!btn) return;

        function render(theme) {
            if (label) label.textContent = 'Theme: ' + theme;
        }

        render(window.WineBox.theme.get());
        window.WineBox.theme.subscribe(render);
        btn.addEventListener('click', function () { window.WineBox.theme.cycle(); });
    }

    function wireToastDemos() {
        if (!window.WineBox || !window.WineBox.toast) return;
        document.querySelectorAll('[data-toast]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var spec;
                try {
                    spec = JSON.parse(btn.getAttribute('data-toast'));
                } catch (e) {
                    return;
                }
                if (Array.isArray(spec)) {
                    spec.forEach(showOne);
                } else {
                    showOne(spec);
                }
            });
        });
    }

    function showOne(spec) {
        var variant = spec && spec.variant;
        var fn = window.WineBox.toast[variant] || window.WineBox.toast.show;
        var opts = {};
        if (spec.title) opts.title = spec.title;
        if (spec.duration !== undefined) opts.duration = spec.duration;
        fn(spec.body || '', opts);
    }

    function wireFormDemo() {
        var form = document.getElementById('ds-form-demo');
        if (!form) return;
        form.addEventListener('submit', function (e) { e.preventDefault(); });
    }

    function init() {
        wireThemeToggle();
        wireToastDemos();
        wireFormDemo();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
