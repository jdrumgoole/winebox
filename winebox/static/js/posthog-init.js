/**
 * PostHog Analytics Initialization
 * Loads configuration from backend and initializes PostHog if enabled.
 */

// Default config - will be overwritten by backend config
window.POSTHOG_CONFIG = { enabled: false, apiKey: '', host: 'https://eu.posthog.com' };

// Fetch config and initialize PostHog
(function() {
    fetch('/api/config/analytics')
        .then(function(response) { return response.json(); })
        .then(function(config) {
            if (!config.enabled || !config.api_key) return;
            window.POSTHOG_CONFIG = { enabled: true, apiKey: config.api_key, host: config.host };
            // Load PostHog script
            !function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.async=!0,p.src=s.api_host+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="capture identify alias people.set people.set_once set_config register register_once unregister opt_out_capturing has_opted_out_capturing opt_in_capturing reset isFeatureEnabled onFeatureFlags getFeatureFlag getFeatureFlagPayload reloadFeatureFlags group updateEarlyAccessFeatureEnrollment getEarlyAccessFeatures getActiveMatchingSurveys getSurveys onSessionId".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);
            posthog.init(config.api_key, {
                api_host: config.host,
                autocapture: true,
                capture_pageview: true
            });
        })
        .catch(function(err) { console.debug('PostHog config fetch failed:', err); });
})();
