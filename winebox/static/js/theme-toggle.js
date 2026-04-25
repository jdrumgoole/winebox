/* WineBox theme toggle wiring for the main app header.
   Pairs the #theme-toggle button (in index.html) with WineBox.theme.cycle().
   Loaded after theme.js so window.WineBox.theme is available.

   Kept in an external file (not inline) for CSP compliance — the project
   CSP forbids inline <script> blocks. */
(function () {
    'use strict';

    function init() {
        var btn = document.getElementById('theme-toggle');
        if (!btn || !window.WineBox || !window.WineBox.theme) return;

        var icons = {
            auto: btn.querySelector('.theme-icon-auto'),
            light: btn.querySelector('.theme-icon-light'),
            dark: btn.querySelector('.theme-icon-dark')
        };
        var labels = {
            auto: 'Theme: follow system (click to switch)',
            light: 'Theme: light (click to switch)',
            dark: 'Theme: dark (click to switch)'
        };

        function render(theme) {
            Object.keys(icons).forEach(function (k) {
                if (icons[k]) icons[k].style.display = (k === theme) ? '' : 'none';
            });
            btn.title = labels[theme] || labels.auto;
            btn.setAttribute('aria-label', labels[theme] || labels.auto);
        }

        render(window.WineBox.theme.get());
        window.WineBox.theme.subscribe(render);
        btn.addEventListener('click', function () { window.WineBox.theme.cycle(); });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
