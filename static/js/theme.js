/**
 * PyRunner theme: light / dark / system (localStorage + class on <html>)
 */
(function () {
    const STORAGE_KEY = 'pyrunner-theme';

    function getStored() {
        return localStorage.getItem(STORAGE_KEY);
    }

    function getSystemDark() {
        return window.matchMedia('(prefers-color-scheme: dark)').matches;
    }

    function resolveDark(theme) {
        if (theme === 'dark') return true;
        if (theme === 'light') return false;
        return getSystemDark();
    }

    function apply(dark) {
        document.documentElement.classList.toggle('dark', dark);
        document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
        window.dispatchEvent(new CustomEvent('pyrunner-theme-change', { detail: { dark } }));
        document.querySelectorAll('[data-theme-toggle]').forEach((btn) => {
            btn.setAttribute('aria-label', dark ? 'Switch to light mode' : 'Switch to dark mode');
            btn.setAttribute('title', dark ? 'Light mode' : 'Dark mode');
        });
    }

    function init() {
        apply(resolveDark(getStored() || 'system'));

        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
            if (getStored() === 'system' || !getStored()) {
                apply(getSystemDark());
            }
        });

        document.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-theme-toggle]');
            if (!btn) return;
            const isDark = document.documentElement.classList.contains('dark');
            const next = isDark ? 'light' : 'dark';
            localStorage.setItem(STORAGE_KEY, next);
            apply(next === 'dark');
        });
    }

    window.PyRunnerTheme = {
        isDark: () => document.documentElement.classList.contains('dark'),
        monaco: () => (document.documentElement.classList.contains('dark') ? 'vs-dark' : 'vs'),
        get: () => getStored() || 'system',
        set: (theme) => {
            localStorage.setItem(STORAGE_KEY, theme);
            apply(resolveDark(theme));
        },
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
