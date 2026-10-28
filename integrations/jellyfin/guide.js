(function (scope) {
    'use strict';

    function preferredGuideHash(hash) {
        if (!/^#!?\/livetv(?:\.html)?(?:\?|$)/i.test(hash)) return null;
        const parts = hash.split('?');
        const query = new URLSearchParams(parts[1] || '');
        if (query.has('tab')) return null;
        query.set('tab', '1');
        return parts[0] + '?' + query.toString();
    }

    function channelLabel(title, number) {
        const prefix = String(number || '') + ' ';
        return title.startsWith(prefix) ? title.slice(prefix.length) : title;
    }

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = { preferredGuideHash, channelLabel };
        return;
    }
    if (scope.mediaStackGuideInstalled) return;
    scope.mediaStackGuideInstalled = true;

    function update() {
        const destination = preferredGuideHash(scope.location.hash);
        if (destination) {
            scope.location.replace(destination);
            return;
        }
        document.querySelectorAll('.guide-channelHeaderCell').forEach(function (header) {
            const number = header.querySelector('.guideChannelNumber');
            if (!number) return;
            let label = header.querySelector('.stack-tv-channel-name');
            if (!label) {
                label = document.createElement('span');
                label.className = 'stack-tv-channel-name';
                label.textContent = channelLabel(header.title, number.textContent);
                header.appendChild(label);
            }
            header.classList.toggle('stack-tv-extra', Number(number.textContent) >= 10000);
            const legacyName = header.querySelector('.guideChannelName');
            if (legacyName) legacyName.hidden = true;
        });
        document.querySelectorAll('.guideOptions').forEach(function (options) {
            if (options.querySelector('.stack-tv-guide-key')) return;
            const key = document.createElement('span');
            key.className = 'stack-tv-guide-key';
            key.textContent = 'UK guide first. Other UK channels from 10000. International from 20000.';
            options.appendChild(key);
        });
    }

    let pending = false;
    function schedule() {
        if (pending) return;
        pending = true;
        scope.requestAnimationFrame(function () {
            pending = false;
            update();
        });
    }
    scope.addEventListener('hashchange', schedule);
    function start() {
        new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
        schedule();
    }
    if (document.body) start();
    else document.addEventListener('DOMContentLoaded', start, { once: true });
})(typeof window === 'undefined' ? globalThis : window);
