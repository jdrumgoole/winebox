/* WineBox toast — transient feedback floating outside the page flow.
   See brand-kit/DESIGN-SYSTEM.md §2.10 and /design-system#toasts.

   Usage:
     WineBox.toast.success("Bottle added");
     WineBox.toast.error("Couldn't import — three rows missing a wine name.");
     WineBox.toast.warning("Vintage looks unusual", { title: "Double-check" });
     WineBox.toast.info("Tip — drag a photo onto the scan area");

   Options: { title, duration (ms; 0 = sticky), dismissible (default true) }.
   Errors are sticky by default; pass duration explicitly to override.
*/
(function () {
    'use strict';

    var ICONS = {
        success: '<svg class="icon icon-md" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6L9 17l-5-5"/></svg>',
        warning: '<svg class="icon icon-md" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 8v4M12 16h.01"/></svg>',
        error:   '<svg class="icon icon-md" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M15 9l-6 6M9 9l6 6"/></svg>',
        info:    '<svg class="icon icon-md" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 8v4M12 16h.01"/></svg>'
    };

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    function getContainer() {
        var el = document.getElementById('toast-container');
        if (!el) {
            el = document.createElement('div');
            el.id = 'toast-container';
            document.body.appendChild(el);
        }
        if (!el.classList.contains('toast-container')) {
            el.classList.add('toast-container');
        }
        el.setAttribute('aria-live', 'polite');
        el.setAttribute('aria-atomic', 'false');
        return el;
    }

    function show(messageOrConfig, opts) {
        var cfg;
        if (typeof messageOrConfig === 'string') {
            cfg = Object.assign({}, opts || {}, { body: messageOrConfig });
        } else {
            cfg = Object.assign({}, messageOrConfig || {});
        }

        var variant = (cfg.variant && ICONS[cfg.variant]) ? cfg.variant : 'info';
        var role = (variant === 'error' || variant === 'warning') ? 'alert' : 'status';
        var dismissible = cfg.dismissible !== false;
        var duration = cfg.duration !== undefined
            ? cfg.duration
            : (variant === 'error' ? 0 : 4000);

        var toast = document.createElement('div');
        toast.className = 'toast toast-' + variant;
        toast.setAttribute('role', role);

        var html = ICONS[variant] + '<div class="toast-body">';
        if (cfg.title) {
            html += '<span class="toast-title">' + escapeHtml(cfg.title) + '</span>';
        }
        html += escapeHtml(cfg.body || '') + '</div>';
        if (dismissible) {
            html += '<button class="toast-close" type="button" aria-label="Dismiss">&times;</button>';
        }
        toast.innerHTML = html;

        getContainer().appendChild(toast);

        var timer = null;
        function dismiss() {
            if (toast.classList.contains('is-leaving')) return;
            if (timer) { clearTimeout(timer); timer = null; }
            toast.classList.add('is-leaving');
            toast.addEventListener('animationend', function () {
                if (toast.parentNode) toast.parentNode.removeChild(toast);
            }, { once: true });
        }

        if (dismissible) {
            toast.querySelector('.toast-close').addEventListener('click', dismiss);
        }
        if (duration > 0) {
            timer = setTimeout(dismiss, duration);
        }

        return { dismiss: dismiss, element: toast };
    }

    function variantHelper(variant) {
        return function (message, opts) {
            return show(message, Object.assign({ variant: variant }, opts || {}));
        };
    }

    window.WineBox = window.WineBox || {};
    window.WineBox.toast = {
        show: show,
        success: variantHelper('success'),
        warning: variantHelper('warning'),
        error: variantHelper('error'),
        info: variantHelper('info')
    };
})();
