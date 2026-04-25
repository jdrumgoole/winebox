/* WineBox theme — auto / light / dark with localStorage persistence.

   See brand-kit/DESIGN-SYSTEM.md §1.8.

   To prevent FOUC, every page that loads this script should also include
   a tiny inline pre-paint snippet in <head>:

       <script>
         try {
           var t = localStorage.getItem('wb-theme');
           if (t === 'dark' || t === 'light') {
             document.documentElement.setAttribute('data-theme', t);
           }
         } catch (e) {}
       </script>

   Then load /static/js/theme.js for the runtime API:

       WineBox.theme.get()       // 'auto' | 'light' | 'dark'
       WineBox.theme.set('dark') // persist + apply
       WineBox.theme.cycle()     // auto -> dark -> light -> auto
       WineBox.theme.subscribe(fn)  // notified on theme change
*/
(function () {
    'use strict';

    var KEY = 'wb-theme';
    var ORDER = ['auto', 'dark', 'light'];
    var listeners = [];

    function read() {
        try {
            var t = localStorage.getItem(KEY);
            return (t === 'dark' || t === 'light') ? t : 'auto';
        } catch (e) {
            return 'auto';
        }
    }

    function persist(theme) {
        try {
            if (theme === 'auto') localStorage.removeItem(KEY);
            else localStorage.setItem(KEY, theme);
        } catch (e) {
            /* localStorage unavailable — ignore */
        }
    }

    function apply(theme) {
        var html = document.documentElement;
        if (theme === 'auto') {
            html.removeAttribute('data-theme');
        } else {
            html.setAttribute('data-theme', theme);
        }
    }

    function notify(theme) {
        for (var i = 0; i < listeners.length; i++) {
            try { listeners[i](theme); } catch (e) { /* swallow */ }
        }
    }

    function set(theme) {
        if (ORDER.indexOf(theme) === -1) return;
        persist(theme);
        apply(theme);
        notify(theme);
    }

    function cycle() {
        var next = ORDER[(ORDER.indexOf(read()) + 1) % ORDER.length];
        set(next);
        return next;
    }

    function subscribe(fn) {
        if (typeof fn !== 'function') return function () {};
        listeners.push(fn);
        return function unsubscribe() {
            var i = listeners.indexOf(fn);
            if (i !== -1) listeners.splice(i, 1);
        };
    }

    // Apply immediately on load so SPA pages stay in sync if the inline
    // pre-paint snippet was missed.
    apply(read());

    window.WineBox = window.WineBox || {};
    window.WineBox.theme = {
        get: read,
        set: set,
        cycle: cycle,
        subscribe: subscribe
    };
})();
